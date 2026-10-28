import json
import os
import shlex
import subprocess
from importlib.metadata import version as pkg_version
from pathlib import Path
from unittest.mock import patch

import pytest
from expects import *
from typer.testing import CliRunner

from pdp.cli import app
from pdp.remote import SSH_OPTS, load_remote, parse_env, pull_args, push_args

SPEC = (
    f"pdp[dagster] @ git+https://github.com/ChrisDonovan307/pdp@v{pkg_version('pdp')}"
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "PDP_REMOTE_HOST",
        "PDP_REMOTE_PATH",
        "PDP_REMOTE_PORT",
        "PDP_REMOTE_SPEC",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def remote_project(real_pdp):
    Path(".env").write_text("PDP_REMOTE_HOST=me@login1\nPDP_REMOTE_PATH=/gpfs/proj\n")
    return real_pdp


def fake_run(
    session=False,
    run_session=False,
    remote_has_pdp=True,
    squeue="",
    ports=(False, True),
    uvx=True,
    reachable=True,
    last_run=None,
    stream_rc=0,
):
    """Patch subprocess.run, answer ssh commands, record every argv"""
    port_answers = list(ports)

    def run(argv, **kwargs):
        cmd = argv[-1]
        rc = 0
        stdout = ""
        if not reachable:
            rc = 255
        elif cmd.startswith("tail "):
            rc = stream_rc
        elif "has-session" in cmd:
            up = run_session if cmd.endswith("-run") else session
            rc = 0 if up else 1
        elif "/dev/tcp/" in cmd:
            is_open = port_answers.pop(0) if len(port_answers) > 1 else port_answers[0]
            rc = 0 if is_open else 1
        elif cmd.startswith("test -e"):
            rc = 0 if remote_has_pdp else 1
        elif cmd == "command -v uvx":
            rc = 0 if uvx else 1
        elif cmd.startswith("squeue"):
            stdout = squeue
        elif cmd.startswith("cat "):
            rc = 1 if last_run is None else 0
            stdout = json.dumps(last_run)
        return subprocess.CompletedProcess(argv, rc, stdout=stdout)

    return patch("subprocess.run", side_effect=run)


def invoke(*args):
    return CliRunner(mix_stderr=False).invoke(app, list(args))


def argvs(run):
    return [c.args[0] for c in run.call_args_list]


def remote_cmds(run):
    """Remote shell commands sent over ssh in order"""
    return [a[-1] for a in argvs(run) if a[0] == "ssh" and "-N" not in a]


def session_cmd(run):
    return next(c for c in remote_cmds(run) if "new-session" in c)


def first(run, program):
    return next(a for a in argvs(run) if a[0] == program)


def pushed_or_pulled(run):
    return any(a[0] == "rsync" for a in argvs(run))


def programs(run):
    """First word of each remote command, or rsync"""
    return [a[0] if a[0] == "rsync" else a[-1].split()[0] for a in argvs(run)]


class TestLoadRemote:
    def test_parses_comments_blanks_and_equals_in_values(self, tmp_path):
        (tmp_path / ".env").write_text(
            "# comment\n\nPDP_REMOTE_HOST=me@login1\nPDP_REMOTE_PATH=/gpfs/a=b\n"
        )

        expect(parse_env(tmp_path / ".env")).to(
            equal({"PDP_REMOTE_HOST": "me@login1", "PDP_REMOTE_PATH": "/gpfs/a=b"})
        )

    def test_environment_wins_over_env_file(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("PDP_REMOTE_HOST=file\nPDP_REMOTE_PATH=/p/\n")
        monkeypatch.setenv("PDP_REMOTE_HOST", "environ")

        remote = load_remote(tmp_path)

        expect(remote.host).to(equal("environ"))
        expect(remote.path).to(equal("/p"))
        expect(remote.port).to(equal("3000"))
        expect(remote.spec).to(equal(SPEC))

    @pytest.mark.usefixtures("real_pdp")
    def test_missing_keys_named_and_exit_1(self):
        with fake_run() as run:
            result = invoke("remote", "push")

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("PDP_REMOTE_HOST", "PDP_REMOTE_PATH"))
        run.assert_not_called()


class TestSshOptions:
    @pytest.mark.usefixtures("remote_project")
    def test_every_ssh_and_rsync_call_shares_the_control_master(self):
        with fake_run(remote_has_pdp=False, squeue="1 pdp-r-t\n") as run:
            invoke("remote", "start")
            invoke("remote", "pull", "--force")
            invoke("remote", "stop")

        opts = " ".join(SSH_OPTS)
        for argv in argvs(run):
            if argv[0] == "ssh":
                expect(" ".join(argv)).to(contain(opts))
            else:
                expect(argv[:3]).to(equal(["rsync", "-e", f"ssh {opts}"]))
        expect({a[0] for a in argvs(run)}).to(equal({"ssh", "rsync"}))


@pytest.fixture
def project_tree(tmp_path):
    src = tmp_path / "src_proj"
    for d in (
        "hand",
        "t/src",
        "t/input",
        "t/output",
        "u/output",
        ".dagster",
        ".git",
        ".venv",
    ):
        (src / d).mkdir(parents=True)
    for f in (
        "pdp.yml",
        "hand/notes",
        "t/task.yml",
        "t/src/run.sh",
        "t/output/o",
        "u/output/u",
        ".dagster/db",
        ".git/HEAD",
        ".venv/py",
        ".env",
    ):
        (src / f).write_text(f)
    (src / "t/input/u").symlink_to("../../u/output")
    os.utime(src / "t/src/run.sh", (1000, 1000))

    dest = tmp_path / "dest"
    dest.mkdir()
    return src, dest


def rsync(args):
    subprocess.run(["rsync", *args], check=True)


class TestPushRsync:
    def test_sends_project_and_keeps_symlinks_and_mtimes(self, project_tree):
        src, dest = project_tree
        rsync(push_args(src, f"{dest}/", send_output=False))

        for f in ("pdp.yml", "hand/notes", "t/task.yml", "t/src/run.sh"):
            expect((dest / f).is_file()).to(be_true)
        expect((dest / "t/input/u").is_symlink()).to(be_true)
        expect(os.readlink(dest / "t/input/u")).to(equal("../../u/output"))
        expect((dest / "t/src/run.sh").stat().st_mtime).to(equal(1000))

    def test_output_only_on_first_push_and_never_local_state(self, project_tree):
        src, dest = project_tree

        rsync(push_args(src, f"{dest}/", send_output=False))
        expect((dest / "t/output").exists()).to(be_false)

        rsync(push_args(src, f"{dest}/", send_output=True))
        expect((dest / "t/output/o").is_file()).to(be_true)

        for f in (".dagster", ".git", ".venv", ".env"):
            expect((dest / f).exists()).to(be_false)


class TestPush:
    @pytest.mark.parametrize(
        "running, session",
        [({"session": True}, "pdp-test"), ({"run_session": True}, "pdp-test-run")],
    )
    @pytest.mark.usefixtures("remote_project")
    def test_refuses_while_either_session_runs(self, running, session):
        with fake_run(**running) as run:
            result = invoke("remote", "push")

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain(f"session {session} running"))
        expect(pushed_or_pulled(run)).to(be_false)

    @pytest.mark.parametrize(
        "remote_has_pdp, sends_output", [(True, False), (False, True)]
    )
    @pytest.mark.usefixtures("remote_project")
    def test_sends_output_only_without_remote_pdp_yml(
        self, remote_has_pdp, sends_output
    ):
        with fake_run(remote_has_pdp=remote_has_pdp) as run:
            result = invoke("remote", "push")

        expect(result.exit_code).to(equal(0))
        expect(remote_cmds(run)).to(contain("test -e /gpfs/proj/pdp.yml"))
        rsync_argv = first(run, "rsync")
        expect(rsync_argv[-1]).to(equal("me@login1:/gpfs/proj/"))
        expect("--exclude=/*/output/" not in rsync_argv).to(equal(sends_output))


