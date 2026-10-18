import os
import subprocess
from pathlib import Path
from unittest.mock import ANY, patch

import pytest
from expects import *
from ruamel.yaml import YAML

from pdp.pdp import PDP, PDPConfig
from pdp.pdp_errors import InvalidConfigError
from pdp.task import Task
from pdp.utils import find_project_root
from tests.helpers import backdate_task_yml, write_task_yml


def read_config_file(filename):
    return dict(YAML().load(Path(filename)))


class TestUtilities:
    def test_find_project_root(self, fs):
        pdp = PDP("test")
        pdp.initialize()

        root = find_project_root("pdp.yml", start=pdp.project_root)
        assert root == pdp.project_root


class TestInitialize:
    def test_pdp_uninitialized_when_config_file_does_not_exist(self, fs):
        pdp = PDP("test")

        expect(pdp.initialized).to(be_false)

    def test_pdp_uninitialized_when_config_file_empty(self, empty_pdp_yaml, fs):
        path = Path("pdp.yml")
        path.touch()

        pdp = PDP("test")
        expect(pdp.initialized).to(be_false)

        pdp.initialize()

        expect(pdp.initialized).to(be_true)

    def test_pdp_inits_empty_task_list(self, fs, pdp):
        config_dict = read_config_file("pdp.yml")
        expect(config_dict["tasks"]).to(equal([]))

    def test_pdp_init_is_idempotent_on_files(self, hello_world_tasks, pdp):
        expect(pdp.config.config).to(
            equal({"name": "test", "tasks": ["hello", "world"]})
        )

    def test_pdp_initialize_raises_error_if_invalid_config(self, yaml_without_tasks):
        config = PDPConfig("test", "pdp.yml")
        with pytest.raises(InvalidConfigError):
            pdp = PDP(config=config)
            pdp.initialize()


class TestValidate:
    def test_pdp_validate_fails_if_config_has_no_tasks(self, empty_pdp_yaml):
        pdp = PDP()
        expect(pdp.validate()).to(be_false)

    def test_pdp_validate_passes_with_no_depends_on_tasks(self, pdp):
        pdp.create_task("hello")
        expect(pdp.validate()).to(be_true)

    def test_pdp_validate_raises_when_depends_on_bad_task(self, pdp):
        task = pdp.create_task("hello")
        task.task_config.update_config_key("depends_on", ["bad_task"])
        expect(pdp.validate()).to(be_false)

    def test_pdp_validate_raises_on_cycle(self, pdp):
        task1 = pdp.create_task("hello")
        task1.task_config.update_config_key("depends_on", ["world"])

        task2 = pdp.create_task("world")
        task2.task_config.update_config_key("depends_on", ["hello"])

        expect(pdp.validate()).to(be_false)


