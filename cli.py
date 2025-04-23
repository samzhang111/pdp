import typer
from pyprojroot import here

app = typer.Typer()

@app.command()
def init():
    """
    Initialize the project.
    """

    # Create the empty configuration object
    pdp_config = {
        'tasks': []
    }

    typer.echo("Initializing the project...")

if __name__ == "__main__":
    app()
