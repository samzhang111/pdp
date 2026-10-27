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
- [Usage](#usage)
- [Install](#install)
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

# Install PDP
uv tool install "pdp[dagster] @ git+https://github.com/scienceandhumanitylab/pdp"

# Alternatively, install just the core PDP features
# No Dagster or Slurm - local use only
uv tool install "pdp @ git+https://github.com/scienceandhumanitylab/pdp"

# Upgrade PDP
uv tool upgrade pdp
```

**Requirements:**

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

Optional

- dagster>=1.13,<1.14
- dagster-webserver>=1.13,<1.14

## Usage

### Editing an existing PDP project

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
- `pdp run` always runs in the local environment and does not require Dagster or
  Slurm.

### Run with Dagster

- Run `pdp dagster dev` to start Dagster UI. From there, you can materialize
  assets. No other Dagster CLI commands currently pass through.
- Tasks from PDP are generated as Dagster assets. Observations are used to
  record events so that changes to outputs outside of Dagster are properly
  recognized.

### Run with Slurm

- The VACC has `uv` and `tmux` installed by default. Both are required to be
  able to run PDP on Slurm.
- Put slurm flags in an optional `slurm:` block in the `pdp.yml`. You can also
  set `task.yml` with settings that override the `pdp.yml` for that task.
- Datasets on the VACC can be symlinked in your local project
  (`ln -s /path/from/vacc task/input/data.csv`). Symlinks will sync with PDP to
  be able to access those datasets during runtime.
- Run `pdp dagster dev --slurm` to run the project with each task as a Slurm
  job.

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
- `pdp remote push` syncs the project to the cluster.
- `pdp remote pull` pulls each task's `output/` from the cluster back to your
  local machine. It refuses while jobs are still running, but can be interrupted
  with `--force`.
- `pdp remote stop` ends the tmux session and cancels PDP's remaining Slurm
  jobs.

#### From the Cluster

Clone your repository into a directory project on the cluster. Then, on a login
node:

```sh
tmux new -s pdp
pdp dagster dev --slurm -p 3000   # 3000 is default
```

Forward the port from your local machine with
`ssh -N -L 3000:localhost:3000 <node>` and open localhost:3000 to materialize
assets in the UI.

### Additional commands

- Run `pdp tree` to see the tree structure of all tasks.
- Run `pdp validate` to validate the project configuration.

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

See [Contribution Guidelines](CONTRIBUTING.md) for details.

## About

This work was developed with the support of a
[US Research Software Sustainability Institute](https://urssi.us/) early-career
fellowship. Thanks to helpful discussions with Patrick Ball, Bailey Passmore,
and Tarak Shah. Principled Data Processing was a framework developed by the
[Human Rights Data Analysis Group](https://hrdag.org) in the early 2000s, to
facilitate reproducibility in their forensic human rights work.
