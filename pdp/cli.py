import importlib.util
import os
import subprocess
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Annotated

import typer
from rich import print as rprint
from rich.console import Console

from pdp.pdp import PDP, RunReport
from pdp.pdp_errors import InvalidConfigError

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")

dagster_app = typer.Typer(no_args_is_help=True, help="Run pdp with Dagster")
app.add_typer(dagster_app, name="dagster")
app.add_typer(dagster_app, name="dg", hidden=True) # dg commands also work

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
    """

    pdp = PDP(project_name)
    pdp.initialize()


@app.command()
def scaffold():
    """
    Scaffold the project. That is, for each task, create input and output folders if they don't already exist.
    """

    pdp = load_pdp()
    pdp.scaffold()


@app.command()
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
def validate():
    """
    Validate the pdp yml.
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
def run(
    task_id: Annotated[str | None, typer.Argument()] = None,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Run tasks regardless of staleness.")
    ] = False,
) -> None:
    """
    Run a task (by id) or all tasks (if no id given).
    """

    pdp = load_pdp()

    try:
        if task_id:
            report: RunReport = pdp.run_task(task_id, force)
        elif pdp.current_path == Path("."):
            report: RunReport = pdp.run_all(force)
        else:
            current_task = pdp.current_task

            if current_task is None:
                err_console.print(f"No task at {pdp.current_path}.")
                raise typer.Exit(1)

            report: RunReport = pdp.run_task(current_task.task_id, force)
    except InvalidConfigError as e:
        _exit_validation_failed(e)
    except ValueError as e:
        # Bad task id
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
def tree() -> None:
    """
    Print the task tree.
    """

    pdp = load_pdp()
    tree = pdp.task_tree()
    rprint(tree)

    raise typer.Exit(0)


@dagster_app.command("dev")
def dev() -> None:
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

    # Popen over run to avoid orphan daemon
    proc = subprocess.Popen(
        [sys.executable, "-m", "dagster", "dev", "-m", "pdp.dagster_defs"],
        cwd=root,
        env=env,
    )

    try:
        returncode = proc.wait()
    except KeyboardInterrupt:
        # dagster dev got the same Ctrl-C; let it shut down its webserver and daemon
        returncode = proc.wait()

    raise typer.Exit(returncode)
