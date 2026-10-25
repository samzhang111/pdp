import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import ANY, call, patch

import pytest
from expects import *
from ruamel.yaml import YAML
from typer.testing import CliRunner

from pdp.cli import app
from tests.helpers import backdate_task_yml, write_task_yml


@pytest.fixture
def runner(fs):
    runner = CliRunner(mix_stderr=False)
    _ = runner.invoke(app, ["init", "--name", "test"])

    return runner


def read_config_file(filename):
    return dict(YAML().load(Path(filename)))


def run_dagster_dev(returncode=0, args=()):
    with patch("subprocess.Popen") as popen:
        popen.return_value.wait.return_value = returncode
        result = CliRunner(mix_stderr=False).invoke(app, ["dagster", "dev", *args])
    return result, popen


class TestInitCli:
    def test_init_creates_pdp_yaml(self, runner, fs):
        config_dict = read_config_file("/pdp.yml")
        expect(config_dict["name"]).to(equal("test"))
        expect(config_dict["tasks"]).to(equal([]))


class TestCreateCli:
    def test_create_tasks(self, runner, fs):
        _ = runner.invoke(app, ["create", "hello", "world"])

        expect(Path("/hello/input").exists()).to(be_true)
        expect(Path("/hello/output").exists()).to(be_true)
        expect(Path("/hello/src").exists()).to(be_true)

        expect(Path("/world/input").exists()).to(be_true)
        expect(Path("/world/output").exists()).to(be_true)
        expect(Path("/world/src").exists()).to(be_true)

    def test_create_from_inside_task_errors(self, runner, fs):
        _ = runner.invoke(app, ["create", "hello"])

        os.chdir("hello")

        result = runner.invoke(app, ["create", "world"])

        expect(result.exit_code).to(equal(1))
        expect(" ".join(result.stderr.split())).to(
            contain("Cannot create task: tasks can only be created at the project root")
        )
        expect(Path("/hello/world").exists()).to(be_false)
        expect(Path("/hello/input").exists()).to(be_true)

    def test_create_errs_if_creating_task_from_invalid_location(self, runner, fs):
        Path("/not_a_task").mkdir(parents=True, exist_ok=True)
        os.chdir("not_a_task")

        result = runner.invoke(app, ["create", "hello"])

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("Cannot create task"))

    def test_create_rejects_invalid_task_name(self, runner, fs):
        bad_name = "bad.task..name"
        result = runner.invoke(app, ["create", bad_name])

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain(f"invalid task name '{bad_name}'"))
        expect(Path(f"/{bad_name}").exists()).to(be_false)


class TestRunCli:
    def test_runs_current_task(self, runner, fs):
        result = runner.invoke(app, ["create", "hello"])

        os.chdir("hello")

        write_task_yml("/hello", entrypoint="echo hello")

        mock_result = subprocess.CompletedProcess(
            args=["echo", "hello"], returncode=0, stdout="world\n"
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = runner.invoke(app, ["run"])
            mock_run.assert_called_once_with(
                "echo hello", cwd=Path("/hello"), shell=True, check=False, env=ANY
            )
            expect(result.exit_code).to(equal(0))

    def test_runs_whole_project(self, runner, fs):
        result = runner.invoke(app, ["create", "hello"])
        result = runner.invoke(app, ["create", "world"])

        write_task_yml("/hello", entrypoint="echo hello")

        write_task_yml("/world", entrypoint="echo world")

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
                    call(
                        "echo hello",
                        cwd=Path("/hello"),
                        shell=True,
                        check=False,
                        env=ANY,
                    ),
                    call(
                        "echo world",
                        cwd=Path("/world"),
                        shell=True,
                        check=False,
                        env=ANY,
                    ),
                ]
            )
            expect(result.exit_code).to(equal(0))

    def test_running_unknown_task_throws_error(self, runner, fs):
        result = runner.invoke(app, ["run", "badtask"])

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("Task badtask not found"))
        expect(result.exception).to(be_a(SystemExit))

    def test_run_with_invalid_pdp_yml_throws_error(self, runner, fs):
        Path("/pdp.yml").write_text("name: test\ntasks:\n  - bad.name\n")

        result = runner.invoke(app, ["run"])

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("Validation failed."))
        expect(result.stderr).to(contain("invalid task name 'bad.name'"))
        expect(result.exception).to(be_a(SystemExit))

    def test_run_reports_failed_and_skipped_tasks(self, import_and_clean_project):
        write_task_yml("import", entrypoint="exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        result = CliRunner(mix_stderr=False).invoke(app, ["run"])

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("Failed: import"))
        expect(result.stderr).to(contain("Skipped (upstream failed): clean"))

    def test_force_flag_runs_a_fresh_task(self, real_pdp):
        task = real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="touch output/ran")
        backdate_task_yml(task)
        (task.output_folder / "result.csv").write_text("done")

        result = CliRunner(mix_stderr=False).invoke(app, ["run", "--force"])

        expect(result.exit_code).to(equal(0))
        expect((task.output_folder / "ran").exists()).to(be_true)

    def test_run_prints_current_and_entrypointless_tasks(self, real_pdp):
        fresh = real_pdp.create_task("fresh")
        write_task_yml("fresh", entrypoint="touch output/ran")
        backdate_task_yml(fresh)
        (fresh.output_folder / "result.csv").write_text("done")
        real_pdp.create_task("hand")

        result = CliRunner(mix_stderr=False).invoke(app, ["run"])

        expect(result.exit_code).to(equal(1))
        expect(result.stdout).to(contain("Current: fresh"))
        expect(result.stderr).to(contain("No entrypoint (failed): hand"))

    def test_run_warns_when_success_wrote_no_output(self, real_pdp):
        """Cover cases where entrypoint only prints, or writes outside of project"""
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="true")

        result = CliRunner(mix_stderr=False).invoke(app, ["run"])

        expect(result.exit_code).to(equal(0))
        expect(result.stderr).to(contain("Ran but wrote nothing to output/: task1"))

    def test_run_prints_tasks_that_ran(self, import_and_clean_project):
        write_task_yml("import", entrypoint="touch output/data.csv")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        result = CliRunner(mix_stderr=False).invoke(app, ["run"])

        expect(result.stdout).to(contain("Ran: import, clean"))