class TestScaffoldTask:
    def test_pdp_create_task(self, pdp):
        pdp.create_task("hello")

        expect(pdp.config.tasks).to(equal(["hello"]))

        hello_path = Path("hello")
        hello_path_input = hello_path / "input"
        hello_path_output = hello_path / "output"
        hello_path_src = hello_path / "src"
        hello_path_task_config = hello_path / "task.yml"

        expect(hello_path_input.exists()).to(be_true)
        expect(hello_path_output.exists()).to(be_true)
        expect(hello_path_src.exists()).to(be_true)
        expect(hello_path_task_config.exists()).to(be_true)

    def test_pdp_create_task_idempotent(self, pdp):
        pdp.create_task("hello")
        pdp.create_task("hello")
        expect(pdp.config.tasks).to(equal(["hello"]))

    def test_pdp_scaffold(self, hello_world_tasks, pdp):
        pdp.scaffold()

        hello_path = Path("hello")
        hello_path_input = hello_path / "input"
        hello_path_output = hello_path / "output"

        expect(hello_path_input.exists()).to(be_true)
        expect(hello_path_output.exists()).to(be_true)

        world_path = Path("world")
        world_path_input = world_path / "input"
        world_path_output = world_path / "output"

        expect(world_path_input.exists()).to(be_true)
        expect(world_path_output.exists()).to(be_true)

    def test_pdp_creates_task_from_root(self, pdp):
        pdp.create_task_from_current_location("hello")
        expect(pdp.config.tasks).to(equal(["hello"]))

        hello_path = Path("hello")
        hello_path_input = hello_path / "input"
        hello_path_output = hello_path / "output"

        expect(hello_path_input.exists()).to(be_true)
        expect(hello_path_output.exists()).to(be_true)

    def test_pdp_create_task_from_inside_task_throws_error(
        self, hello_world_tasks, pdp
    ):
        pdp.scaffold()

        os.chdir("hello")

        with pytest.raises(
            ValueError, match="tasks can only be created at the project root"
        ):
            pdp.create_task_from_current_location("foo")

        expect(pdp.config.tasks).to(equal(["hello", "world"]))
        expect(Path("/hello/foo").exists()).to(be_false)

    def test_pdp_task_tree_is_flat_numbered_list(self, hello_world_tasks, pdp):
        """Will revisit hierarchical tasks later"""
        tree = pdp.task_tree()

        expect(tree.label).to(equal("1. test"))
        expect([child.label for child in tree.children]).to(
            equal(["2. hello", "3. world"])
        )
        expect([child.children for child in tree.children]).to(equal([[], []]))

    def test_pdp_task_tree_shows_dependencies(self, pdp):
        pdp.create_task("hello")
        world = pdp.create_task("world")
        world.task_config.update_config_key("depends_on", ["hello"])

        tree = pdp.task_tree()

        expect([child.label for child in tree.children]).to(
            equal(["2. hello", "3. world [dim] <- hello[/dim]"])
        )

    def test_pdp_create_task_from_current_location_raises_if_not_in_task(self, fs):
        pdp = PDP()
        pdp.initialize()

        Path("/not_a_task").mkdir(parents=True, exist_ok=True)
        os.chdir("/not_a_task")

        with pytest.raises(
            ValueError, match="tasks can only be created at the project root"
        ):
            pdp.create_task_from_current_location("foo")

    def test_pdp_detects_current_directory(self, hello_world_tasks, pdp):
        pdp.scaffold()

        expect(pdp.current_path).to(equal(Path(".")))

        os.chdir("hello")

        expect(pdp.current_path).to(equal(Path("hello")))

    def test_pdp_detects_current_task(self, hello_world_tasks, pdp):
        pdp.scaffold()

        expect(pdp.current_task).to(be_none)

        os.chdir("hello")

        expect(pdp.current_task.task_name).to(equal("hello"))

        os.mkdir("dummy")

        os.chdir("dummy")

        expect(pdp.current_task).to(be_none)

    def test_pdp_picks_up_name_from_config(self, pdp):
        pdp.scaffold()

        pdp2 = PDP()
        pdp2.initialize()

        expect(pdp2.project_name).to(equal("test"))


class TestFlattenTasks:
    def test_flatten_tasks_creates_dict(self, hello_world_tasks, pdp):
        flattened = pdp.flatten_tasks()

        expect(isinstance(flattened, dict))
        expect(set(flattened.keys())).to(equal({"hello", "world"}))
        expect(flattened["hello"]).to(be_a(Task))