def new_session_cmd(port):
    dagster = f"cd /gpfs/proj && uvx --from '{SPEC}' pdp dagster dev --slurm -p {port}"
    return ["tmux", "new-session", "-d", "-s", "pdp-test", dagster]


class TestRemoteStart:
    @pytest.mark.usefixtures("remote_project")
    def test_pushes_starts_session_then_tunnels(self):
        with fake_run() as run:
            result = invoke("remote", "start")

        expect(result.exit_code).to(equal(0))
        expect(programs(run)).to(
            equal(
                [
                    "tmux",  # dagster session?
                    "command",  # uvx?
                    "bash",  # port free?
                    "tmux",  # run session?
                    "test",  # pushed before?
                    "rsync",
                    "tmux",  # new-session
                    "bash",  # dagster listening?
                    "me@login1",  # tunnel
                ]
            )
        )
        expect(shlex.split(session_cmd(run))).to(equal(new_session_cmd(3000)))
        expect(argvs(run)[-1][-4:]).to(
            equal(["-N", "-L", "3000:localhost:3000", "me@login1"])
        )
        expect(result.stdout).to(contain("http://127.0.0.1:3000"))

    @pytest.mark.usefixtures("remote_project")
    def test_running_session_skips_push_and_start(self):
        with fake_run(session=True) as run:
            result = invoke("remote", "start")

        expect(result.exit_code).to(equal(0))
        expect(remote_cmds(run)).to(equal(["tmux has-session -t =pdp-test"]))
        expect(pushed_or_pulled(run)).to(be_false)
        expect(argvs(run)[-1]).to(contain("-N"))

    @pytest.mark.parametrize(
        "remote_state, named",
        [({"ports": (True,)}, "3000"), ({"uvx": False}, "uvx")],
        ids=["port_in_use", "no_uvx"],
    )
    @pytest.mark.usefixtures("remote_project")
    def test_refuses_before_push(self, remote_state, named):
        with fake_run(**remote_state) as run:
            result = invoke("remote", "start")

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain(named))
        expect(pushed_or_pulled(run)).to(be_false)
        expect(remote_cmds(run)).not_to(contain(new_session_cmd(3000)[-1]))

    @pytest.mark.usefixtures("remote_project")
    def test_dagster_dying_on_startup_is_reported_without_tunnel(self):
        with fake_run(ports=(False,)) as run:
            result = invoke("remote", "start")

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain(new_session_cmd(3000)[-1]))
        expect(argvs(run)[-1]).not_to(contain("-N"))

    @pytest.mark.usefixtures("remote_project")
    def test_waits_until_dagster_listens(self):
        # neither session runs at first, then Dagster's is alive while it starts
        sessions = [False, False, True, True]
        with (
            fake_run(ports=(False, False, False, True)) as run,
            patch("time.sleep"),
            patch("pdp.remote.has_session", side_effect=sessions),
        ):
            result = invoke("remote", "start")

        expect(result.exit_code).to(equal(0))
        port_checks = [c for c in remote_cmds(run) if "/dev/tcp/" in c]
        expect(port_checks).to(have_len(4))
        expect(argvs(run)[-1]).to(contain("-N"))

    @pytest.mark.parametrize(
        "flag, env, port",
        [(["-p", "4000"], {}, 4000), ([], {"PDP_REMOTE_PORT": "3100"}, 3100)],
    )
    @pytest.mark.usefixtures("remote_project")
    def test_port_reaches_remote_dagster_and_tunnel(self, monkeypatch, flag, env, port):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        with fake_run() as run:
            invoke("remote", "start", *flag)

        expect(shlex.split(session_cmd(run))).to(equal(new_session_cmd(port)))
        expect(argvs(run)[-1]).to(contain(f"{port}:localhost:{port}"))


