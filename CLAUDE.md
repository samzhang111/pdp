# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Installation and Setup
- `poetry install` - Install dependencies and set up virtual environment
- `poetry shell` - Activate the virtual environment

### Running the CLI
- `poetry run pdp --help` - View available commands
- `poetry run pdp init` - Initialize a new PDP project
- `poetry run pdp create <task_names>` - Create new tasks
- `poetry run pdp run [task_name]` - Run a specific task or all tasks from project root
- `poetry run pdp tree` - Display task hierarchy
- `poetry run pdp validate` - Validate project configuration
- `poetry run pdp scaffold` - Create input/output folders for existing tasks

### Testing
- `poetry run pytest` - Run all tests
- `poetry run pytest tests/test_cli.py` - Run specific test file
- `poetry run pytest -v` - Run tests with verbose output
- Tests use `expects` assertion library and `pyfakefs` for filesystem mocking

## Architecture Overview

### Core Components

**PDP Class** (`pdp/pdp.py`): Central orchestrator that manages the entire project lifecycle. Handles project initialization, task creation, validation, and execution coordination. Uses a config-driven approach where project metadata is stored in `pdp.yml` at the project root.

**Task Class** (`pdp/task.py`): Represents individual tasks with hierarchical subtask support. Each task has three standard directories: `input/`, `src/`, and `output/`. Tasks can be atomic (leaf nodes) or composite (containing subtasks). Execution happens via configurable entrypoints (typically `make`).

**Configuration System** (`pdp_config.py`): Manages YAML-based configuration files (`pdp.yml` for projects, `task.yml` for individual tasks). Handles validation, initialization, and task hierarchy definitions.

**CLI Interface** (`pdp/cli.py`): Typer-based command-line interface with rich console output. Provides project management commands and integrates with the core PDP functionality.

### Key Design Patterns

- **Project Root Discovery**: Uses upward directory traversal to find `pdp.yml` files, similar to Git's repository detection
- **Hierarchical Task Structure**: Tasks can contain subtasks, creating a tree-like project organization
- **Separation of Concerns**: Tasks only write to their `output/` folders and never read from their own outputs
- **Configuration-Driven**: Project structure and task relationships defined declaratively in YAML files

### Data Flow
1. CLI commands invoke PDP class methods
2. PDP class coordinates with Task instances and configuration files
3. Tasks execute via subprocess calls to their configured entrypoints
4. Results propagate back through the hierarchy with return code aggregation

## Project Structure Conventions

- `pdp/` - Main package containing all source code
- `tests/` - Test suite using pytest, expects, and pyfakefs
- `pyproject.toml` - Poetry configuration with dependencies and scripts
- Projects using this tool will have:
  - `pdp.yml` at root defining project metadata and task list
  - Task directories with `task.yml`, `input/`, `src/`, `output/` subdirectories
  - Entrypoint commands (usually `make`) in each atomic task

## Dependencies

- **typer**: CLI framework with rich integration
- **ruamel.yaml**: YAML processing with preservation of formatting
- **rich**: Terminal formatting and tree visualization
- **pytest + expects + pyfakefs**: Testing stack with BDD-style assertions and filesystem mocking