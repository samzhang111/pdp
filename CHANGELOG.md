# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Releasing

When merging to main:

1. Bump version with `uv version --bump <major|minor|patch|alpha>`. This updates
   `pyproject.toml` and locks.
2. Retitle `## [Unreleased]` to `## [<version>] - YYYY-MM-DD` and start a fresh
   `## [Unreleased]` above it.
3. Commit `pyproject.toml`, `uv.lock` and `CHANGELOG.md` in their own commit and
   merge to main
4. Tag with `git tag -a v<version>-m "Release x.x.x"`, then
   `git push origin main --folow-tags`.

## [Unreleased]

### Added

- `pdp run` accepts several task IDs and selection flags:
  - `--only` runs the given tasks without their upstream.
  - `--from <task>` runs a task and its downstream.
  - `--to <task>` runs a task and its upstream. With `--from`, runs every task
    on a path between the two.
- `pdp run` refuses to run when a selected task depends on a stale task outside
  the selection. `--allow-stale` runs anyway.

## [0.2.2] - 2026-10-26

### Added

- `pdp dagster dev --slurm` runs from the cluster login node and sets each task
  as Slurm job. Can run concurrently when PDP structure allows for it. Configure
  with `slurm` block in `pdp.yml` or `task.yml`. Tasks override project
  configuration.
- `pdp dagster dev -p/--port` sets the UI port.
- Remote commands:
  - `pdp remote start` - connect to cluster, push project, and start dagster dev
  - `pdp remote push` - push project to cluster
  - `pdp remote pull` - pull outputs from cluster to local
  - `pdp remote stop` - kill dagster and tmux session on remote
- Added `pdp status` and `pdp remote status`
- Added command shortcuts: `-h` for `--help`, `s` for `status`

## [0.2.1] - 2026-10-18

### Added

- `pdp dagster dev` starts local Dagster UI. Dagster assets are created from PDP
  tasks.
- Optional dependencies for dagster and dagster-webserver
- When Dagster loads, tasks with outputs that changed outside of Dagster are
  recorded as asset observations so staleness carries through and only necessary
  tasks are run.
- Dependencies show on `pdp tree` output

### Changed

- A task without an entrypoint now fails the run. This may be revisited when
  subtasks are reintroduced.

## [0.2.0] - 2026-10-04

### Added

- Added `task.is_stale()` based on mtimes of task dirs and staleness of task
  dependencies.
- Added `TopologicalSorter()` to `pdp.run_all()` and `pdp.run_task()` to
  determine task order
- Added `task.depends_on()` for task dependencies
- Dependency symlinks whole `task1/output/` directory to `task2/input/` when
  listed under `depends_on()`
- `PDP_INPUT_<DEP>` env vars set for entrypoints as fallback when symlinks fail
  (i.e. Windows)
- Failure handling:
  - On failed task, downstream tasks are skipped
  - On failed task, unrelated tasks still run
  - Snapshot is taken before task run so that on failure, `pdp` removes what it
    wrote in that run, leaving other outputs untouched.
- Runs create `RunReport`, which prints tasks run successfully, tasks failed,
  and tasks current (i.e. did not need to run)
- Added `--force` flag to invalidate outputs and run all tasks regardless of
  staleness

### Changed

- Switched from poetry to uv, build backend is now `uv_build`. Install with
  `uv sync`, run with `uv run`.

### Removed

- Removed hierarchical subtasks temporarily. Will return sometime.
- Dropped the `graphlib` dependency and moved `pytest-cov` out of the runtime
  dependencies into the dev group.