@pytest.mark.usefixtures("real_pdp")
def test_local_port_reaches_dagster_dev():
    with patch("subprocess.Popen") as popen:
        popen.return_value.wait.return_value = 0
        invoke("dagster", "dev", "-p", "4000")

    expect(popen.call_args.args[0][-2:]).to(equal(["-p", "4000"]))


class TestStop:
    @pytest.mark.parametrize(
        "squeue, cancel",
        [
            (
                "11 pdp-run1-import\n12 my-other-job\n13 pdp-run1-clean\n",
                ["scancel 11 13"],
            ),
            ("12 my-other-job\n", []),
        ],
    )
    @pytest.mark.usefixtures("remote_project")
    def test_kills_both_sessions_then_cancels_only_pdp_jobs(self, squeue, cancel):
        with fake_run(squeue=squeue) as run:
            result = invoke("remote", "stop")

        expect(result.exit_code).to(equal(0))
        expect(remote_cmds(run)).to(
            equal(
                [
                    "tmux kill-session -t =pdp-test",
                    "tmux kill-session -t =pdp-test-run",
                    "squeue --me -h -o '%i %j'",
                    *cancel,
                ]
            )
        )
        expect(result.stdout).to(
            contain(
                "Stopped session pdp-test on me@login1",
                "Stopped session pdp-test-run on me@login1",
            )
        )
        expect("Cancelled Slurm jobs: 11, 13" in result.stdout).to(equal(bool(cancel)))


