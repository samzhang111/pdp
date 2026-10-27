import importlib.util
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from graphlib import TopologicalSorter
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Annotated

import typer
from rich import print as rprint
from rich.console import Console

from pdp import remote
from pdp.pdp import PDP, RunReport
from pdp.pdp_errors import InvalidConfigError

app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

dagster_app = typer.Typer(no_args_is_help=True, help="Run PDP with Dagster.")
app.add_typer(dagster_app, name="dagster")
app.add_typer(dagster_app, name="dg", hidden=True)  # dg commands also work

remote_app = typer.Typer(
    no_args_is_help=True, help="Run the project on a Slurm cluster over SSH."
)
app.add_typer(remote_app, name="remote")
app.add_typer(remote_app, name="r", hidden=True)

err_console = Console(stderr=True)
console = Console()


def _print_version():
    rprint(pkg_version("pdp"))


def _version_callback(value: bool):
    if value:
        _print_version()
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True)
    ] = False,
) -> None:
    pass


def _exit_validation_failed(error: InvalidConfigError):
    err_console.print("Validation failed.")
    for line in str(error).split("\n"):
        err_console.print(f"  {line}")
    raise typer.Exit(1)


def load_pdp():
    pdp = PDP()

    if not pdp.initialized:
        err_console.print("No project detected. Try `pdp init`.")
        raise typer.Exit(1)

    try:
        pdp.initialize()
    except InvalidConfigError as e:
        _exit_validation_failed(e)

    return pdp


@app.command()
def init(
    project_name: str = typer.Option(None, "--name", "-n", prompt="Project name"),
) -> None:
    """
    Initialize the project.

    Sets a project name, then creates tasks for every task listed in pdp.yml, if it exists.
    """

    pdp = PDP(project_name)
    pdp.initialize()


@app.command()
@app.command("s", hidden=True)
def scaffold():
    """
    Scaffold the project.

    For each task, create input and output folders if they don't already exist.
    """

    pdp = load_pdp()
    pdp.scaffold()


@app.command()
@app.command("c", hidden=True)
def create(task_names: list[str]) -> None:
    """
    Create a task.

    Task names may contain uppercase or lowercase letters, numbers, and single underscores
    or dashes.
    """

    pdp = load_pdp()

    try:
        for task_name in task_names:
            pdp.create_task_from_current_location(task_name)
    except ValueError as e:
        err_console.print(f"Cannot create task: {e}")
        raise typer.Exit(1)


@app.command()
@app.command("v", hidden=True)
def validate():
    """Validate the pdp yml.

    Checks that:
    - Each task has an input/, output/, and src/ folder
    - Each task has a valid `task.yml`
    - Any `depends_on` references a valid task
    - There are no dependency cyles in the project
    """

    pdp = load_pdp()
    errors = pdp.validation_errors()

    if errors:
        err_console.print("Validation failed.")
        for error in errors:
            err_console.print(f"  {error}")
        raise typer.Exit(1)

    console.print("Valid.")


@app.command()
@app.command("r", hidden=True)
def run(
    task_ids: Annotated[list[str] | None, typer.Argument()] = None,
    only: Annotated[
        bool,
        typer.Option("--only", help="Run the given task(s) without their upstream(s)."),
    ] = False,
    from_: Annotated[
        str | None,
        typer.Option("--from", help="Run this task and everything downstream of it."),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="Run this task and everything upstream of it."),
    ] = None,
    allow_stale: Annotated[
        bool,
        typer.Option(
            "--allow-stale", help="Run even if a task outside the selection is stale."
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Run tasks even if they are not stale."),
    ] = False,
) -> None:
    """Run tasks and their upstreams by id, or run all tasks if no id given.

    If run from inside a task directory and without ids, runs that task and its upstream."""

    pdp = load_pdp()

    try:
        if not (task_ids or from_ or to) and pdp.current_path != Path("."):
            current_task = pdp.current_task

            if current_task is None:
                err_console.print(f"No task at {pdp.current_path}.")
                raise typer.Exit(1)

            task_ids = [current_task.task_id]

        selection = pdp.select(task_ids or [], only, from_, to)

        stale = [] if allow_stale else pdp.stale_upstream(selection)
        if stale:
            err_console.print(
                f"Stale upstream outside the selection: {', '.join(stale)}\n"
                f"Run with --from {stale[0]} to include it, "
                "or --allow-stale to run anyway."
            )
            raise typer.Exit(1)

        report: RunReport = pdp.run_selection(selection, force)
    except InvalidConfigError as e:
        _exit_validation_failed(e)
    except ValueError as e:
        # Bad task id or flags
        err_console.print(str(e))
        raise typer.Exit(1)

    if report.ran:
        console.print(f"Ran: {', '.join(report.ran)}")
    if report.current:
        console.print(f"Current: {', '.join(report.current)}")
    if report.no_output:
        err_console.print(
            f"Ran but wrote nothing to output/: {', '.join(report.no_output)}"
        )
    if report.failed:
        err_console.print(f"Failed: {', '.join(report.failed)}")
    if report.no_entrypoint:
        err_console.print(f"No entrypoint (failed): {', '.join(report.no_entrypoint)}")
    if report.skipped:
        err_console.print(f"Skipped (upstream failed): {', '.join(report.skipped)}")

    raise typer.Exit(report.exit_code)


