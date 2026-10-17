import hashlib
import os
import sys
from pathlib import Path

import dagster as dg

from .pdp import PDP
from .task import Task, latest_mtime_in_dir


class PdpResource(dg.ConfigurableResource):
    """Hold config for the Dagster run.

    Only has single boolean, but apparently a cheapway to pass to Dagster and can scale
    """

    force: bool = False


def output_data_version(task: Task) -> dg.DataVersion:
    """Pass output snapshot from Task to Dagster as DataVersion"""
    snapshot = sorted(
        (os.path.relpath(path, task.output_folder), stat)
        for path, stat in task._output_snapshot().items()
    )
    return dg.DataVersion(hashlib.sha256(repr(snapshot).encode()).hexdigest())


def build_asset(task: Task, project_root: Path) -> dg.AssetsDefinition:
    """Build a Dagster asset from a single pdp Task

    Use multi_asset for each Task as workaround for naming conventions. 
    Instead of returning `get_materialize_result()`, we create our own
    `dg.MaterializeResult()` so we can add output snapshot.

    Args:
        task: A single pdp Task
        project_root: Root of project, found with `pdp.find_project_root`

    Returns:
        Dagster asset definition with metadata and data version snapshot
    """
    task_id = task.task_id

    # multi asset allows setting name separately from key
    # workaround to avoid 'import', which is not allowed
    @dg.multi_asset(
        name=f"task_{task_id.replace('-', '__')}",
        outs={"out": dg.AssetOut(key=dg.AssetKey(task_id))},
        ins={
            f"dep_{i}": dg.AssetIn(key=dg.AssetKey(dep), dagster_type=dg.Nothing)
            for i, dep in enumerate(task.depends_on)
        },
    )
    def _asset(
        context: dg.AssetExecutionContext,
        pdp: PdpResource,
        pipes: dg.PipesSubprocessClient,
    ) -> dg.MaterializeResult:
        if not task.entrypoint:
            raise dg.Failure("no entrypoint")

        # Either task records an output, or fails and Dagster skips its dependents
        if not (pdp.force or task.is_stale):
            return dg.MaterializeResult(
                metadata={"pdp/ran": False}, data_version=output_data_version(task)
            )

        # Run python -m pdp.pipes_wrapper <task_id> as subprocess through pipes
        pipes.run(
            context=context,
            command=[sys.executable, "-m", "pdp.pipes_wrapper", task_id],
            cwd=str(project_root),
        )

        no_output = latest_mtime_in_dir(task.output_folder) is None
        if no_output:
            context.log.warning(f"{task_id} ran but created nothing in output/ folder")

        return dg.MaterializeResult(
            metadata={"pdp/ran": True, "pdp/no_output": no_output},
            data_version=output_data_version(task),
        )

    return _asset


def build_assets(pdp: PDP) -> list[dg.AssetsDefinition]:
    """Build Dagster assets for all PDP tasks

    Args:
        pdp: PDP object representing project with one or more tasks

    Returns:
        List of Dagster asset definitions
    """
    project_root = pdp.project_root
    return [build_asset(task, project_root) for task in pdp.flatten_tasks().values()]


def build_definitions(project_root: Path) -> dg.Definitions:
    """Pass list of Dagster asset definitions

    Args:
        project_root: Root of project as found by `pdp.find_project_root`

    Returns:
        Dagster definitions
    """
    # shortcut: PDP has no root parameter, pass one through if the defs module
    # ever loads more than one project
    os.chdir(project_root)
    pdp = PDP()
    pdp.initialize()
    pdp._validate_or_raise()

    return dg.Definitions(
        assets=build_assets(pdp),
        resources={"pdp": PdpResource(), "pipes": dg.PipesSubprocessClient()},
    )
