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

1. Projects are separated into _tasks_, which are folders in the filesystem. A task is either a collection of subtasks, which are themselves subdirectories in the task, or an _atomic_ task which contains no further subtasks.

2. Atomic tasks contain folders for `input` (input data for the task), `src` (source code), and `output` (where the task writes its outputs). Importantly, tasks only write to their output folders, and never read from their own outputs.

3. Tasks have an entrypoint that allows them to be run with a single command. Usually this is `make`.

## Install

Soon to be available on PyPI. Meanwhile, clone the repository, and run `poetry install`.

**Requirements:**

- Python 3.11+
- [poetry](https://python-poetry.org/)

## Usage

### Editing an existing PDP project

- Run `pdp init` from the root of a project. It creates a file called `pdp.yml`, which contains metadata about the project, and marks the project root.
- Edit the `tasks` key in the `pdp.yml` file to list all the tasks in order.
- Run `pdp init` again, to initialize the `task.yml` files within each of those tasks.
- Edit each `task.yml` to designate the entrypoint, which would be `make` for most PDP projects.
- Run `pdp run` from within a task to run that task. If in the project root, this runs all tasks.

### Starting a new project from scratch

- Run `pdp init` from the root of a project. It creates a file called `pdp.yml`, which contains metadata about the project, and marks the project root.
- Run `pdp create <name_of_task1> <name_of_task2> ... <name_of_taskN>` to create tasks. This creates directories for each task, a `task.yml` configuration file, as well as the `src`, `input`, and `output` folders within that task.
- Edit each `task.yml` to designate a specific command to run as an entrypoint, such as `make`.
- Run `pdp run` from within a task to run that task. If in the project root, this runs all tasks.

### Additional commands

- Run `pdp tree` to see the tree structure of all tasks.
- Run `pdp validate` to validate the project configuration.

## Contributing

All code should be tested and formatted using [black](https://github.com/psf/black).

## About

This work was developed with the support of a [US Research Software Sustainability Institute](https://urssi.us/) early-career fellowship.
Thanks to helpful discussions with Patrick Ball, Bailey Passmore, and Tarak Shah.
Principled Data Processing was a framework developed by the [Human Rights Data Analysis Group](https://hrdag.org) in the early 2000s, to facilitate reproducibility in their forensic human rights work.
