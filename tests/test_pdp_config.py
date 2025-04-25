import os
from pathlib import Path

from ruamel.yaml import YAML
from expects import *
import pytest

from pdp_config import PDPConfig, TaskConfig


def test_config_initialization(fs):
    config = PDPConfig()
    expect(config.read_config_file()).to(equal({}))

    config.config_path.touch()
    expect(config.read_config_file()).to(equal({}))

    expect(config.initialized).to(be_false)


def test_config_initialize_creates_file(fs):
    config = PDPConfig()
    config.initialize()

    with open("pdp.yml") as f:
        expect(f.read().strip()).to(equal("tasks: []"))


def test_config_add_task(fs):
    config = PDPConfig()
    config.initialize()

    config.add_task("hello")
    expect(config.config["tasks"]).to(equal(["hello"]))

    config.add_task("world")
    expect(config.config["tasks"]).to(equal(["hello", "world"]))

    config.add_task("hello")
    expect(config.config["tasks"]).to(equal(["hello", "world"]))

    with open("pdp.yml") as f:
        expect(f.read().strip()).to(equal("tasks:\n- hello\n- world"))


def test_config_validate(fs):
    config = PDPConfig()
    config.initialize()

    expect(config.validate()).to(be_true)

    config.update_config({"tasks": "hello"})
    expect(config.validate()).to(be_false)

    config.update_config({"tasks": ["hello", "world"]})
    expect(config.validate()).to(be_true)

    config.update_config({"no_tasks": 123})
    expect(config.validate()).to(be_false)


def test_config_finds_pdp_yml_from_parents(fs):
    with open("./pdp.yml", "w") as f:
        f.write("tasks:\n  - hello\n  - world\n")

    nested_dir = Path("nested")
    nested_dir.mkdir(parents=True, exist_ok=True)

    os.chdir(nested_dir)

    config = PDPConfig()
    config.initialize()

    expect(config.config_path).to(equal(Path("/pdp.yml")))


def test_config_uses_current_directory_if_no_pdp_yml_found(fs):
    nested_dir = Path("nested")
    nested_dir.mkdir(parents=True, exist_ok=True)

    os.chdir(nested_dir)

    config = PDPConfig()
    config.initialize()

    expect(config.config_path).to(equal(Path("/nested/pdp.yml")))


def test_task_config_initializes_with_entrypoint_and_subtasks(fs):
    config = TaskConfig("task1", "task.yml")
    config.initialize()

    with open("task.yml") as f:
        expect(f.read().strip()).to(equal("entrypoint: make\nsubtasks: []"))


def test_task_config_validation_requires_subtasks_and_entrypoint(fs):
    config = TaskConfig("task1", "task.yml")
    config.initialize()

    expect(config.validate()).to(be_true)

    # only subtasks, without entrypoint
    config.update_config({"subtasks": []})
    expect(config.validate()).to(be_false)

    # only entrypoint, without subtasks
    config.update_config({"entrypoint": "make"})
    expect(config.validate()).to(be_false)
