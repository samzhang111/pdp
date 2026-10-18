<h1 align="center">
  pdp: Principled Data Processing
</h1>

<p align="center">
  <b>A command-line tool for reproducible data analysis workflows.</b>
</p>

Principled Data Processing is a reproducible and readable way to organize data analyses.
`pdp` is a command-line tool that makes using Principled Data Processing very simple.
This tool is designed both to be opinionated (see [Principles](#principles) below), as well as easy to bolt onto existing PDP projects (see [Usage](#usage)).

##### Table of contents

- [Principles](#principles)
- [Usage](#usage)
- [Install](#install)
- [Contributing](#contributing)
- [About PDP](#about)

## Principles

1. Projects are separated into _tasks_, which are folders in the filesystem. A task is either a collection of subtasks, which are themselves subdirectories in the task, or an _atomic_ task which contains no further subtasks. **NOTE:** subtask functionality is delayed - project only currently works with single level tasks.

2. Atomic tasks contain folders for `input` (input data for the task), `src` (source code), and `output` (where the task writes its outputs). Importantly, tasks only write to their output folders, and never read from their own outputs.

3. Tasks have an entrypoint that allows them to be run with a single command. Usually this is `make`.

## Install

Soon to be available on PyPI. Meanwhile, clone and install with [uv tool](https://docs.astral.sh/uv/concepts/tools/):

```sh
# install uv if needed:
curl -LsSf https://astral.sh/uv/install.sh | sh

# clone and install pdp
git clone https://github.com/samzhang111/pdp.git
uv tool install ./pdp

# install pdp with dagster (optional):
uv tool install "./pdp[dagster]"
```

**Requirements:**

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

Optional

- dagster>=1.13,<1.14
- dagster-webserver>=1.13,<1.14

## Usage

### Editing an existing PDP project

- Run `pdp init` from the root of a project. It creates a file called `pdp.yml`, which contains metadata about the project, and marks the project root.
- Edit the `tasks` key in the `pdp.yml` file to list all the tasks in order.
- Run `pdp init` again, to initialize the `task.yml` files within each of those tasks.
- Edit each `task.yml` to designate the entrypoint, which would be `make` for most PDP projects.
- Run `pdp run` from within a task to run that task. If in the project root, this runs all tasks.

### Starting a new project from scratch

- Run `pdp init` from the root of a project. It creates a file called `pdp.yml`, which contains metadata about the project, and marks the project root.
- Run `pdp create <name_of_task1> <name_of_task2> ... <name_of_taskN>` to create tasks. This creates directories for each task, a `task.yml` configuration file, as well as the `src`, `input`, and `output` folders within that task. Task names may contain upper or lower cases letters, digits, and can be separated by one or more single underscores (`_`) or dashes (`-`).
- Edit each `task.yml` to designate a specific command to run as an entrypoint, such as `make`.
- Run `pdp run` from within a task to run that task. If in the project root, this runs all tasks.

### Dagster

- Run `pdp dagster dev` to start

### Additional commands

- Run `pdp tree` to see the tree structure of all tasks.
- Run `pdp validate` to validate the project configuration.

## Contributing

Install `uv`, clone repository and sync dependencies:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/samzhang111/pdp.git
uv sync
```

Install as an editable tool with Dagster for development:

```
uv tool install --force --editable "[dagster]"
```

Guidelines

- Run tests with `uv run pytest`.
- Code should be formatted and linted with [Ruff](https://github.com/astral-sh/ruff). 
- Use [Google style docstrings](https://google.github.io/styleguide/pyguide.html#docstrings).

## About

This work was developed with the support of a [US Research Software Sustainability Institute](https://urssi.us/) early-career fellowship.
Thanks to helpful discussions with Patrick Ball, Bailey Passmore, and Tarak Shah.
Principled Data Processing was a framework developed by the [Human Rights Data Analysis Group](https://hrdag.org) in the early 2000s, to facilitate reproducibility in their forensic human rights work.
