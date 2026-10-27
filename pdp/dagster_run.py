"""Run a selection of tasks through Dagster without the UI"""

import json
import os
import warnings
from collections.abc import Generator
from contextlib import chdir, contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import dagster as dg
from dagster._core.instance.ref import InstanceRef

from .dagster_assets import RUN_JOB, build_definitions, op_name
from .pdp import PDP, RunReport
from .utils import dagster_env

QUIET_LOGS = {"loggers": {"console": {"config": {"log_level": "CRITICAL"}}}}
# Step processes log through the instance's logger, which ignores the run's loggers
QUIET_INSTANCE = {"python_logs": {"python_log_level": "CRITICAL"}}


@contextmanager
def _environ(env: dict[str, str]) -> Generator[None]:
    """Set env for the run, which step processes inherit, then restore it"""
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def asset_job(project_root: str, slurm: bool) -> dg.JobDefinition:
    """Job over every task asset, rebuilt by Dagster in each step process"""
    warnings.filterwarnings("ignore", category=dg.PreviewWarning)
    defs = build_definitions(Path(project_root), slurm=slurm)
    return defs.resolve_job_def(RUN_JOB)


def _report(pdp: PDP, selection: set[str], result: dg.JobExecutionResult) -> RunReport:
    """Sort each selected task into a RunReport category from the run's events"""
    flattened = pdp.flatten_tasks()
    materialized = {
        event.materialization.asset_key.to_user_string(): event.materialization.metadata
        for event in result.get_asset_materialization_events()
    }
    failed_steps = {event.step_key for event in result.get_step_failure_events()}

    report = RunReport()
    for tid in pdp._order(flattened):
        if tid not in selection:
            continue
        if tid in materialized:
            metadata = materialized[tid]
            if not metadata["pdp/ran"].value:
                report.current.append(tid)
                continue
            report.ran.append(tid)
            if metadata["pdp/no_output"].value:
                report.no_output.append(tid)
        elif op_name(tid) in failed_steps:
            if flattened[tid].entrypoint:
                report.failed.append(tid)
            else:
                report.no_entrypoint.append(tid)
        else:
            # Never started: an upstream failed
            report.skipped.append(tid)

    return report


def run_dagster(
    pdp: PDP,
    selection: set[str],
    force: bool = False,
    slurm: bool = False,
    verbose: bool = False,
) -> RunReport:
    """Materialize the selected tasks in the project's Dagster instance.

    Uses the same DAGSTER_HOME as `pdp dagster dev`, so runs show in the UI.
    Writes the report to $DAGSTER_HOME/last-run.json.

    Raises:
        SlurmUnavailableError: slurm is set and srun is not on PATH
        KeyboardInterrupt: on Ctrl-C, after Dagster has interrupted its steps
    """
    root = pdp.project_root
    run_config: dict = {"resources": {"pdp": {"config": {"force": force}}}}
    if not verbose:
        run_config |= QUIET_LOGS

    # Loading the definitions changes directory to the root, so restore it after
    with chdir(root), _environ(dagster_env(root, slurm)):
        job = dg.build_reconstructable_job(
            "pdp.dagster_run",
            "asset_job",
            reconstructable_kwargs={"project_root": str(root), "slurm": slurm},
        )
        instance_ref = InstanceRef.from_dir(
            os.environ["DAGSTER_HOME"], overrides=None if verbose else QUIET_INSTANCE
        )
        with dg.DagsterInstance.from_ref(instance_ref) as instance:
            try:
                # Without raise_on_error, Dagster swallows an interrupt.
                # Step failures never raise here
                result = dg.execute_job(
                    job,
                    instance,
                    run_config=run_config,
                    asset_selection=[dg.AssetKey(tid) for tid in selection],
                    raise_on_error=True,
                )
            except dg.DagsterExecutionInterruptedError:
                # Steps were interrupted and the Slurm client cancelled its jobs
                raise KeyboardInterrupt from None
            report = _report(pdp, selection, result)

        last_run = Path(os.environ["DAGSTER_HOME"]) / "last-run.json"
        last_run.write_text(
            json.dumps(
                asdict(report)
                | {
                    "exit_code": report.exit_code,
                    "finished": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            )
        )

    return report