class TestStatus:
    @pytest.mark.usefixtures("remote_project")
    def test_reports_project_session_dagster_and_pdp_jobs(self):
        squeue = "11 pdp-run1-import\n12 my-other-job\n"
        with fake_run(session=True, ports=(True,), squeue=squeue):
            result = invoke("remote", "status")

        expect(result.exit_code).to(equal(0))
        expect(result.stdout).to(
            contain(
                "me@login1",
                "/gpfs/proj",
                "project:  exists",
                "pdp-test running",
                "listening on 3000",
                "jobs:     1 (11)",
            )
        )

    @pytest.mark.usefixtures("remote_project")
    def test_not_pushed_and_nothing_running(self):
        with fake_run(remote_has_pdp=False, ports=(False,)):
            result = invoke("remote", "status")

        expect(result.exit_code).to(equal(0))
        expect(result.stdout).to(
            contain("not pushed yet", "not running", "not listening", "jobs:     0")
        )

    @pytest.mark.usefixtures("remote_project")
    def test_unreachable_host_exits_1(self):
        with fake_run(reachable=False) as run:
            result = invoke("remote", "status")

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("Cannot reach me@login1"))
        expect(remote_cmds(run)).to(equal(["true"]))


def test_pull_rsync_brings_back_only_output(tmp_path):
    remote, local = tmp_path / "remote", tmp_path / "local"
    for root in (remote, local):
        for d in ("t/src", "t/output", ".git"):
            (root / d).mkdir(parents=True)
    (remote / "t/output/new").write_text("new")
    os.utime(remote / "t/output/new", (1000, 1000))
    (remote / "t/src/run.sh").write_text("remote")
    (remote / ".dagster").mkdir()
    (remote / ".dagster/db").write_text("db")
    (local / "t/src/run.sh").write_text("local edit")
    (local / "t/output/deleted_remotely").write_text("old")
    (local / ".git/HEAD").write_text("head")
    (local / "localonly").mkdir()

    rsync(pull_args(f"{remote}/", local))

    expect((local / "t/output/new").stat().st_mtime).to(equal(1000))
    expect((local / "t/output/deleted_remotely").exists()).to(be_false)
    expect((local / ".dagster").exists()).to(be_false)
    expect((local / "t/src/run.sh").read_text()).to(equal("local edit"))
    expect((local / ".git/HEAD").is_file()).to(be_true)
    expect((local / "localonly").is_dir()).to(be_true)


@pytest.mark.parametrize(
    "running, flags, refuses",
    [
        ({"squeue": "11 pdp-run1-import\n"}, [], True),
        ({"squeue": "11 pdp-run1-import\n"}, ["--force"], False),
        ({"squeue": "12 my-other-job\n"}, [], False),
        ({"run_session": True}, [], True),
        ({"run_session": True}, ["--force"], False),
    ],
    ids=[
        "pdp_job_blocks",
        "force_past_job",
        "other_job_ignored",
        "run_session_blocks",
        "force_past_run",
    ],
)
@pytest.mark.usefixtures("remote_project")
def test_pull_refuses_while_a_run_or_pdp_jobs_are_running(running, flags, refuses):
    with fake_run(**running) as run:
        result = invoke("remote", "pull", *flags)

    expect(result.exit_code).to(equal(1 if refuses else 0))
    pulls = [a[-2:] for a in argvs(run) if a[0] == "rsync"]
    expected = [] if refuses else [["me@login1:/gpfs/proj/", f"{Path.cwd()}/"]]
    expect(pulls).to(equal(expected))


def run_cmd(*args):
    pdp_run = shlex.join(["pdp", "run", "--slurm", *args])
    return (
        "cd /gpfs/proj && mkdir -p .dagster && rm -f .dagster/last-run.json && "
        f"uvx --from '{SPEC}' {pdp_run} > .dagster/last-run.log 2>&1"
    )


REPORT = {"ran": ["a"], "failed": [], "no_entrypoint": [], "exit_code": 0}


