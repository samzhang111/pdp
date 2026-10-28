"""Remote: push the project to a cluster login node, run Dagster there in tmux, pull outputs back."""

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from importlib.metadata import version as pkg_version
from pathlib import Path

SSH_OPTS = [
    "-o",
    "ControlMaster=auto",
    "-o",
    "ControlPath=~/.ssh/pdp-%C",
    "-o",
    "ControlPersist=10m",
]
PUSH_EXCLUDES = [".dagster/", ".git/", ".venv/", ".env"]
OUTPUT_EXCLUDE = "/*/output/"
RUN_LOG = ".dagster/last-run.log"
LAST_RUN = ".dagster/last-run.json"

ENV_EXAMPLE = """\
# .env

# alias defined in ~/.ssh/config, see README
PDP_REMOTE_HOST=vacc-login1 
PDP_REMOTE_PATH=/gpfs1/home/n/e/netid/pdp-project

# optional
PDP_REMOTE_PORT=3000"""


class RemoteError(Exception):
    pass


@dataclass
class Remote:
    host: str
    path: str
    port: str
    spec: str

    @property
    def target(self) -> str:
        return f"{self.host}:{self.path}/"

    def ssh(
        self, cmd: str, check: bool = False, **kwargs
    ) -> subprocess.CompletedProcess:
        return subprocess.run(["ssh", *SSH_OPTS, self.host, cmd], check=check, **kwargs)

    def rsync(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["rsync", "-e", " ".join(["ssh", *SSH_OPTS]), *args], check=True
        )


def parse_env(path: Path) -> dict[str, str]:
    """Read environment and pass values for syncing"""
    if not path.exists():
        return {}

    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")  # split at first = only
            values[key.strip()] = value.strip()

    return values


def remote_version(env: dict[str, str]) -> str:
    # TODO: remove this and use proper version once library is available
    return env.get("PDP_REMOTE_SPEC") or (
        f"pdp[dagster] @ git+https://github.com/ChrisDonovan307/pdp@v{pkg_version('pdp')}"
    )


def load_remote(root: Path) -> Remote:
    env = parse_env(root / ".env") | os.environ
    missing = [
        key for key in ("PDP_REMOTE_HOST", "PDP_REMOTE_PATH") if not env.get(key)
    ]
    if missing:
        raise RemoteError(
            f"Missing {', '.join(missing)}. Set them in {root / '.env'}, e.g.:\n\n{ENV_EXAMPLE}"
        )

    return Remote(
        host=env["PDP_REMOTE_HOST"],
        path=env["PDP_REMOTE_PATH"].rstrip("/"),
        port=env.get("PDP_REMOTE_PORT") or "3000",
        spec=remote_version(env),
    )


def session_name(project_name: str) -> str:
    """Name of tmux session on remote"""
    return f"pdp-{project_name}"


def run_session_name(project_name: str) -> str:
    """Name of tmux session for `pdp remote run`"""
    return f"pdp-{project_name}-run"


def _target(session: str) -> str:
    """tmux target for exactly this session. A bare -t name matches by prefix"""
    return shlex.quote(f"={session}")


def has_session(remote: Remote, session: str) -> bool:
    cmd = f"tmux has-session -t {_target(session)}"
    return remote.ssh(cmd, capture_output=True).returncode == 0


def check_uvx(remote: Remote) -> None:
    """Check if the login node can find uvx."""
    if remote.ssh("command -v uvx", capture_output=True).returncode != 0:
        raise RemoteError(
            f"uvx not found on {remote.host}. "
            "Install uv there with:\n\n"
            "  curl -LsSf https://astral.sh/uv/install.sh | sh\n\n"
            "If uv is installed, make sure its directory is on PATH."
        )


def reachable(remote: Remote) -> bool:
    return remote.ssh("true", capture_output=True).returncode == 0


def exists(remote: Remote) -> bool:
    """Whether project has been pushed to remote"""
    return remote.ssh(f"test -e {remote.path}/pdp.yml").returncode == 0


def push_args(root: Path, dest: str, send_output: bool) -> list[str]:
    excludes = PUSH_EXCLUDES if send_output else [*PUSH_EXCLUDES, OUTPUT_EXCLUDE]
    return ["-a", *(f"--exclude={e}" for e in excludes), f"{root}/", dest]


def sync(remote: Remote, root: Path) -> None:
    """Sync the project to remote.

    Brings symlinks and state of task staleness. Sends contents of
    `output/` only on the first push, because remote project should be
    the source of truth after that and we don't want to overwrite anything."""
    remote.rsync(push_args(root, remote.target, send_output=not exists(remote)))


