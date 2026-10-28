import os
import re
import shutil
from pathlib import Path

from .pdp_errors import SlurmUnavailableError

TASK_NAME_RULE = "letters and digits, separated by single underscores or dashes"
_TASK_NAME = re.compile(r"[A-Za-z0-9]+([_-][A-Za-z0-9]+)*")


def is_valid_task_name(task_name) -> bool:
    """Only allow upper/lower case letters and digits separated by single underscores
    or single dashes. This lets us get a clean input_env_var and reserves double
    under score `__` for eventual nested subtasks."""
    return isinstance(task_name, str) and _TASK_NAME.fullmatch(task_name) is not None


def input_env_var(task_id: str) -> str:
    """Turn task_id into uppercase var with only `_` for shell"""
    return f"PDP_INPUT_{task_id.upper().replace('-', '_')}"


def find_project_root(config_name: str, start: Path | None = None) -> Path:
    """Walk up directories until you find config file. Starts by current cwd()
    by default, but can be given a path to accommodate using it Task.task_id

    Args:
        config_name (str): Name of config file
        start (Path | None, optional): Path to start walking from. Defaults to None.

    Returns:
        Path: Absolute path to project root
    """
    current_path = (start or Path.cwd()).resolve()
    while current_path != current_path.parent:
        if (current_path / config_name).exists():
            return current_path
        current_path = current_path.parent

    if (current_path / config_name).exists():
        return current_path

    return (start or Path.cwd()).resolve()


def slurm_enabled(env) -> bool:
    """PDP_SLURM is on unless unset, empty, 0 or false"""
    return env.get("PDP_SLURM", "").strip().lower() not in ("", "0", "false")


def dagster_env(project_root: Path, slurm: bool) -> dict[str, str]:
    """Environment variables `pdp.dagster_defs` and the Slurm client need.

    DAGSTER_HOME defaults to <root>/.dagster, created if missing with a
    dagster.yaml that turns off Dagster's telemetry. A DAGSTER_HOME that is
    already set is left alone.

    Raises:
        SlurmUnavailableError: slurm is set and srun is not on PATH
    """
    env = {"PDP_PROJECT_ROOT": str(project_root)}
    if "DAGSTER_HOME" not in os.environ:
        home = project_root / ".dagster"
        home.mkdir(exist_ok=True)
        config = home / "dagster.yaml"
        if not config.exists():
            config.write_text("telemetry:\n  enabled: false\n")
        env["DAGSTER_HOME"] = str(home)

    if slurm:
        if shutil.which("srun") is None:
            raise SlurmUnavailableError(
                "--slurm needs Slurm's srun on PATH. Run this on a cluster login node"
            )
        env["PDP_SLURM"] = "1"

    return env
