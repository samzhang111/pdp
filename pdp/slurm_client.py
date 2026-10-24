import os
import signal
import subprocess
from pathlib import Path

import dagster as dg
from dagster._core.errors import DagsterPipesExecutionError
from dagster_pipes import PipesExtras

TERMINATION_TIMEOUT_SECONDS = 20


class PdpSlurmClient(dg.PipesClient):
    """Run a task as a Slurm job with srun

    Pipes context and messages go to $DAGSTER_HOME, in shared file system
    """

    def run(
        self,
        *,
        context: dg.AssetExecutionContext,
        command: list[str],
        cwd: str,
        slurm_flags: list[str],
        extras: PipesExtras | None = None,
    ) -> dg.PipesClientCompletedInvocation:  # ty: ignore[invalid-method-override]
        task_id = context.asset_key.to_user_string()
        run_id = context.run.run_id
        name = f"pdp-{run_id}-{task_id}"
        pipes_dir = Path(os.environ["DAGSTER_HOME"]) / "pipes" / run_id / task_id
        pipes_dir.mkdir(parents=True, exist_ok=True)

        with dg.open_pipes_session(
            context=context,
            context_injector=dg.PipesFileContextInjector(
                str(pipes_dir / "context.json")
            ),
            message_reader=dg.PipesFileMessageReader(str(pipes_dir / "messages.jsonl")),
            extras=extras,
        ) as session:
            process = subprocess.Popen(
                [
                    "srun",
                    "--export=ALL",
                    "--quit-on-interrupt",
                    f"--job-name={name}",
                    *slurm_flags,
                    *command,
                ],
                cwd=cwd,
                env=os.environ | session.get_bootstrap_env_vars(),
            )
            try:
                process.wait()
                if process.returncode != 0:
                    raise DagsterPipesExecutionError(
                        f"srun failed with code {process.returncode}"
                    )
            except dg.DagsterExecutionInterruptedError:
                context.log.info("[pipes] execution interrupted, cancelling Slurm job.")
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=TERMINATION_TIMEOUT_SECONDS)
                finally:
                    # srun may never have seen the SIGINT, e.g. still queued
                    subprocess.run(["scancel", f"--name={name}"], check=False)
                raise

        return dg.PipesClientCompletedInvocation(session)
