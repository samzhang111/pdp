import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from itertools import count

from ruamel.yaml import YAML
from expects import *
import pytest

from pdp.task import Task
from pdp.pdp_config import TaskConfig


def read_config_file(filename):
    return dict(YAML().load(Path(filename)))


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

    task_dict = read_config_file("/hello/task.yml")

    expect(task_dict["name"]).to(equal("hello"))
    expect(task_dict["entrypoint"]).to(equal(""))
    expect(task_dict["subtasks"]).to(equal(["world"]))

    expect(Path("/hello/world/input").exists()).to(be_true)
    expect(Path("/hello/world/output").exists()).to(be_true)
    expect(Path("/hello/world/src").exists()).to(be_true)

    subtask_dict = read_config_file("/hello/world/task.yml")
    expect(subtask_dict["name"]).to(equal("world"))
    expect(subtask_dict["entrypoint"]).to(equal(""))
    expect(subtask_dict["subtasks"]).to(equal([]))

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


def test_task_traverses_subtree(task, fs):
    task.scaffold()
    subtask = task.create_subtask("world")
    subtask2 = task.create_subtask("world2")
    subtask_world_child = task.create_subtask("world_child")

    counter = count(1)

    results = []
    callback = lambda num, task: results.append((num, task.task_name))
    task.subtree_traversal(counter, callback)

    expect(results).to(
        equal([(1, "hello"), (2, "world"), (3, "world2"), (4, "world_child")])
    )


# SLURM functionality tests
def test_task_config_has_slurm_disabled_by_default(task, fs):
    task.scaffold()
    
    task_dict = read_config_file("/hello/task.yml")
    
    expect(task_dict["slurm"]["enabled"]).to(be_false)
    expect(task_dict["slurm"]["script"]).to(equal(""))


def test_task_config_detects_slurm_enabled(task, fs):
    task.scaffold()
    
    with open(task.task_config.path_to_config, "w") as f:
        f.write("entrypoint: make\nsubtasks: []\nslurm:\n  enabled: true\n  script: job.sbatch")
    
    expect(task.task_config.uses_slurm).to(be_true)
    expect(task.task_config.slurm_script).to(equal("job.sbatch"))


def test_task_runs_sbatch_when_slurm_enabled(task, fs):
    task.scaffold()
    
    # Create SLURM script file
    slurm_script = task.task_directory / "job.sbatch"
    slurm_script.write_text("#!/bin/bash\necho hello")
    
    with open(task.task_config.path_to_config, "w") as f:
        f.write("entrypoint: make\nsubtasks: []\nslurm:\n  enabled: true\n  script: job.sbatch")
    
    # Mock sbatch submission
    sbatch_result = subprocess.CompletedProcess(
        args=["sbatch", "job.sbatch"], returncode=0, stdout="Submitted batch job 12345\n"
    )
    
    # Mock squeue (job running then completed)
    squeue_running = subprocess.CompletedProcess(
        args=["squeue", "-j", "12345", "-h"], returncode=0, stdout="12345 main job.sbatch user R 0:01"
    )
    squeue_completed = subprocess.CompletedProcess(
        args=["squeue", "-j", "12345", "-h"], returncode=0, stdout=""
    )
    
    # Mock sacct (job exit status)
    sacct_result = subprocess.CompletedProcess(
        args=["sacct", "-j", "12345", "--format=ExitCode", "-n"], returncode=0, stdout="0:0\n"
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [sbatch_result, squeue_running, squeue_completed, sacct_result]
        with patch("time.sleep"):  # Speed up the test
            return_code = task.run()
        
        expect(return_code).to(equal(0))
        expect(mock_run.call_count).to(equal(4))


def test_task_handles_slurm_job_failure(task, fs):
    task.scaffold()
    
    # Create SLURM script file
    slurm_script = task.task_directory / "job.sbatch"
    slurm_script.write_text("#!/bin/bash\nexit 1")
    
    with open(task.task_config.path_to_config, "w") as f:
        f.write("entrypoint: make\nsubtasks: []\nslurm:\n  enabled: true\n  script: job.sbatch")
    
    # Mock sbatch submission
    sbatch_result = subprocess.CompletedProcess(
        args=["sbatch", "job.sbatch"], returncode=0, stdout="Submitted batch job 12345\n"
    )
    
    # Mock squeue (job completed)
    squeue_completed = subprocess.CompletedProcess(
        args=["squeue", "-j", "12345", "-h"], returncode=0, stdout=""
    )
    
    # Mock sacct (job failed)
    sacct_result = subprocess.CompletedProcess(
        args=["sacct", "-j", "12345", "--format=ExitCode", "-n"], returncode=0, stdout="1:0\n"
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [sbatch_result, squeue_completed, sacct_result]
        with patch("time.sleep"):
            return_code = task.run()
        
        expect(return_code).to(equal(1))


def test_task_raises_error_when_slurm_script_missing(task, fs):
    task.scaffold()
    
    with open(task.task_config.path_to_config, "w") as f:
        f.write("entrypoint: make\nsubtasks: []\nslurm:\n  enabled: true\n  script: missing.sbatch")
    
    with pytest.raises(FileNotFoundError):
        task.run()


def test_task_handles_sbatch_submission_failure(task, fs):
    task.scaffold()
    
    # Create SLURM script file
    slurm_script = task.task_directory / "job.sbatch"
    slurm_script.write_text("#!/bin/bash\necho hello")
    
    with open(task.task_config.path_to_config, "w") as f:
        f.write("entrypoint: make\nsubtasks: []\nslurm:\n  enabled: true\n  script: job.sbatch")
    
    # Mock sbatch failure
    sbatch_result = subprocess.CompletedProcess(
        args=["sbatch", "job.sbatch"], returncode=1, stdout="", stderr="sbatch: error"
    )
    
    with patch("subprocess.run", return_value=sbatch_result):
        return_code = task.run()
        
        expect(return_code).to(equal(1))


def test_task_runs_subtasks_with_mixed_slurm_and_local(task, fs):
    task.scaffold()
    
    # Create local subtask
    local_subtask = task.create_subtask("local")
    with open(local_subtask.task_config.path_to_config, "w") as f:
        f.write("entrypoint: echo local\nsubtasks: []\nslurm:\n  enabled: false\n  script: \"\"")
    
    # Create SLURM subtask
    slurm_subtask = task.create_subtask("slurm")
    slurm_script = slurm_subtask.task_directory / "job.sbatch"
    slurm_script.write_text("#!/bin/bash\necho slurm")
    
    with open(slurm_subtask.task_config.path_to_config, "w") as f:
        f.write("entrypoint: make\nsubtasks: []\nslurm:\n  enabled: true\n  script: job.sbatch")
    
    # Mock subprocess calls
    local_result = subprocess.CompletedProcess(
        args=["echo", "local"], returncode=0, stdout="local\n"
    )
    
    sbatch_result = subprocess.CompletedProcess(
        args=["sbatch", "job.sbatch"], returncode=0, stdout="Submitted batch job 67890\n"
    )
    
    squeue_completed = subprocess.CompletedProcess(
        args=["squeue", "-j", "67890", "-h"], returncode=0, stdout=""
    )
    
    sacct_result = subprocess.CompletedProcess(
        args=["sacct", "-j", "67890", "--format=ExitCode", "-n"], returncode=0, stdout="0:0\n"
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [local_result, sbatch_result, squeue_completed, sacct_result]
        with patch("time.sleep"):
            return_code = task.run()
        
        expect(return_code).to(equal(0))
        expect(mock_run.call_count).to(equal(4))
