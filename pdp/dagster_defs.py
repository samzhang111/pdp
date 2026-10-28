"""Entrypoint for Dagster"""

import os
from pathlib import Path

import dagster as dg

from .dagster_assets import build_definitions, load_project, reconcile
from .utils import slurm_enabled

if not os.environ.get("PDP_PROJECT_ROOT"):
    raise RuntimeError(
        "'PDP_PROJECT_ROOT' is not set. To run with Dagster, use `pdp dagster dev`."
    )

project_root = Path(os.environ["PDP_PROJECT_ROOT"])
defs = build_definitions(project_root, slurm=slurm_enabled(os.environ))

# Reconcile events on definition load
with dg.DagsterInstance.get() as instance:
    reconcile(load_project(project_root), instance)