class TestTreeCli:
    def test_tree_enumerates_tasks_as_flat_list(self, runner, fs):
        _ = runner.invoke(app, ["create", "hello", "world"])

        result = runner.invoke(app, ["tree"])

        expect(result.stdout).to(
            equal(
                """1. test
├── 2. hello
└── 3. world
"""
            )
        )


class TestStatusCli:
    def test_status_prints_more_when_verbose_task(self, import_and_clean_project):
        write_task_yml("import", description="Load data")

        result = CliRunner(mix_stderr=False).invoke(app, ["status"])

        expect(result.exit_code).to(equal(0))
        expect(result.stdout).to(contain("Stale"))
        expect(result.stdout).to_not(contain("description: Load data"))

        result = CliRunner(mix_stderr=False).invoke(app, ["status", "-v"])

        expect(result.exit_code).to(equal(0))
        expect(result.stdout).to(contain("status: Stale"))
        expect(result.stdout).to(contain("description: Load data"))
        expect(result.stdout).to(contain("depends on: import"))


class TestDagsterCli:
    def test_pdp_dagster_dev_calls_module(self, real_pdp):
        result, popen = run_dagster_dev()
        root = real_pdp.project_root

        popen.assert_called_once_with(
            [sys.executable, "-m", "dagster", "dev", "-m", "pdp.dagster_defs"],
            cwd=root,
            env=ANY,
        )

        env = popen.call_args.kwargs["env"]
        expect(env["PDP_PROJECT_ROOT"]).to(equal(str(root)))
        expect(env["DAGSTER_HOME"]).to(equal(str(root / ".dagster")))
        expect((root / ".dagster").is_dir()).to(be_true)
        expect(result.exit_code).to(equal(0))

    def test_dagster_dev_honors_existing_dagster_home(self, real_pdp, monkeypatch):
        monkeypatch.setenv("DAGSTER_HOME", "/elsewhere")
        _, popen = run_dagster_dev()

        expect(popen.call_args.kwargs["env"]["DAGSTER_HOME"]).to(equal("/elsewhere"))

    def test_dagster_dev_fails_when_run_outside_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, popen = run_dagster_dev()

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("No project detected"))
        popen.assert_not_called()

    def test_dagster_dev_throws_error_when_dagster_missing(self, real_pdp):
        with patch("importlib.util.find_spec", return_value=None):
            result, popen = run_dagster_dev()

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(contain("Dagster must be installed: `pdp[dagster]`"))
        popen.assert_not_called()

    @pytest.mark.usefixtures("real_pdp")
    def test_dagster_dev_slurm_sets_pdp_slurm(self):
        with patch("shutil.which", return_value="/usr/bin/srun"):
            result, popen = run_dagster_dev(args=["--slurm"])

        expect(result.exit_code).to(equal(0))
        expect(popen.call_args.kwargs["env"]["PDP_SLURM"]).to(equal("1"))

    @pytest.mark.usefixtures("real_pdp")
    def test_dagster_dev_slurm_without_srun_fails(self):
        with patch("shutil.which", return_value=None):
            result, popen = run_dagster_dev(args=["--slurm"])

        expect(result.exit_code).to(equal(1))
        expect(result.stderr).to(
            contain(
                "--slurm needs Slurm's srun on PATH. Run this on a cluster login node"
            )
        )
        popen.assert_not_called()