class TestRun:
    def test_pdp_runs_task_by_name(self, pdp):
        task = pdp.create_task("hello")
        task.task_config.update_config_key("entrypoint", "make")

        mock_result = subprocess.CompletedProcess(
            args=["make"], returncode=0, stdout="hello\n"
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            return_code = pdp.run_task("hello")
            mock_run.assert_called_once_with(
                "make", cwd=task.task_directory, shell=True, check=False, env=ANY
            )
            expect(return_code.exit_code).to(equal(0))

    def test_pdp_raises_error_if_task_not_found(self, pdp):
        pdp.create_task("hello")

        with pytest.raises(ValueError) as excinfo:
            pdp.run_task("world")

        expect(str(excinfo.value)).to(equal("Task world not found"))

    def test_pdp_runs_all_tasks(self, make_task, pdp):
        pdp.scaffold()

        pdp.run_all()

        make_task.run.assert_called_once()

    def test_pdp_run_all_raises_for_cycle(self, pdp):
        task1 = pdp.create_task("hello")
        task1.task_config.update_config_key("depends_on", ["world"])

        task2 = pdp.create_task("world")
        task2.task_config.update_config_key("depends_on", ["hello"])

        with pytest.raises(InvalidConfigError):
            pdp.run_all()

    def test_pdp_run_task_raises_for_cycle(self, pdp):
        task1 = pdp.create_task("hello")
        task1.task_config.update_config_key("depends_on", ["world"])

        task2 = pdp.create_task("world")
        task2.task_config.update_config_key("depends_on", ["hello"])

        with pytest.raises(InvalidConfigError):
            pdp.run_task("hello")

    def test_pdp_run_task_runs_dependency_closure_and_nothing_else(self, pdp):
        """import <- clean <- report, plus unrelated. Running clean runs import then
        clean: not its dependent (report), not the unrelated task."""
        for name in ("import", "clean", "report", "unrelated"):
            pdp.create_task(name)
        write_task_yml("/import", entrypoint="echo import")
        write_task_yml("/clean", entrypoint="echo clean", depends_on=["import"])
        write_task_yml("/report", entrypoint="echo report", depends_on=["clean"])
        write_task_yml("/unrelated", entrypoint="echo unrelated")

        ok = subprocess.CompletedProcess(args=[], returncode=0)

        with patch("subprocess.run", return_value=ok) as mock_run:
            return_code = pdp.run_task("clean")

        expect([c.args[0] for c in mock_run.call_args_list]).to(
            equal(["echo import", "echo clean"])
        )
        expect(return_code.exit_code).to(equal(0))


class TestSymlinks:
    def test_scaffold_symlinks_dependency_output_into_input(
        self, import_and_clean_project
    ):
        import_and_clean_project.scaffold()

        link = Path("clean/input/import")
        expect(link.is_symlink()).to(be_true)
        expect(link.resolve()).to(equal(Path("import/output").resolve()))

    def test_scaffold_symlink_target_is_relative(self, import_and_clean_project):
        import_and_clean_project.scaffold()

        expect(os.readlink("clean/input/import")).to(equal("../../import/output"))

    def test_symlink_still_resolves_after_project_is_moved(
        self, import_and_clean_project, tmp_path
    ):
        import_and_clean_project.scaffold()
        (tmp_path / "import/output/data.csv").write_text("x")

        moved = tmp_path.parent / f"{tmp_path.name}-moved"
        tmp_path.rename(moved)

        expect((moved / "clean/input/import/data.csv").read_text()).to(equal("x"))

    def test_scaffold_symlink_resolves_when_dependency_output_missing(self, real_pdp):
        real_pdp.create_task("clean")
        real_pdp.create_task("import")
        write_task_yml("clean", depends_on=["import"])
        Path("import/output").rmdir()

        real_pdp.scaffold()

        expect(Path("clean/input/import").resolve().is_dir()).to(be_true)

    def test_scaffold_twice_keeps_one_working_symlink(self, import_and_clean_project):
        import_and_clean_project.scaffold()
        import_and_clean_project.scaffold()

        expect(os.listdir("clean/input")).to(equal(["import"]))
        expect(Path("clean/input/import").resolve()).to(
            equal(Path("import/output").resolve())
        )

    def test_rescaffold_prunes_link_for_removed_dependency(
        self, import_and_clean_project
    ):
        import_and_clean_project.scaffold()
        write_task_yml("clean", depends_on=[])

        import_and_clean_project.scaffold()

        expect(os.path.lexists("clean/input/import")).to(be_false)

    def test_rescaffold_never_removes_hand_made_file_in_input(
        self, import_and_clean_project
    ):
        write_task_yml("clean", depends_on=[])
        Path("clean/input/import").write_text("mine")
        Path("clean/input/notes.csv").write_text("mine")

        import_and_clean_project.scaffold()

        expect(Path("clean/input/import").read_text()).to(equal("mine"))
        expect(Path("clean/input/notes.csv").read_text()).to(equal("mine"))

    def test_rescaffold_never_removes_symlink_pointing_outside_project(
        self, import_and_clean_project, tmp_path_factory
    ):
        outside = tmp_path_factory.mktemp("elsewhere")
        write_task_yml("clean", depends_on=[])
        Path("clean/input/import").symlink_to(outside)

        import_and_clean_project.scaffold()

        expect(Path("clean/input/import").resolve()).to(equal(outside.resolve()))

    def test_real_directory_at_dependency_link_path_fails_validation(
        self, import_and_clean_project
    ):
        Path("clean/input/import").mkdir()

        errors = import_and_clean_project.validation_errors()

        expect(errors).to(contain(contain("input/import")))

    def test_symlink_failure_warns_and_scaffold_completes(
        self, import_and_clean_project, refuse_symlinks
    ):

        with pytest.warns(UserWarning, match="input/import"):
            import_and_clean_project.scaffold()

        expect(Path("clean/output").is_dir()).to(be_true)

    def test_pdp_run_task_creates_symlinks_before_entrypoint(
        self, import_and_clean_project
    ):
        write_task_yml("import", entrypoint="touch output/data.csv")
        write_task_yml(
            "clean",
            entrypoint="test -f input/import/data.csv",
            depends_on=["import"],
        )

        expect(import_and_clean_project.run_task("clean").exit_code).to(equal(0))


class TestDependencyEnvPaths:
    def test_run_sets_dep_env_var_to_output_path(self, import_and_clean_project):
        """Entrypoint should read input variable from env"""

        write_task_yml("import", entrypoint="touch output/data.csv")
        write_task_yml(
            "clean",
            entrypoint='echo "$PDP_INPUT_IMPORT" > output/env.txt',
            depends_on=["import"],
        )

        import_and_clean_project.run_task("clean")

        expect(Path("clean/output/env.txt").read_text().strip()).to(
            equal(str(Path("import/output").resolve()))
        )

    def test_run_sets_no_dep_env_vars_without_deps(self, real_pdp):
        real_pdp.create_task("task1")
        write_task_yml(
            "task1", entrypoint="env | grep ^PDP_INPUT_ > output/env.txt; true"
        )

        real_pdp.run_task("task1")

        expect(Path("task1/output/env.txt").read_text()).to(equal(""))

    def test_run_task_keeps_inherited_env(self, real_pdp, monkeypatch):
        monkeypatch.setenv("PDP_TEST_VAR", "kept")
        real_pdp.create_task("task")
        write_task_yml("task", entrypoint='echo "$PDP_TEST_VAR" > output/env.txt')

        real_pdp.run_task("task")

        expect(Path("task/output/env.txt").read_text().strip()).to(equal("kept"))

    def test_run_task_uses_dep_data_via_env_when_symlink_fails(
        self, import_and_clean_project, refuse_symlinks
    ):
        """Windows/Slurm case: symlink fails, but task should still work"""

        write_task_yml("import", entrypoint="echo hello > output/data.csv")
        write_task_yml(
            "clean",
            entrypoint='cat "$PDP_INPUT_IMPORT/data.csv" > output/copy.csv',
            depends_on=["import"],
        )

        with pytest.warns(UserWarning, match="input/import"):
            return_code = import_and_clean_project.run_task("clean")

        expect(os.path.lexists("clean/input/import")).to(be_false)
        expect(return_code.exit_code).to(equal(0))
        expect(Path("clean/output/copy.csv").read_text()).to(equal("hello\n"))

    def test_run_env_var_name_replaces_dash_with_underscore(self, real_pdp):
        real_pdp.create_task("clean-data")
        real_pdp.create_task("report")
        write_task_yml("clean-data", entrypoint="touch output/data.csv")
        write_task_yml(
            "report",
            entrypoint='echo "$PDP_INPUT_CLEAN_DATA" > output/env.txt',
            depends_on=["clean-data"],
        )

        real_pdp.run_task("report")

        expect(Path("report/output/env.txt").read_text().strip()).to(
            equal(str(Path("clean-data/output").resolve()))
        )


class TestTaskNames:
    @pytest.mark.parametrize(
        "task_name",
        [
            "clean__data",
            "clean--data",
            "clean-_data",
            "_clean",
            "clean_",
            "-clean",
            "clean-",
            "clean.v2",
            "clean/p1",
            "",
        ],
    )
    def test_pdp_create_task_rejects_invalid_task_name(self, pdp, task_name):
        with pytest.raises(ValueError, match="invalid task name"):
            pdp.create_task(task_name)

        expect(pdp.config.tasks).to(equal([]))
        if task_name:
            expect(Path(task_name).exists()).to(be_false)

    @pytest.mark.parametrize(
        "task_name",
        [
            "import",
            "clean_data",
            "clean-data",
            "Clean",
            "CleanData2",
            "2026",
            "task-clean-v2_3",
        ],
    )
    def test_pdp_create_task_accepts_valid_task_name(self, pdp, task_name):
        pdp.create_task(task_name)

        expect(pdp.config.tasks).to(equal([task_name]))


class TestRunFailureHandling:
    def test_failed_task_skips_direct_dependents(self, import_and_clean_project):
        write_task_yml("import", entrypoint="exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        import_and_clean_project.run_all()

        expect(Path("clean/output/ran").exists()).to(be_false)

    def test_failed_task_skips_dependents_of_dependents(self, import_and_clean_project):
        import_and_clean_project.create_task("report")
        write_task_yml("import", entrypoint="exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])
        write_task_yml("report", entrypoint="touch output/ran", depends_on=["clean"])

        import_and_clean_project.run_all()

        expect(Path("report/output/ran").exists()).to(be_false)

    def test_unaffected_tasks_still_run_after_failure(self, import_and_clean_project):
        import_and_clean_project.create_task("other")
        write_task_yml("import", entrypoint="exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])
        write_task_yml("other", entrypoint="touch output/ran")

        import_and_clean_project.run_all()

        expect(Path("other/output/ran").exists()).to(be_true)

    def test_run_report_logs_failed_and_skipped(self, import_and_clean_project):
        import_and_clean_project.create_task("report")
        write_task_yml("import", entrypoint="exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])
        write_task_yml("report", entrypoint="touch output/ran", depends_on=["clean"])

        result = import_and_clean_project.run_all()

        expect(result.failed).to(equal(["import"]))
        expect(result.skipped).to(equal(["clean", "report"]))
        expect(result.exit_code).to(equal(1))

    def test_dependents_still_run_after_symlink_failure(
        self, import_and_clean_project, refuse_symlinks
    ):
        write_task_yml("import", entrypoint="touch output/data.csv")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        with pytest.warns(UserWarning, match="input/import"):
            result = import_and_clean_project.run_all()

        # refuse_symlinks in fixture makes symlink break
        expect(os.path.lexists("clean/input/import")).to(be_false)

        expect(Path("clean/output/ran").exists()).to(be_true)
        expect(result.failed).to(equal([]))
        expect(result.skipped).to(equal([]))


class TestIncompleteTasks:
    def test_task_without_entrypoint_throws_error(self, real_pdp):
        real_pdp.create_task("task1")

        result = real_pdp.run_all()

        expect(result.no_entrypoint).to(equal(["task1"]))
        expect(result.exit_code).to(equal(1))

    def test_task_without_entrypoint_skips_downstream_tasks(
        self, import_and_clean_project
    ):
        import_and_clean_project.create_task("report")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])
        write_task_yml("report", entrypoint="touch output/ran", depends_on=["clean"])

        result = import_and_clean_project.run_all()

        expect(result.skipped).to(equal(["clean", "report"]))
        expect(Path("clean/output/ran").exists()).to(be_false)
        expect(Path("report/output/ran").exists()).to(be_false)

    def test_unrelated_tasks_run_after_task_without_entrypoint(
        self, import_and_clean_project
    ):
        import_and_clean_project.create_task("other")
        write_task_yml("other", entrypoint="touch output/ran")

        import_and_clean_project.run_all()

        expect(Path("other/output/ran").exists()).to(be_true)


class TestFailureCleanup:
    def test_failed_run_removes_only_its_files(self, real_pdp):
        task = real_pdp.create_task("task1")
        for name in ("old.csv", "changed.csv"):
            (task.output_folder / name).write_text("good")
            os.utime(task.output_folder / name, (1000, 1000))
        (task.src_folder / "script.py").write_text("")
        write_task_yml(
            "task1",
            entrypoint="echo partial > output/new.csv;"
            "echo partial > output/changed.csv; exit 1",
        )

        real_pdp.run_task("task1")

        expect(sorted(os.listdir(task.output_folder))).to(equal(["old.csv"]))
        expect(task.is_stale).to(be_true)


class TestForceRun:
    def _fresh_task(self, real_pdp):
        task = real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="touch output/ran")
        backdate_task_yml(task)
        (task.output_folder / "result.csv").write_text("done")
        expect(task.is_stale).to(be_false)
        return task

    def test_run_skips_fresh_task_without_force(self, real_pdp):
        task = self._fresh_task(real_pdp)
        real_pdp.run_task("task1")

        expect((task.output_folder / "ran").exists()).to(be_false)

    def test_run_force_runs_fresh_task(self, real_pdp):
        task = self._fresh_task(real_pdp)
        real_pdp.run_task("task1", force=True)

        expect((task.output_folder / "ran").exists()).to(be_true)


class TestTaskDepValidation:
    def test_task_dep_without_entrypoint_is_valid(self, import_and_clean_project):
        expect(import_and_clean_project.validation_errors()).to(equal([]))


class TestRunReport:
    def test_run_report_has_current_and_entrypointless_tasks(self, real_pdp):
        fresh = real_pdp.create_task("fresh_task")
        write_task_yml("fresh_task", entrypoint="touch output/ran")
        backdate_task_yml(fresh)
        (fresh.output_folder / "result.csv").write_text("done")
        real_pdp.create_task("hand_only_task")

        result = real_pdp.run_all()

        expect(result.current).to(equal(["fresh_task"]))
        expect(result.no_entrypoint).to(equal(["hand_only_task"]))
        expect(result.exit_code).to(equal(1))

    def test_run_report_includes_success_without_output(self, real_pdp):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="true")

        result = real_pdp.run_all()

        expect(result.no_output).to(equal(["task1"]))
        expect(result.exit_code).to(equal(0))

    def test_run_report_lists_tasks_run(self, import_and_clean_project):
        write_task_yml("import", entrypoint="touch output/data.csv")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        result = import_and_clean_project.run_all()

        expect(result.ran).to(equal(["import", "clean"]))
