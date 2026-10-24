import os
import subprocess
from pathlib import Path
from unittest.mock import ANY, patch

from expects import *
from ruamel.yaml import YAML

from pdp.task import Task, latest_mtime_in_dir
from tests.helpers import backdate_task_yml, write_task_yml


def read_config_file(filename):
    return dict(YAML().load(Path(filename)))


def touch(path: Path, mtime: int):
    path.touch()
    os.utime(path, (mtime, mtime))


class TestScaffold:
    def test_task_runs_entrypoint_in_config(self, task, fs):
        task.scaffold()

        with open(task.task_config.path_to_config, "w") as f:
            f.write("entrypoint: echo hello\nsubtasks: []")

        mock_result = subprocess.CompletedProcess(
            args=["echo", "hello"], returncode=0, stdout="hello\n"
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            return_code = task.run()
            mock_run.assert_called_once_with(
                "echo hello", cwd=task.task_directory, shell=True, check=False, env=ANY
            )
            expect(return_code).to(equal(0))

    def test_task_scaffold_creates_folders(self, task, fs):
        task.scaffold()

        expect(task.input_folder.is_dir()).to(be_true)
        expect(task.output_folder.is_dir()).to(be_true)
        expect(task.src_folder.is_dir()).to(be_true)

    def test_task_scaffold_ignores_subtasks_and_always_creates_folders(self, fs):
        """Will revisit subtasks later"""
        Path("/hello").mkdir()
        write_task_yml("/hello", subtasks=["world"])
        task = Task("hello", Path("/hello"))

        task.scaffold()

        expect(task.input_folder.is_dir()).to(be_true)
        expect(task.output_folder.is_dir()).to(be_true)
        expect(task.src_folder.is_dir()).to(be_true)
        expect(Path("/hello/world").exists()).to(be_false)

    def test_task_scaffold_passes_validation(self, task, fs):
        task.scaffold()

        expect(task.validation_errors()).to(equal([]))
        expect(task.validate()).to(be_true)


class Validate:
    def test_task_validate_raises_on_unscaffolded_task(self, task, fs):
        errors = task.validation_errors()

        expect(errors).to(contain("Missing key(s): depends_on, entrypoint, name"))
        expect(errors).to(contain("name must be a non-empty string"))
        expect(errors).to(contain("input/ folder is missing"))
        expect(errors).to(contain("output/ folder is missing"))
        expect(errors).to(contain("src/ folder is missing"))
        expect(task.validate()).to(be_false)


def test_task_id_is_directory_name(fs):
    Path("/pdp.yml").write_text("name: test\ntasks: []\n")

    task = Task("hello", Path("/somewhere/deeper/hello"))

    expect(task.task_id).to(equal("hello"))


def test_task_equality_based_on_repr(task, fs):
    task_name = "hello"
    task2 = Task(task_name, Path(task_name))

    expect(task).to(equal(task2))


class TestStaleness:
    def test_latest_mtime_in_dir_returns_newest_mtime(self, task, fs):
        task.scaffold()

        touch(task.output_folder / "old.txt", 1000)
        touch(task.output_folder / "new.txt", 2000)

        expect(latest_mtime_in_dir(task.output_folder)).to(equal(2000))

    def test_latest_mtime_in_dir_checks_subdirs(self, task, fs):
        task.scaffold()

        nested_dir = task.output_folder / "nested"
        nested_dir.mkdir()

        touch(task.output_folder / "top.txt", 1000)
        touch(nested_dir / "deep.txt", 5000)

        expect(latest_mtime_in_dir(task.output_folder)).to(equal(5000))

    def test_latest_mtime_in_dir_empty_returns_none(self, task, fs):
        task.scaffold()

        expect(latest_mtime_in_dir(task.output_folder)).to(be_none)

    def test_task_is_stale_when_output_missing(self, import_and_clean):
        _, clean = import_and_clean

        expect(clean.is_stale).to(be_true)

    def test_task_is_stale_when_dependency_is_newer(self, import_and_clean):
        import_task, clean = import_and_clean

        touch(clean.output_folder / "result.txt", 1000)
        touch(import_task.output_folder / "data.txt", 2000)

        expect(clean.is_stale).to(be_true)

    def test_task_not_stale_when_own_output_is_newer_than_dependency(
        self, import_and_clean
    ):
        import_task, clean = import_and_clean

        touch(import_task.output_folder / "data.txt", 1000)
        touch(clean.output_folder / "result.txt", 2000)

        expect(clean.is_stale).to(be_false)

    def test_task_is_stale_when_src_is_newer(self, task, fs):
        task.scaffold()

        touch(task.src_folder / "script.py", 2000)
        touch(task.output_folder / "output.csv", 1000)
        expect(task.is_stale).to(be_true)

    def test_task_not_stale_when_src_is_older(self, task, fs):
        task.scaffold()
        backdate_task_yml(task)

        touch(task.src_folder / "script.py", 1000)
        touch(task.output_folder / "output.csv", 2000)

        expect(task.is_stale).to(be_false)

    def test_task_is_stale_when_only_one_of_multiple_dependencies_is_newer(
        self, two_deps_and_clean
    ):
        import1, import2, clean = two_deps_and_clean

        touch(clean.output_folder / "output.csv", 2000)
        touch(import1.output_folder / "data1.csv", 1000)
        touch(import2.output_folder / "data2.csv", 3000)

        expect(clean.is_stale).to(be_true)

    def test_task_not_stale_when_all_dependencies_are_older(self, two_deps_and_clean):
        import1, import2, clean = two_deps_and_clean

        touch(clean.output_folder / "result.txt", 2000)
        touch(import1.output_folder / "data1.txt", 1000)
        touch(import2.output_folder / "data2.txt", 1500)

        expect(clean.is_stale).to(be_false)

    def test_task_is_stale_when_input_file_symlink_target_is_newer(
        self, real_task, tmp_path
    ):
        target = tmp_path / "data.csv"
        touch(target, 2000)
        (real_task.input_folder / "data.csv").symlink_to(target)
        touch(real_task.output_folder / "result.csv", 1000)

        expect(real_task.is_stale).to(be_true)

    def test_task_is_stale_when_output_has_no_files(self, real_task):
        (real_task.output_folder / "empty_subdir").mkdir()

        expect(real_task.is_stale).to(be_true)

    def test_task_ignores_broken_symlink_in_input(self, real_task, tmp_path):
        (real_task.input_folder / "gone.csv").symlink_to(tmp_path / "missing.csv")
        touch(real_task.output_folder / "result.csv", 1000)

        expect(real_task.is_stale).to(be_false)

    def test_task_is_stale_when_input_file_is_newer(self, real_task):
        touch(real_task.input_folder / "data.csv", 2000)
        touch(real_task.output_folder / "result.csv", 1000)

        expect(real_task.is_stale).to(be_true)

    def test_task_is_stale_when_hand_file_is_newer(self, real_task):
        hand = real_task.task_directory / "hand"
        hand.mkdir()
        touch(hand / "fix.csv", 2000)
        touch(real_task.output_folder / "result.csv", 1000)

        expect(real_task.is_stale).to(be_true)

    def test_task_not_stale_when_hand_is_empty(self, real_task):
        (real_task.task_directory / "hand").mkdir()
        touch(real_task.output_folder / "result.csv", 1000)

        expect(real_task.is_stale).to(be_false)

    def test_task_not_stale_when_input_is_missing(self, real_task):
        real_task.input_folder.rmdir()
        touch(real_task.output_folder / "result.csv", 1000)

        expect(real_task.is_stale).to(be_false)

    def test_task_does_not_follow_directory_symlinks_in_input(
        self, real_task, tmp_path
    ):
        """Dependency links are directory symlinks; their freshness comes from
        the dependency checks, not the input/ walk."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        touch(elsewhere / "data.csv", 2000)
        (real_task.input_folder / "elsewhere").symlink_to(elsewhere)
        touch(real_task.output_folder / "result.csv", 1000)

        expect(real_task.is_stale).to(be_false)

    def test_chain_not_stale_when_everything_is_fresh(self, real_dag):
        import_task, clean, report = real_dag
        touch(import_task.src_folder / "script.py", 500)
        touch(import_task.output_folder / "data.csv", 1000)
        touch(clean.output_folder / "clean.csv", 2000)
        touch(report.output_folder / "report.csv", 3000)

        expect(report.is_stale).to(be_false)

    def test_task_is_stale_when_dependency_is_stale_despite_fresh_mtimes(
        self, real_dag
    ):
        import_task, clean, _ = real_dag
        touch(import_task.output_folder / "data.csv", 1000)
        touch(import_task.src_folder / "script.py", 2000)  # import is stale
        touch(clean.output_folder / "clean.csv", 3000)  # newer than everything

        expect(clean.is_stale).to(be_true)

    def test_task_is_stale_when_dependency_output_is_empty(self, real_dag):
        _, clean, _ = real_dag
        touch(clean.output_folder / "clean.csv", 1000)

        expect(clean.is_stale).to(be_true)

    def test_staleness_is_transitive_across_dag(self, real_dag):
        import_task, clean, report = real_dag
        touch(import_task.output_folder / "data.csv", 1000)
        touch(import_task.src_folder / "script.py", 2000)  # import is stale
        touch(clean.output_folder / "clean.csv", 3000)
        touch(report.output_folder / "report.csv", 4000)

        expect(report.is_stale).to(be_true)

    def test_task_stale_when_task_yml_newer(self, real_task):
        touch(real_task.output_folder / "result.csv", 1000)
        touch(real_task.task_directory / "task.yml", 2000)

        expect(real_task.is_stale).to(be_true)

    def test_task_stale_when_task_root_file_is_newer(self, real_task):
        touch(real_task.task_directory / "task.yml", 500)
        touch(real_task.output_folder / "result.csv", 1000)
        touch(real_task.task_directory / "Makefile", 2000)

        expect(real_task.is_stale).to(be_true)

    def test_task_staleness_ignores_hidden_files_at_task_root(self, real_task):
        touch(real_task.task_directory / "task.yml", 500)
        touch(real_task.output_folder / "result.csv", 1000)
        touch(real_task.task_directory / ".task.yml.swp", 2000)

        expect(real_task.is_stale).to(be_false)


class TestSlurmFlags:
    def test_renders_flags_in_key_order(self, real_task):
        write_task_yml(
            real_task.task_directory, slurm={"time": "02:00:00", "mem": "16G"}
        )

        expect(real_task.slurm_flags({})).to(equal(["--mem=16G", "--time=02:00:00"]))

    def test_task_keys_override_project_defaults(self, real_task):
        write_task_yml(real_task.task_directory, slurm={"mem": "32G"})

        flags = real_task.slurm_flags(
            {"mem": "16G", "partition": "general", "ntasks": 1}
        )

        expect(flags).to(equal(["--mem=32G", "--ntasks=1", "--partition=general"]))

    def test_no_slurm_block_uses_project_defaults(self, real_task):
        expect(real_task.slurm_flags({"mem": "16G"})).to(equal(["--mem=16G"]))