def push(remote: Remote, root: Path, sessions: list[str]) -> None:
    for session in sessions:
        if has_session(remote, session):
            raise RemoteError(
                f"session {session} running, not pushing; pdp remote stop first"
            )
    sync(remote, root)


def dagster_command(remote: Remote, port: str) -> str:
    return (
        f"cd {remote.path} && uvx --from {shlex.quote(remote.spec)} "
        f"pdp dagster dev --slurm -p {port}"
    )


def run_command(remote: Remote, args: list[str]) -> str:
    """`pdp run --slurm` on the cluster, logging to RUN_LOG"""
    pdp_run = shlex.join(["pdp", "run", "--slurm", *args])
    return (
        f"cd {remote.path} && mkdir -p .dagster && rm -f {LAST_RUN} && "
        f"uvx --from {shlex.quote(remote.spec)} {pdp_run} > {RUN_LOG} 2>&1"
    )


def start_session(remote: Remote, session: str, cmd: str) -> None:
    remote.ssh(
        f"tmux new-session -d -s {shlex.quote(session)} {shlex.quote(cmd)}",
        check=True,
    )


def stream(remote: Remote, session: str) -> subprocess.CompletedProcess:
    """Print the run log until the session ends.

    Ctrl-C ends only the stream, the run keeps going in tmux. The tty (-t)
    hangs up the remote tail and loop when the connection ends."""
    cmd = (
        f"tail -n +1 -F {remote.path}/{RUN_LOG} & "
        f"while tmux has-session -t {_target(session)} 2>/dev/null; do sleep 2; done; "
        # let tail print the last lines
        "sleep 1; kill $!"
    )
    return subprocess.run(["ssh", *SSH_OPTS, "-t", remote.host, cmd], check=False)


def last_run(remote: Remote) -> dict | None:
    """Report of the last `pdp run` under Dagster on the cluster, if any"""
    out = remote.ssh(f"cat {remote.path}/{LAST_RUN}", capture_output=True, text=True)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def port_open(remote: Remote, port: str) -> bool:
    """Whether something listens on the port on the login node"""
    cmd = f"bash -c ': </dev/tcp/127.0.0.1/{port}'"
    return remote.ssh(cmd, capture_output=True).returncode == 0


def wait_for_dagster(remote: Remote, session: str, port: str) -> None:
    """Wait until Dagster is booted and listening.

    Might take longer on first run if installing."""
    while not port_open(remote, port):
        if not has_session(remote, session):
            raise RemoteError(
                f"Dagster exited on startup. To see why, run on {remote.host}:\n\n"
                f"  {dagster_command(remote, port)}"
            )
        time.sleep(2)


def tunnel(remote: Remote, port: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", *SSH_OPTS, "-N", "-L", f"{port}:localhost:{port}", remote.host],
        check=False,
    )


def pdp_job_ids(remote: Remote) -> list[str]:
    """squeue IDs of user's queued or running jobs"""
    out = remote.ssh(
        # --me user jobs only
        # -h no header line
        # output format: 'id jobname'
        "squeue --me -h -o '%i %j'",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    jobs = (line.split(maxsplit=1) for line in out.splitlines() if line.strip())
    return [job_id for job_id, name in jobs if name.startswith("pdp-")]


def stop(remote: Remote, sessions: list[str]) -> tuple[list[str], list[str]]:
    """Kill tmux sessions on remote. Returns the sessions killed and cancelled job ids"""
    killed = [
        session
        for session in sessions
        if remote.ssh(f"tmux kill-session -t {_target(session)}").returncode == 0
    ]
    # scancel --name matches exact names only, so cancel pdp's jobs by id
    job_ids = pdp_job_ids(remote)
    if job_ids:
        remote.ssh(f"scancel {' '.join(job_ids)}", check=True)
    return killed, job_ids


def pull_args(src: str, root: Path) -> list[str]:
    """Copy only outputs from remote back to local machine

    Flags are rsync syntax"""
    return [
        "-a",  # archive mode - keep symlinks
        "--delete",  # remove extraneous files from dest dirs
        "--filter=P /*/",  # protect top level local dirs
        "--exclude=/.*/",  # skip dot files in both directions
        "--include=/*/",  # all files in top level dirs (tasks)
        "--include=/*/output/***",  # all output/ contents, including dirs themselves
        "--exclude=*",  # exclude the rest
        src,
        f"{root}/",
    ]


def pull(remote: Remote, root: Path, run_session: str, force: bool) -> None:
    # Between two tasks of a run there may be no job queued
    if not force and (has_session(remote, run_session) or pdp_job_ids(remote)):
        raise RemoteError(
            "jobs still running, output may be partial; --force to pull anyway"
        )
    remote.rsync(pull_args(remote.target, root))
