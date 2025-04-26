import os
from pathlib import Path

from ruamel.yaml import YAML
from expects import *
import pytest

from pdp_config import PDPConfig, TaskConfig


@pytest.fixture
def config(fs):
    config = PDPConfig(Path("pdp.yml"))
    yield config


def test_config_initialization(config, fs):
    expect(config.read_config_file()).to(equal({}))

    config.path_to_config.touch()
    expect(config.read_config_file()).to(equal({}))

    expect(config.initialized).to(be_false)


def test_config_initialize_creates_file(config, fs):
    config.initialize()

    with open("pdp.yml") as f:
        expect(f.read().strip()).to(equal("tasks: []"))


def test_config_add_task(config, fs):
    config.initialize()

    config.add_task("hello")
    expect(config.config["tasks"]).to(equal(["hello"]))

    config.add_task("world")
    expect(config.config["tasks"]).to(equal(["hello", "world"]))

    config.add_task("hello")
    expect(config.config["tasks"]).to(equal(["hello", "world"]))

    with open("pdp.yml") as f:
        expect(f.read().strip()).to(equal("tasks:\n- hello\n- world"))


def test_config_validate(config, fs):
    config.initialize()

    expect(config.validate()).to(be_true)

    config.update_config({"tasks": "hello"})
    expect(config.validate()).to(be_false)

    config.update_config({"tasks": ["hello", "world"]})
    expect(config.validate()).to(be_true)

    config.update_config({"no_tasks": 123})
    expect(config.validate()).to(be_false)


def test_task_config_initializes_with_entrypoint_and_subtasks(fs):
    config = TaskConfig("task1", "task.yml")
    config.initialize()

    with open("task.yml") as f:
        expect(f.read().strip()).to(equal("entrypoint: ''\nsubtasks: []"))


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


def test_task_adds_its_own_tasks(fs):
    config = TaskConfig("task1", "task.yml")
    config.initialize()

    config.add_task("task2")
    expect(config.tasks).to(equal(["task2"]))

    yaml = YAML()
    task_yaml = dict(yaml.load(Path("task.yml")))
    expect(task_yaml).to(equal({"entrypoint": "", "subtasks": ["task2"]}))


def test_task_config_repr_prints_name_and_path(fs):
    config = TaskConfig("task1", "task.yml")
    expect(str(config)).to(equal("TaskConfig(task1, /task.yml)"))


def test_pdp_config_repr_prints_config_path(config, fs):
    expect(str(config)).to(equal("PDPConfig(/pdp.yml)"))
