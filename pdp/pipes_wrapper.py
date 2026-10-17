import sys

from dagster_pipes import open_dagster_pipes

from .pdp import PDP


def main(task_id: str) -> int:
    """Run single task with Dagster Pipes

    open_dagster_pipes to send logs and metadata back to Dagster
    """
    with open_dagster_pipes() as pipes:
        pdp = PDP()
        pdp.initialize()
        flattened = pdp.flatten_tasks()
        task = flattened[task_id]
        task.create_symlinks(set(flattened))
        returncode = task.run()
        pipes.log.info(f"{task_id} returncode: {returncode}")
        return returncode


if __name__ == "__main__":
    # run with task_id (argv[1])
    sys.exit(main(sys.argv[1]))
