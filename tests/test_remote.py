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
    session=False, remote_has_pdp=True, squeue="", ports=(False, True), uvx=True
):
    """Patch subprocess.run, answer ssh commands, record every argv"""
    port_answers = list(ports)

    def run(argv, **kwargs):
        cmd = argv[-1]
        rc = 0
        if "has-session" in cmd:
            rc = 0 if session else 1
        elif "/dev/tcp/" in cmd:
            is_open = port_answers.pop(0) if len(port_answers) > 1 else port_answers[0]
            rc = 0 if is_open else 1
        elif cmd.startswith("test -e"):
            rc = 0 if remote_has_pdp else 1
        elif cmd == "command -v uvx":
            rc = 0 if uvx else 1
        stdout = squeue if cmd.startswith("squeue") else ""
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


class TestLoadRemote:
    def test_parses_comments_blanks_and_equals_in_values(self, tmp_path):
        (tmp_path / ".env").write_text(
            "# comment\n\nPDP_REMOTE_HOST=me@login1\nPDP_REMOTE_SPEC=pdp @ git+x?a=b\n"
        )

        expect(parse_env(tmp_path / ".env")).to(
            equal(
                {"PDP_REMOTE_HOST": "me@login1", "PDP_REMOTE_SPEC": "pdp @ git+x?a=b"}
            )
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
    @pytest.mark.usefixtures("remote_project")
    def test_refuses_while_session_runs(self):
        with fake_run(session=True) as run:
            result = invoke("remote", "push")

        expect(result.exit_code).to(equal(1))
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
        programs = [a[0] if a[0] == "rsync" else a[-1].split()[0] for a in argvs(run)]
        expect(programs).to(
            equal(
                [
                    "tmux",
                    "command",
                    "bash",
                    "test",
                    "rsync",
                    "tmux",
                    "bash",
                    "me@login1",
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
        expect(remote_cmds(run)).to(equal(["tmux has-session -t pdp-test"]))
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
        with fake_run(ports=(False, False, False, True)) as run, patch("time.sleep"):
            # the session is alive while Dagster starts
            with patch("pdp.remote.has_session", side_effect=[False, True, True]):
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
    def test_kills_session_then_cancels_only_pdp_jobs(self, squeue, cancel):
        with fake_run(squeue=squeue) as run:
            result = invoke("remote", "stop")

        expect(result.exit_code).to(equal(0))
        expect(remote_cmds(run)).to(
            equal(
                [
                    "tmux kill-session -t pdp-test",
                    "squeue --me -h -o '%i %j'",
                    *cancel,
                ]
            )
        )


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
    "squeue, flags, refuses",
    [
        ("11 pdp-run1-import\n", [], True),
        ("11 pdp-run1-import\n", ["--force"], False),
        ("12 my-other-job\n", [], False),
    ],
    ids=["pdp_job_blocks", "force", "other_job_ignored"],
)
@pytest.mark.usefixtures("remote_project")
def test_pull_refuses_only_while_pdp_jobs_run(squeue, flags, refuses):
    with fake_run(squeue=squeue) as run:
        result = invoke("remote", "pull", *flags)

    expect(result.exit_code).to(equal(1 if refuses else 0))
    pulls = [a[-2:] for a in argvs(run) if a[0] == "rsync"]
    expected = [] if refuses else [["me@login1:/gpfs/proj/", f"{Path.cwd()}/"]]
    expect(pulls).to(equal(expected))
