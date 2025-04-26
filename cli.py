import typer
from typing_extensions import Annotated
from rich.console import Console

from pdp import PDP, PDPConfig

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
def init():
    """
    Initialize the project.
    """

    pdp = PDP()
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

    for task_name in task_names:
        pdp.create_task_from_current_location(task_name)


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


if __name__ == "__main__":
    app()