@pytest.mark.parametrize(
    "command, running, other",
    [
        ("start", {"run_session": True}, "pdp-test-run"),
        ("run", {"session": True}, "pdp-test"),
    ],
)
@pytest.mark.usefixtures("remote_project")
def test_start_and_run_skip_push_while_the_other_session_runs(command, running, other):
    with fake_run(last_run=REPORT, **running) as run:
        result = invoke("remote", command)

    expect(result.stderr).to(contain(f"Session {other} running, not pushing"))
    expect(pushed_or_pulled(run)).to(be_false)
    expect(remote_cmds(run)).to(contain(contain("new-session")))


@pytest.mark.usefixtures("remote_project")
class TestRemoteRun:
    def test_checks_uvx_pushes_starts_run_then_streams(self):
        with fake_run(last_run=REPORT) as run:
            result = invoke("remote", "run", "--from", "clean")

        expect(result.exit_code).to(equal(0))
        expect(programs(run)).to(
            equal(
                [
                    "tmux",  # run session?
                    "command",  # uvx?
                    "tmux",  # dagster session?
                    "test",  # pushed before?
                    "rsync",
                    "tmux",  # new-session
                    "tail",  # stream
                    "cat",  # last-run.json
                ]
            )
        )
        expect(shlex.split(session_cmd(run))[-1]).to(equal(run_cmd("--from", "clean")))
        stream = next(a for a in argvs(run) if a[-1].startswith("tail "))
        expect(stream).to(contain("-t"))
        expect(stream[-1]).to(
            contain(
                "tail -n +1 -F /gpfs/proj/.dagster/last-run.log",
                "tmux has-session -t =pdp-test-run",
            )
        )
        expect(result.stdout).to(contain("pdp remote pull"))

    def test_no_push(self):
        with fake_run(last_run=REPORT) as run:
            result = invoke("remote", "run", "--no-push")

        expect(result.exit_code).to(equal(0))
        expect(pushed_or_pulled(run)).to(be_false)
        expect(shlex.split(session_cmd(run))[-1]).to(equal(run_cmd()))

    def test_run_in_progress_attaches_and_ignores_args(self):
        with fake_run(run_session=True, last_run=REPORT) as run:
            result = invoke("remote", "run", "clean")

        expect(result.exit_code).to(equal(0))
        expect(result.stderr).to(contain("attaching; args ignored"))
        expect(programs(run)).to(equal(["tmux", "tail", "cat"]))

    def test_exits_with_the_runs_exit_code(self):
        with fake_run(last_run=REPORT | {"failed": ["a"], "exit_code": 1}):
            result = invoke("remote", "run")

        expect(result.exit_code).to(equal(1))
        expect(result.stdout).to(contain("pdp remote pull"))

    def test_missing_report_points_at_the_log(self):
        with fake_run():
            result = invoke("remote", "run")

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(
            contain("Run ended without a report", ".dagster/last-run.log on me@login1")
        )

    def test_dropped_connection_leaves_run_going(self):
        with fake_run(stream_rc=255, last_run=REPORT):
            result = invoke("remote", "run")

        expect(result.exit_code).to(equal(0))
        expect(result.stdout).to(contain("Run continues on me@login1"))

    def test_ctrl_c_leaves_run_going(self):
        with (
            fake_run(last_run=REPORT),
            patch("pdp.remote.stream", side_effect=KeyboardInterrupt),
        ):
            result = invoke("remote", "run")

        expect(result.exit_code).to(equal(0))
        expect(result.stdout).to(contain("Run continues on me@login1"))

    def test_selection_args_are_quoted(self):
        with fake_run(last_run=REPORT) as run:
            invoke("remote", "run", "a b", "it's", "--only")

        expect(shlex.split(session_cmd(run))[-1]).to(
            equal(run_cmd("a b", "it's", "--only"))
        )


FINISHED = REPORT | {
    "ran": ["a", "b", "c"],
    "failed": ["d"],
    "no_entrypoint": ["e"],
    "exit_code": 1,
    "finished": "2026-10-27T14:02:31",
}


@pytest.mark.parametrize(
    "state, run",
    [
        ({"run_session": True}, "running"),
        ({"last_run": FINISHED}, "finished 2026-10-27 14:02, ran 3, failed 2"),
        ({}, "none"),
    ],
    ids=["running", "last_result", "none"],
)
@pytest.mark.usefixtures("remote_project")
def test_status_shows_run(state, run):
    with fake_run(ports=(False,), **state):
        result = invoke("remote", "status")

    expect(result.stdout).to(contain(f"run:      {run}"))
