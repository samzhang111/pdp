import typer
from rich.console import Console

from pdp import PDP, PDPConfig

app = typer.Typer()
err_console = Console(stderr=True)
console = Console()


def load_pdp():
    config = PDPConfig()
    pdp = PDP(config)

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

    config = PDPConfig()
    pdp = PDP(config)
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
        pdp.create_task(task_name)


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


if __name__ == "__main__":
    app()
