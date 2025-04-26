import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML
from expects import *
import pytest

from task import Task
from pdp_config import TaskConfig


@pytest.fixture
def task(fs):
    task_name = "hello"
    task = Task(task_name, Path(task_name))

    return task


def test_task_runs_entrypoint_in_config(task, fs):
    task.scaffold()

    with open(task.task_config.path_to_config, "w") as f:
        f.write("entrypoint: echo hello\nsubtasks: []")

    mock_result = subprocess.CompletedProcess(
        args=["echo", "hello"], returncode=0, stdout="hello\n"
    )

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        return_code = task.run()
        mock_run.assert_called_once_with("echo hello", cwd=task.task_directory)
        expect(return_code).to(equal(0))


def test_task_create_subtask(task, fs):
    task.scaffold()

    subtask = task.create_subtask("world")

    with open(task.task_config.path_to_config, "r") as f:
        yaml = YAML()
        task_dict = dict(yaml.load(f))

    expect(task_dict).to(equal({"entrypoint": "", "subtasks": ["world"]}))

    expect(Path("/hello/world/input").exists()).to(be_true)
    expect(Path("/hello/world/output").exists()).to(be_true)
    expect(Path("/hello/world/src").exists()).to(be_true)

    yaml = YAML()
    subtask_dict = dict(yaml.load(Path("/hello/world/task.yml")))
    expect(subtask_dict).to(equal({"entrypoint": "", "subtasks": []}))

    # Removes the hello input, output, and src
    expect(Path("/hello/input").exists()).to(be_false)
    expect(Path("/hello/output").exists()).to(be_false)
    expect(Path("/hello/src").exists()).to(be_false)


def test_task_create_subtask_leaves_folders_if_nonempty(task, fs):
    task.scaffold()

    Path("/hello/src/test.py").touch()

    subtask = task.create_subtask("world")

    expect(Path("/hello/input").exists()).to(be_true)
    expect(Path("/hello/output").exists()).to(be_true)
    expect(Path("/hello/src").exists()).to(be_true)


def test_task_scaffold_scaffolds_subtasks(task, fs):
    task.scaffold()
    with open(task.task_config.path_to_config, "w") as f:
        f.write("entrypoint: \nsubtasks: ['world']")

    task.scaffold()
    expect(Path("/hello/world/input").exists()).to(be_true)
    expect(Path("/hello/world/output").exists()).to(be_true)
    expect(Path("/hello/world/src").exists()).to(be_true)

    expect(Path("/hello/input").exists()).to(be_false)
    expect(Path("/hello/output").exists()).to(be_false)
    expect(Path("/hello/src").exists()).to(be_false)


def test_task_equality_based_on_repr(task, fs):
    task_name = "hello"
    task2 = Task(task_name, Path(task_name))

    expect(task).to(equal(task2))


def test_task_runs_subtasks_if_exist(task, fs):
    task.scaffold()

    subtask = task.create_subtask("world")

    with open(subtask.task_config.path_to_config, "w") as f:
        f.write("entrypoint: echo world\nsubtasks: []")

    mock_result = subprocess.CompletedProcess(
        args=["echo", "world"], returncode=0, stdout="world\n"
    )

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        return_code = task.run()
        mock_run.assert_called_once_with("echo world", cwd=subtask.task_directory)
        expect(return_code).to(equal(0))
