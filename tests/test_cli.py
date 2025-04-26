from pathlib import Path
import os
import subprocess
from unittest.mock import patch, call

from expects import *
import pytest
from typer.testing import CliRunner
from ruamel.yaml import YAML

from cli import app


def test_init_creates_pdp_yaml(fs):
    runner = CliRunner()
    result = runner.invoke(app, ["init"])

    with open("pdp.yml") as f:
        expect(f.read().strip()).to(equal("tasks: []"))


def test_create_tasks(fs):
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    result = runner.invoke(app, ["create", "hello", "world"])

    expect(Path("/hello/input").exists()).to(be_true)
    expect(Path("/hello/output").exists()).to(be_true)
    expect(Path("/hello/src").exists()).to(be_true)

    expect(Path("/world/input").exists()).to(be_true)
    expect(Path("/world/output").exists()).to(be_true)
    expect(Path("/world/src").exists()).to(be_true)


def test_create_subtasks(fs):
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    result = runner.invoke(app, ["create", "hello"])

    os.chdir("hello")

    result = runner.invoke(app, ["create", "world"])

    expect(Path("/hello/input").exists()).to(be_false)
    expect(Path("/hello/output").exists()).to(be_false)
    expect(Path("/hello/src").exists()).to(be_false)

    expect(Path("/hello/world/input").exists()).to(be_true)
    expect(Path("/hello/world/output").exists()).to(be_true)
    expect(Path("/hello/world/src").exists()).to(be_true)

    yaml = YAML()
    task_dict = dict(yaml.load(Path("/hello/task.yml")))

    expect(task_dict).to(equal({"entrypoint": "", "subtasks": ["world"]}))


def test_runs_current_task(fs):
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    result = runner.invoke(app, ["create", "hello"])

    os.chdir("hello")

    with open("/hello/task.yml", "w") as f:
        f.write("entrypoint: echo hello\nsubtasks: []")

    mock_result = subprocess.CompletedProcess(
        args=["echo", "hello"], returncode=0, stdout="world\n"
    )

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = runner.invoke(app, ["run"])
        mock_run.assert_called_once_with("echo hello", cwd=Path("/hello"))
        expect(result.exit_code).to(equal(0))


def test_runs_whole_project(fs):
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    result = runner.invoke(app, ["create", "hello"])
    result = runner.invoke(app, ["create", "world"])

    with open("/hello/task.yml", "w") as f:
        f.write("entrypoint: echo hello\nsubtasks: []")

    with open("/world/task.yml", "w") as f:
        f.write("entrypoint: echo world\nsubtasks: []")

    mock_hello = subprocess.CompletedProcess(
        args=["echo", "hello"], returncode=0, stdout="world\n"
    )

    mock_world = subprocess.CompletedProcess(
        args=["echo", "hello"], returncode=0, stdout="world\n"
    )

    with patch("subprocess.run", side_effect=[mock_hello, mock_world]) as mock_run:
        result = runner.invoke(app, ["run"])
        mock_run.assert_has_calls(
            [
                call("echo hello", cwd=Path("/hello")),
                call("echo world", cwd=Path("/world")),
            ]
        )
        expect(result.exit_code).to(equal(0))
