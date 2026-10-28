<h1 align="center">
  pdp: Principled Data Processing
</h1>

<p align="center">
  <b>A command-line tool for reproducible data analysis workflows.</b>
</p>

Principled Data Processing is a reproducible and readable way to organize data
analyses. `pdp` is a command-line tool that makes using Principled Data
Processing very simple. This tool is designed both to be opinionated (see
[Principles](#principles) below), as well as easy to bolt onto existing PDP
projects (see [Usage](#usage)).

##### Table of contents

- [Principles](#principles)
- [Install](#install)
- [Usage](#usage)
- [Development](#Development)
- [Contributing](#contributing)
- [About PDP](#about)

## Principles

1. Projects are separated into _tasks_, which are folders in the filesystem. A
   task is either a collection of subtasks, which are themselves subdirectories
   in the task, or an _atomic_ task which contains no further subtasks.
   **NOTE:** subtask functionality is delayed - project only currently works
   with single level tasks.

2. Atomic tasks contain folders for `input` (input data for the task), `src`
   (source code), and `output` (where the task writes its outputs). Importantly,
   tasks only write to their output folders, and never read from their own
   outputs.

3. Tasks have an entrypoint that allows them to be run with a single command.
   Usually this is `make`.

## Install

Soon to be available on PyPI. Meanwhile, you can install with
[uv](https://docs.astral.sh/uv/):

```sh
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install pdp
uv tool install "pdp[dagster] @ git+https://github.com/scienceandhumanitylab/pdp"

# Alternatively, install just the core PDP features
# No Dagster or Slurm - local use only
uv tool install "pdp @ git+https://github.com/scienceandhumanitylab/pdp"

# Upgrade pdp
uv tool upgrade pdp
```

**Requirements:**

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

Optional

- dagster>=1.13,<1.14
- dagster-webserver>=1.13,<1.14

## Usage

### Editing an existing pdp project

- Run `pdp init` from the root of a project. It creates a file called `pdp.yml`,
  which contains metadata about the project, and marks the project root.
- Edit the `tasks` key in the `pdp.yml` file to list all the tasks in order.
- Run `pdp init` again, to initialize the `task.yml` files within each of those
  tasks.
- Edit each `task.yml` to designate the entrypoint, which would be `make` for
  most PDP projects.
- Run `pdp run` from within a task to run that task. If in the project root,
  this runs all tasks.

### Starting a new project from scratch

- Run `pdp init` from the root of a project. It creates a file called `pdp.yml`,
  which contains metadata about the project, and marks the project root.
- Run `pdp create <name_of_task1> <name_of_task2> ... <name_of_taskN>` to create
  tasks. This creates directories for each task, a `task.yml` configuration
  file, as well as the `src`, `input`, and `output` folders within that task.
  Task names may contain upper or lower cases letters, digits, and can be
  separated by one or more single underscores (`_`) or dashes (`-`).
- Edit each `task.yml` to designate a specific command to run as an entrypoint,
  such as `make`.

### Run locally

- Use `pdp run` from within a task to run that task. If in the project root,
  this runs all tasks.
- Only stale tasks run. Add `--force` to rerun selected tasks even when they are
  current.
- Use `pdp run <task>` to run a specific task.

Select which tasks to run (`import -> clean -> analyze`):

| Command                              | Action                                          |
| ------------------------------------ | ----------------------------------------------- |
| `pdp run`                            | All tasks                                       |
| `pdp run clean`                      | `clean` and its upstream (`import`)             |
| `pdp run clean --only`               | `clean` alone                                   |
| `pdp run --from clean`               | `clean` and its downstream (`analyze`)          |
| `pdp run --from import --to analyze` | Every task on a path from `import` to `analyze` |
| `pdp run --to clean`                 | Same as `pdp run clean`                         |

Several IDs run the union of their selections, so `pdp run import other --only`
runs both alone. If a selected task depends on a stale task outside the
selection, `pdp run` refuses and suggests `--from <task>`. Add `--allow-stale`
to run anyway.

### Run with Dagster

- Run `pdp dagster dev` to start Dagster UI. Then you can materialize assets.
- Tasks from PDP are generated as Dagster assets.
- Run `pdp run --runner dagster` to run a through Dagster without the UI, or set
  `runner: dagster` in `pdp.yml` to make it the default. Add `-v` to see
  Dagster's logs.

### Run with Dagster on Slurm

- The VACC has `uv` and `tmux` installed by default. Both are required to be
  able to run PDP on Slurm.
- Put slurm flags in an optional `slurm:` block in the `pdp.yml`. You can also
  set `task.yml` with settings that override the `pdp.yml` for that task.
- Datasets on the VACC can be symlinked in your local project
  (`ln -s /path/from/vacc task/input/data.csv`). Symlinks will sync with pdp to
  be able to access datasets on the cluster at runtime.
- Run `pdp dagster dev --slurm` to run the project with each task as a Slurm
  job.
- Run `pdp run --slurm` to run the project the same but without the UI.
  `--slurm` implies `--runner dagster`.

```yaml
# pdp.yml
slurm:
  partition: general
  time: "01:00:00"

# clean/task.yml
slurm:
  mem: 16G
  exclusive: true
```

Jobs inherit the login node's environment (`--export=ALL`).

#### From Local Machine

Launch your project from your local machine and have PDP sync and run it from
the cluster with Dagster-Slurm.

First, put the cluster info in `.env` in your project root, and add `.env` to
`.gitignore`:

```sh
PDP_REMOTE_HOST=<mynetid>@login1.vacc.uvm.edu
PDP_REMOTE_PATH=/gpfs1/home/n/e/netid/my-project
PDP_REMOTE_PORT=3002 # optional
```

Note that we need to specify a login node so that we can keep communicating with
the Dagster session.

To run the project:

- `pdp remote start` pushes the project to VACC, opens a persistent tmux
  session, runs `pdp dagster dev --slurm` and forwards the UI for Dagster. Set
  the port with `-p` or `PDP_REMOTE_PORT`.
  - Visit the localhost URL to materialize assets with Dagster.
  - Closing your terminal only closes the tunnel. The tmux session will persist
    on the cluster and will keep managing jobs.
  - Run `pdp remote start` again to reconnect to the session.
- `pdp remote run` runs `pdp run --slurm` on the cluster, without the UI, in a
  tmux session called `pdp-<project-name>-run`, and streams its log. It takes
  the same selection flags as `pdp run`.
  - It pushes first, unless the `remote start` session is running or you pass
    `--no-push`.
  - Ctrl-C or a lost connection ends the stream, but the run continues in tmux.
    Run `pdp remote run` again to reattach.
  - Use `pdp remote pull` to fetch the output.
- `pdp remote status` shows whether a run is in progress, or the last run's
  result.
- `pdp remote push` syncs the project to the cluster, unless a session is
  running.
- `pdp remote pull` pulls each task's `output/` from the cluster back to your
  local machine.
- `pdp remote stop` ends both tmux sessions and cancels remaining Slurm jobs.

#### From the Cluster

Clone your repository into a the cluster. Then, on a login node:

```sh
tmux new -s pdp
pdp dagster dev --slurm -p 3000   # 3000 is default
```

Forward the port from your local machine with
`ssh -N -L 3000:localhost:3000 <node>` and open localhost:3000 to materialize
assets in the UI. Alternatively, use any of the `pdp run` commands followed by
`--slurm`. For example, `pdp run task1 --slurm`.

### Additional commands

- Run `pdp tree` to see the tree structure of all tasks.
- Run `pdp validate` to validate the project configuration.
- Run `pdp clean` to delete each task's `clean:` files from `task.yml`, like
  `clean: [output/*]`.

## Development

Install `uv`, clone repository and sync dependencies:

```sh
# Install uv if necessary
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repo and install editable
git clone https://github.com/scienceandhumanitylab/pdp
cd pdp
uv sync
uv tool install --force --editable ".[dagster]"
```

## Contributing

Install an editable version of the tool for development:

```sh
uv tool install --force --editable ".[dagster]"
```

If working with branches that are ahead of the latest release tag, add a pinned
version to the `.env`:

```sh
PDP_REMOTE_SPEC="pdp[dagster] @ git+https://github.com/scienceandhumanitylab/pdp@<sha>"
```

Guidelines

- Run tests with `uv run pytest`.
- Code should be formatted and linted with
  [Ruff](https://github.com/astral-sh/ruff).
- Use
  [Google style docstrings](https://google.github.io/styleguide/pyguide.html#docstrings).
- See [Contribution Guidelines](CONTRIBUTING.md) for details.

## About

This work was developed with the support of a
[US Research Software Sustainability Institute](https://urssi.us/) early-career
fellowship. Thanks to helpful discussions with Patrick Ball, Bailey Passmore,
and Tarak Shah. Principled Data Processing was a framework developed by the
[Human Rights Data Analysis Group](https://hrdag.org) in the early 2000s, to
facilitate reproducibility in their forensic human rights work.
