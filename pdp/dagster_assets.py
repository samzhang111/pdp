import hashlib
import os
import sys
from pathlib import Path

import dagster as dg

from .pdp import PDP
from .slurm_client import PdpSlurmClient
from .task import Task, latest_mtime_in_dir

DATA_VERSION_TAG = "dagster/data_version"
RUN_JOB = "pdp_run"


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


def op_name(task_id: str) -> str:
    """Dagster op and step name for a task. Dagster rejects keywords like 'import'"""
    return f"task_{task_id.replace('-', '__')}"


def build_asset(
    task: Task, project_root: Path, slurm_defaults: dict
) -> dg.AssetsDefinition:
    """Build a Dagster asset from a single pdp Task

    Use multi_asset for each Task as workaround for naming conventions.
    Instead of returning `get_materialize_result()`, we create our own
    `dg.MaterializeResult()` so we can add output snapshot.

    Args:
        task: A single pdp Task
        project_root: Root of project, found with `pdp.find_project_root`
        slurm_defaults: `slurm:` mapping from pdp.yml, used only under Slurm

    Returns:
        Dagster asset definition with metadata and data version snapshot
    """
    task_id = task.task_id

    # multi asset allows setting name separately from key
    # workaround to avoid 'import', which is not allowed
    @dg.multi_asset(
        name=op_name(task_id),
        outs={"out": dg.AssetOut(key=dg.AssetKey(task_id))},
        ins={
            f"dep_{i}": dg.AssetIn(key=dg.AssetKey(dep), dagster_type=dg.Nothing)
            for i, dep in enumerate(task.depends_on)
        },
    )
    def _asset(
        context: dg.AssetExecutionContext,
        pdp: PdpResource,
        pipes: dg.ResourceParam[dg.PipesClient],
    ) -> dg.MaterializeResult:
        if not task.entrypoint:
            raise dg.Failure("no entrypoint")

        # Either task records an output, or fails and Dagster skips its dependents
        if not (pdp.force or task.is_stale):
            return dg.MaterializeResult(
                metadata={"pdp/ran": False}, data_version=output_data_version(task)
            )

        # Run python -m pdp.pipes_wrapper <task_id> as subprocess through pipes
        command = [sys.executable, "-m", "pdp.pipes_wrapper", task_id]
        cwd = str(project_root)
        before = task._output_snapshot()
        if isinstance(pipes, PdpSlurmClient):
            pipes.run(
                context=context,
                command=command,
                cwd=cwd,
                slurm_flags=task.slurm_flags(slurm_defaults),
            )
        else:
            pipes.run(context=context, command=command, cwd=cwd)

        no_output = latest_mtime_in_dir(task.output_folder) is None
        if no_output:
            context.log.warning(f"{task_id} ran but created nothing in output/ folder")

        return dg.MaterializeResult(
            metadata={
                "pdp/ran": True,
                "pdp/no_output": no_output,
                "pdp/written": dg.MetadataValue.json(task.written_since(before)),
            },
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
    slurm_defaults = pdp.config.slurm
    return [
        build_asset(task, project_root, slurm_defaults)
        for task in pdp.flatten_tasks().values()
    ]


def load_project(project_root: Path) -> PDP:
    """Load and validate the pdp project at project_root

    Args:
        project_root: Root of project as found by `pdp.find_project_root`

    Returns:
        Initialized PDP object
    """
    os.chdir(project_root)
    pdp = PDP()
    pdp.initialize()
    pdp._validate_or_raise()

    return pdp


def reconcile(pdp: PDP, instance: dg.DagsterInstance) -> None:
    """Record dg observations for current tasks whose output changed outside
    of Dagster process.

    Runs every time definitions are loaded. Tasks which are stale or
    entrypoints are skipped.

    Args:
        pdp: Valid PDP object with one or more tasks
        instance: Dagster instance
    """
    for task_id, task in pdp.flatten_tasks().items():
        if not task.entrypoint or task.is_stale:
            continue

        key = dg.AssetKey(task_id)
        data_version = output_data_version(task).value

        # Find most recent event Dagster recorded for asset
        latest = max(
            [
                *instance.fetch_observations(key, limit=1).records,
                *instance.fetch_materializations(key, limit=1).records,
            ],
            key=lambda record: record.storage_id,
            default=None,
        )
        event = latest and (latest.asset_observation or latest.asset_materialization)

        # If the data version tag of event matches what Dagster has, it already knows about it
        if event and (event.tags or {}).get(DATA_VERSION_TAG) == data_version:
            continue

        # Otherwise, new observation with current version
        instance.report_runless_asset_event(
            dg.AssetObservation(key, tags={DATA_VERSION_TAG: data_version})
        )


def build_definitions(project_root: Path, slurm: bool = False) -> dg.Definitions:
    """Pass list of Dagster asset definitions

    Args:
        project_root: Root of project as found by `pdp.find_project_root`
        slurm: If true, submit each task to Slurm with `srun` instead of local subprocess

    Returns:
        Dagster definitions
    """
    assets = build_assets(load_project(project_root))
    # Named job for `pdp run`: the implicit asset job can't be reconstructed by name
    jobs = [dg.define_asset_job(RUN_JOB)]
    if not slurm:
        return dg.Definitions(
            assets=assets,
            jobs=jobs,
            resources={"pdp": PdpResource(), "pipes": dg.PipesSubprocessClient()},
        )

    # Configured executor overrides default dg settings
    # Set max concurrency specifically for weird login node behavior
    max_concurrent = int(os.environ.get("PDP_MAX_CONCURRENT", "8"))
    return dg.Definitions(
        assets=assets,
        jobs=jobs,
        resources={"pdp": PdpResource(), "pipes": PdpSlurmClient()},
        executor=dg.multiprocess_executor.configured(
            {"max_concurrent": max_concurrent}
        ),
    )
