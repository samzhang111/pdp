import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML
from expects import *
import pytest

from task import Task
from pdp_config import TaskConfig


def test_task_runs_entrypoint_in_config(fs):
    task_name = "hello"
    task_parent = Path(".")
    task_config_path = Path(task_name) / "task.yml"

    task_config = TaskConfig(task_name, config_path=task_config_path)

    task = Task(task_name, task_parent, task_config)
    task.scaffold()

    with open(task_config_path, "w") as f:
        f.write("entrypoint: echo hello\nsubtasks: []")

    mock_result = subprocess.CompletedProcess(
        args=["echo", "hello"], returncode=0, stdout="hello\n"
    )

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        return_code = task.run()
        mock_run.assert_called_once_with("echo hello")
        expect(return_code).to(equal(0))