@app.command()
@app.command("t", hidden=True)
def tree() -> None:
    """Print the task tree as flat list with dependencies."""

    pdp = load_pdp()
    tree = pdp.task_tree()
    rprint(tree)

    raise typer.Exit(0)


@app.command()
@app.command("s", hidden=True)
def status(
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose", "-v", help="Show description, entrypoint, and slurm flags"
        ),
    ] = False,
) -> None:
    """Print status for each task

    Verbose output includes description, entrypoint, and slurm flags"""

    pdp = load_pdp()
    flattened = pdp.flatten_tasks()
    graph = {tid: task.depends_on for tid, task in flattened.items()}

    console.print()
    for i, tid in enumerate(TopologicalSorter(graph).static_order()):
        if verbose and i:
            console.print()
        task = flattened[tid]
        status = "[red]Stale[/]" if task.is_stale else "[blue]Fresh[/]"
        if verbose:
            console.print(f"[green]{tid}[/]")
            console.print(f"  status: {status}")
        else:
            console.print(f"{tid}: {status}")
        if verbose:
            if task.description:
                console.print(f"  description: {task.description}", markup=False)
            console.print(f"  depends on: {', '.join(task.depends_on) or '-'}")
            console.print(
                f"  entrypoint: {task.entrypoint or '(none)'}",
                markup=False,
                highlight=False,
            )
            if task.task_config.slurm:
                flags = ", ".join(
                    f"{key}={value}" for key, value in task.task_config.slurm.items()
                )
                console.print(f"  slurm: {flags}", markup=False)
    console.print()

    raise typer.Exit(0)


@dagster_app.command("dev")
def dev(
    slurm: Annotated[
        bool, typer.Option("--slurm", help="Run each task as a Slurm job via srun.")
    ] = False,
    port: Annotated[
        int | None, typer.Option("--port", "-p", help="Port for the Dagster UI.")
    ] = None,
) -> None:
    """Launch the Dagster UI

    PDP tasks are automatically converted to Dagster assets along with the DAG. You can find the UI at: [link=http://127.0.0.1:3000]http://127.0.0.1:3000[/link]

    This is an optional feature. Make sure you have pdp\\[dagster] installed to use it.
    """

    pdp = load_pdp()
    root = pdp.project_root

    if importlib.util.find_spec("dagster") is None:
        err_console.print("Dagster must be installed: `pdp\\[dagster]`.")
        raise typer.Exit(1)

    env = os.environ | {"PDP_PROJECT_ROOT": str(root)}
    if "DAGSTER_HOME" not in env:
        env["DAGSTER_HOME"] = str(root / ".dagster")
        Path(env["DAGSTER_HOME"]).mkdir(exist_ok=True)

    if slurm:
        if shutil.which("srun") is None:
            err_console.print(
                "--slurm needs Slurm's srun on PATH. Run this on a cluster login node"
            )
            raise typer.Exit(1)
        env["PDP_SLURM"] = "1"

    cmd = [sys.executable, "-m", "dagster", "dev", "-m", "pdp.dagster_defs"]
    if port:
        cmd += ["-p", str(port)]

    # Popen over run to avoid orphan daemon
    proc = subprocess.Popen(cmd, cwd=root, env=env)

    try:
        returncode = proc.wait()
    except KeyboardInterrupt:
        # let dagster shut itself down
        returncode = proc.wait()

    raise typer.Exit(returncode)


