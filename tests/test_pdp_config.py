from pathlib import Path

import pytest
from expects import *
from ruamel.yaml import YAML

from pdp.pdp_config import PDPConfig, TaskConfig
from pdp.utils import TASK_NAME_RULE


@pytest.fixture
def config(fs):
    config = PDPConfig("test", Path("pdp.yml"))
    yield config


def read_config_file(filename):
    return dict(YAML().load(Path(filename)))


def write_config_file(filename, data):
    YAML().dump(data, Path(filename))


class TestInit:
    def test_config_initialization(self, config, fs):
        expect(config.read_config_file()).to(equal({}))

        config.path_to_config.touch()
        expect(config.read_config_file()).to(equal({}))

        expect(config.initialized).to(be_false)

    def test_config_initialize_creates_file(self, config, fs):
        config.initialize()

        config_dict = read_config_file("pdp.yml")
        expect(config_dict["name"]).to(equal("test"))
        expect(config_dict["tasks"]).to(equal([]))

    def test_task_config_initializes_with_entrypoint(self, fs):
        # TODO: Bring back subtasks
        config = TaskConfig("task1", "task.yml")
        config.initialize()

        config_dict = read_config_file("task.yml")
        expect(config_dict["entrypoint"]).to(equal(""))
        expect(config_dict["depends_on"]).to(equal([]))


def test_config_add_task(config, fs):
    config.initialize()

    config.add_task("hello")
    expect(config.config["tasks"]).to(equal(["hello"]))

    config.add_task("world")
    expect(config.config["tasks"]).to(equal(["hello", "world"]))

    config.add_task("hello")
    expect(config.config["tasks"]).to(equal(["hello", "world"]))

    config_dict = read_config_file("pdp.yml")
    expect(config_dict["tasks"]).to(equal(["hello", "world"]))


class TestValidate:
    def test_config_validate(self, config, fs):
        config.initialize()

        expect(config.validate()).to(be_true)

        config.update_config({"tasks": "hello"})
        expect(config.validate()).to(be_false)

        config.update_config({"no_tasks": 123})
        expect(config.validate()).to(be_false)

    def test_config_validate_flags_bad_task_name(self, fs):
        write_config_file(
            "pdp.yml", {"name": "test", "tasks": ["import", "clean.data"]}
        )

        errors = PDPConfig("test", "pdp.yml").validation_errors()

        expect(errors).to(
            equal([f"invalid task name 'clean.data': must be {TASK_NAME_RULE}"])
        )

    def test_task_config_validation_requires_default_config_keys(self, fs):
        config = TaskConfig("task1", "task.yml")
        config.initialize()

        expect(config.validate()).to(be_true)

        # only subtasks, without entrypoint
        config.update_config({"subtasks": []})
        expect(config.validate()).to(be_false)

        # only entrypoint, without subtasks
        config.update_config({"entrypoint": "make"})
        expect(config.validate()).to(be_false)


def test_task_config_description_is_optional_string(fs):
    base = {"name": "task1", "entrypoint": "", "depends_on": []}
    write_config_file("task.yml", base)
    expect(TaskConfig("task1", "task.yml").validation_errors()).to(equal([]))

    write_config_file("task.yml", {**base, "description": 9999999})
    expect(TaskConfig("task1", "task.yml").validation_errors()).to(
        equal(["description must be str, got int"])
    )


def test_task_config_repr_prints_name_and_path(fs):
    config = TaskConfig("task1", "task.yml")
    expect(str(config)).to(equal("TaskConfig(task1, /task.yml)"))


def test_pdp_config_repr_prints_config_path(config, fs):
    expect(str(config)).to(equal("PDPConfig(test, /pdp.yml)"))


def test_pdp_config_throws_for_colliding_task_names(fs):
    write_config_file(
        "pdp.yml",
        {
            "name": "test",
            "tasks": ["import", "clean-data", "clean_data", "Report", "report"],
        },
    )

    errors = PDPConfig("test", "pdp.yml").validation_errors()

    expect(errors).to(
        equal(
            [
                "task names clean-data, clean_data all map to PDP_INPUT_CLEAN_DATA",
                "task names Report, report all map to PDP_INPUT_REPORT",
            ]
        )
    )


class TestSlurmConfig:
    def test_task_config_without_slurm_is_still_valid(self, fs):
        config = TaskConfig("task1", "task.yml")
        config.initialize()

        expect(read_config_file("task.yml")).not_to(have_key("slurm"))
        expect(config.validate()).to(be_true)

    def test_task_config_takes_slurm_config(self, fs):
        write_config_file(
            "task.yml",
            {
                "name": "task1",
                "entrypoint": "",
                "depends_on": [],
                "slurm": {
                    "time": "02:00:00",
                    "mem": "16G",
                    "cpus-per-task": 4,
                    "ntasks": 1,
                },
            },
        )

        expect(TaskConfig("task1", "task.yml").validation_errors()).to(equal([]))

    def test_pdp_config_accepts_slurm_mappings(self, fs):
        write_config_file(
            "pdp.yml",
            {
                "name": "test",
                "tasks": [],
                "slurm": {"partition": "general", "nodes": 1, "mem": "4G"},
            },
        )

        expect(PDPConfig("test", "pdp.yml").validation_errors()).to(equal([]))

    def test_slurm_config_with_flags_is_rejected(self, fs):
        write_config_file("pdp.yml", {"name": "test", "tasks": [], "slurm": "general"})
        write_config_file(
            "task.yml",
            {
                "name": "task1",
                "entrypoint": "",
                "depends_on": [],
                "slurm": ["--mem=16G"],
            },
        )

        expect(PDPConfig("test", "pdp.yml").validation_errors()).to(
            contain(contain("slurm should be a mapping"), contain("got str"))
        )
        expect(TaskConfig("task1", "task.yml").validation_errors()).to(
            contain(contain("slurm should be a mapping"), contain("got list"))
        )


class TestRunnerConfig:
    @pytest.mark.parametrize(
        "yml, runner", [({}, "pdp"), ({"runner": "dagster"}, "dagster")]
    )
    def test_runner_is_read_from_pdp_yml_and_defaults_to_pdp(self, fs, yml, runner):
        write_config_file("pdp.yml", {"name": "test", "tasks": [], **yml})

        pdp_config = PDPConfig("test", "pdp.yml")

        expect(pdp_config.runner).to(equal(runner))
        expect(pdp_config.validation_errors()).to(equal([]))

    def test_unknown_runner_is_rejected(self, fs):
        write_config_file("pdp.yml", {"name": "test", "tasks": [], "runner": "banana"})

        expect(PDPConfig("test", "pdp.yml").validation_errors()).to(
            equal(["runner must be one of pdp, dagster, got 'banana'"])
        )
