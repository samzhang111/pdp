<h1 align="center">
  pdp: Principled Data Processing
</h1>

<p align="center">
  <b>A command-line tool for reproducible data analysis workflows.</b>
</p>

Principled Data Processing is a reproducible and readable way to organize data analyses.
`pdp` is a command-line tool that makes using Principled Data Processing very simple.

##### Table of contents

- [Principles](#principles)
- [Usage](#usage)
- [Install](#install)
- [Contributing](#contributing)
- [About PDP](#about)

## Principles

As in says in the title, Principled Data Processing lays out a few, well, principles. These principles are:

1. Projects are separated into _tasks_, which are folders in the filesystem. A task is either a collection of subtasks, which are themselves subdirectories in the task, or an _atomic_ task which contains no further subtasks.

2. Atomic tasks contain folders for `input` (input data for the task), `src` (source code), and `output` (where the task writes its outputs). Importantly, tasks only write to their output folders, and never read from their own outputs.

3. Tasks have an entrypoint that allows them to be run with a single command. Usually this is `make`.

## Install

Soon to be available on PyPI. In the repository, `cli.py` is the commandline tool, which I alias to `pdp`.

**Requirements:**

- Python 3.11+

## Usage

The motivation for this tool is to streamline the application of these principles to any data analysis project.

### Starting a project

Run `pdp init` from the root of a project. It creates a file called `pdp.yml`, which contains metadata about the project, and marks the project root.

### Creating tasks

Run `pdp create <name_of_task>` to create a task. This creates a directory called <name_of_task>, as well as the folders within that task.

### Creating tasks

Run `pdp create <name_of_task>` to create a task. If in the project root, this creates a task. If in a task, this creates a subtask.

### Running tasks

Run `pdp run` from within a task to run that task. If in the project root, this runs all tasks.

### Listing tasks

Run `pdp tree` to see the tree structure of all tasks.

### Validating project

Run `pdp validate` to validate the project configuration.

### Further help

This documentation is work in progress. Run `pdp --help` to see the .

## Contributing

Contributions should be tested. All code should be formatted using [black](https://github.com/psf/black), and tested. Use `pytest` to run the tests.

## About

This work was developed with the support of a [US Research Software Sustainability Institute](https://urssi.us/) early-career fellowship.
Thanks to helpful discussions with Patrick Ball, Tarak Shah, Bailey Passmore, and Ayyub Ibrahim, and many conversations about PDP with Daniel Manrique-Vallier.
Principled Data Processing was a framework developed by the [Human Rights Data Analysis Group](https://hrdag.org) in the early 2000s, to facilitate reproducibility in their forensic human rights work.
Incidentally, I've come to think it's one of the better ways of organizing data analysis projects in general.
