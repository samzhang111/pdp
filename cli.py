import typer
from typing_extensions import Annotated
from rich.console import Console
from rich import print as rprint

from pdp.pdp import PDP, PDPConfig

app = typer.Typer()
err_console = Console(stderr=True)
console = Console()


def load_pdp():
    pdp = PDP()

    if not pdp.initialized:
        err_console.print("No project detected. Try `pdp init`.")
        raise typer.Exit(1)

    pdp.initialize()

    #    if not pdp.validate():
    #        err_console.print("Invalid pdp.yml file.")
    #        raise typer.Exit(1)

    return pdp


@app.command()
def init(
    project_name: str = typer.Option(None, "--name", "-n", prompt="Project name")
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
    """

    pdp = load_pdp()

    try:
        for task_name in task_names:
            pdp.create_task_from_current_location(task_name)
    except ValueError:
        err_console.print(
            "Cannot create task from current location. Not at project root or a valid task directory."
        )
        raise typer.Exit(1)


@app.command()
def validate():
    """
    Validate the pdp yml.
    """

    pdp = load_pdp()
    result = pdp.validate()

    if not result:
        err_console.print("Validation failed.")
        raise typer.Exit(1)

    console.print("Valid.")


@app.command()
def run(task_name: Annotated[str, typer.Argument()] = None) -> None:
    """
    Run a task.
    """

    pdp = load_pdp()

    if task_name:
        return_code = pdp.run_task(task_name)
    else:
        current_task = pdp.current_task

        if current_task == ".":
            return_code = pdp.run_all()

        else:
            return_code = pdp.run_task(current_task.task_name)

    raise typer.Exit(return_code)


@app.command()
def tree() -> None:
    """
    Print the task tree.
    """

    pdp = load_pdp()
    tree = pdp.task_tree()
    rprint(tree)

    raise typer.Exit(0)


if __name__ == "__main__":
    app()
