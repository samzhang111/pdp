import os
import subprocess
import sys
from pathlib import Path

LOCATION_FLAGS = {"-m", "--module-name", "-f", "--python-file", "-w", "--workspace"}


def _with_project_module(args: list[str]) -> list[str]:
    """Insert `-m pdp.dagster_defs` after the dagster subcommand, unless a location is given"""
    if any(arg.split("=")[0] in LOCATION_FLAGS for arg in args):
        return args

    import click
    from dagster._cli import cli

    command, depth = cli, 0
    while isinstance(command, click.Group) and depth < len(args):
        if args[depth] not in command.commands:
            break
        command = command.commands[args[depth]]
        depth += 1

    if not any(param.name == "module_name" for param in command.params):
        return args
    return [*args[:depth], "-m", "pdp.dagster_defs", *args[depth:]]


def _dagster_env(root: Path) -> dict[str, str]:
    """Default environment for Dagster, with telemtry off"""
    env = os.environ | {"PDP_PROJECT_ROOT": str(root)}
    if "DAGSTER_HOME" not in env:
        home = root / ".dagster"
        env["DAGSTER_HOME"] = str(home)
        home.mkdir(exist_ok=True)
        if not (home / "dagster.yaml").exists():
            (home / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    return env


def run_dagster(root: Path, args: list[str]) -> int:
    """Run `dagster <args>` on the project at root and return its exit code"""
    # Popen over run to avoid orphan daemon
    proc = subprocess.Popen(
        [sys.executable, "-m", "dagster", *_with_project_module(args)],
        cwd=root,
        env=_dagster_env(root),
    )

    try:
        return proc.wait()
    except KeyboardInterrupt:
        # shut down own webserver and daemon
        return proc.wait()