@contextmanager
def _remote_errors():
    try:
        yield
    except remote.RemoteError as e:
        err_console.print(str(e), markup=False, soft_wrap=True)
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        raise typer.Exit(e.returncode)


def _load_remote() -> tuple[remote.Remote, Path, str]:
    pdp = load_pdp()
    with _remote_errors():
        cluster = remote.load_remote(pdp.project_root)
    return cluster, pdp.project_root, remote.session_name(pdp.project_name)


@remote_app.command("start")
def remote_start(
    port: Annotated[
        int | None, typer.Option("--port", "-p", help="Port for the Dagster UI.")
    ] = None,
) -> None:
    """Push to the cluster in .env, run Dagster there with --slurm in tmux, and tunnel the UI. Reconnects if the session is already running."""

    cluster, root, session = _load_remote()
    with _remote_errors():
        port_ = str(port or cluster.port)

        if remote.has_session(cluster, session):
            err_console.print(
                f"Session {session} already running, not pushing. "
                "`pdp remote stop` to restart it."
            )
        else:
            remote.check_uvx(cluster)
            if remote.port_open(cluster, port_):
                raise remote.RemoteError(
                    f"Port {port_} is already in use on {cluster.host}. "
                    "Pick another with -p or PDP_REMOTE_PORT."
                )
            remote.sync(cluster, root)
            remote.start_session(cluster, session, port_)
            console.print("Waiting for Dagster...")
            remote.wait_for_dagster(cluster, session, port_)

        console.print(
            f"Dagster UI: http://127.0.0.1:{port_} "
            "(ctrl+c closes the tunnel. Dagster keeps running)"
        )
        try:
            returncode = remote.tunnel(cluster, port_).returncode
        except KeyboardInterrupt:
            returncode = 0

    raise typer.Exit(returncode)


@remote_app.command("push")
def remote_push() -> None:
    """Push the project to the cluster. output/ is sent only on the first push."""

    cluster, root, session = _load_remote()
    with _remote_errors():
        remote.push(cluster, root, session)


@remote_app.command("pull")
def remote_pull(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Pull even while pdp jobs are running."),
    ] = False,
) -> None:
    """Pull every task's output/ back from the cluster."""

    cluster, root, _ = _load_remote()
    with _remote_errors():
        remote.pull(cluster, root, force)


@remote_app.command("status")
@remote_app.command("s", hidden=True)
def remote_status() -> None:
    """Show the remote config, if the project exists on remote, and what is running there."""

    cluster, _, session = _load_remote()
    console.print()
    console.print(f"host:     {cluster.host}", markup=False)
    console.print(f"path:     {cluster.path}", markup=False, highlight=False)
    console.print(f"port:     {cluster.port}", markup=False, highlight=False)
    console.print(
        f"version:  {cluster.spec}", markup=False, soft_wrap=True, highlight=False
    )

    with _remote_errors():
        if not remote.reachable(cluster):
            raise remote.RemoteError(f"Cannot reach {cluster.host} over SSH.")

        pushed = remote.exists(cluster)
        console.print(f"project:  {'exists' if pushed else 'not pushed yet'}")

        running = remote.has_session(cluster, session)
        console.print(
            f"session:  {session} {'[blue]running[/]' if running else '[red]not running[/]'}"
        )

        if remote.port_open(cluster, cluster.port):
            console.print(
                f"dagster: listening on {cluster.port} (tunnel: pdp remote start)"
            )
        else:
            console.print(f"dagster:  not listening on {cluster.port}", highlight=False)

        try:
            job_ids = remote.pdp_job_ids(cluster)
            jobs = f"{len(job_ids)} ({', '.join(job_ids)})" if job_ids else "0"
        except subprocess.CalledProcessError:
            jobs = "unknown (squeue failed)"
        console.print(f"jobs:     {jobs}", highlight=False)

        console.print()


@remote_app.command("stop")
def remote_stop() -> None:
    """Stop the remote Dagster session and cancel pdp's Slurm jobs."""

    cluster, _, session = _load_remote()
    with _remote_errors():
        killed, job_ids = remote.stop(cluster, session)

    if killed:
        console.print(f"Stopped session {session} on {cluster.host}.", markup=False)
    if job_ids:
        console.print(f"Cancelled Slurm jobs: {', '.join(job_ids)}")
