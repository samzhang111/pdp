import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from ruamel.yaml import YAML

from pdp import PDP, PDPConfig
from pdp_errors import InvalidConfigError
from expects import *
import pytest


def read_config_file(filename):
    return dict(YAML().load(Path(filename)))


# Pre-existing task fixture
@pytest.fixture
def hello_world_tasks(fs):
    with open("/pdp.yml", "w") as f:
        f.write("tasks:\n  - hello\n  - world\n")

    Path("/hello").mkdir(parents=True, exist_ok=True)
    Path("/world").mkdir(parents=True, exist_ok=True)

    yield fs


@pytest.fixture
def make_task(pdp):
    task = pdp.create_task("hello")
    task.run = MagicMock()

    with open("/hello/pdp.yml", "w") as f:
        f.write("entrypoint: make\nsubtasks: []")

    yield task


@pytest.fixture
def config(fs):
    config = PDPConfig("test", Path("pdp.yml"))

    yield config


@pytest.fixture
def empty_pdp_yaml(fs):
    path_to_config = Path("pdp.yml")
    path_to_config.touch()

    yield fs


@pytest.fixture
def yaml_without_tasks(fs):
    with open("pdp.yml", "w") as f:
        f.write("hello:\n  - hello\n  - world\n")

    yield fs


@pytest.fixture
def pdp(fs):
    pdp = PDP("test")
    pdp.initialize()

    yield pdp


def test_pdp_uninitialized_when_config_file_does_not_exist(fs):
    pdp = PDP("test")

    expect(pdp.initialized).to(be_false)


def test_pdp_uninitialized_when_config_file_empty(empty_pdp_yaml, fs):
    path = Path("pdp.yml")
    path.touch()

    pdp = PDP("test")
    expect(pdp.initialized).to(be_false)

    pdp.initialize()

    expect(pdp.initialized).to(be_true)


def test_pdp_inits_empty_task_list(fs, pdp):
    config_dict = read_config_file("pdp.yml")
    expect(config_dict["tasks"]).to(equal([]))


def test_pdp_init_is_idempotent_on_files(hello_world_tasks, pdp):
    expect(pdp.config.config).to(equal({"tasks": ["hello", "world"]}))


def test_pdp_validate_fails_if_config_has_no_tasks(empty_pdp_yaml):
    pdp = PDP()
    expect(pdp.validate()).to(be_false)


def test_pdp_initialize_raises_error_if_invalid_config(yaml_without_tasks):
    config = PDPConfig("test", "pdp.yml")
    with pytest.raises(InvalidConfigError):
        pdp = PDP(config=config)
        pdp.initialize()


def test_pdp_create_task(pdp):
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


def test_pdp_create_task_idempotent(pdp):
    pdp.create_task("hello")
    pdp.create_task("hello")
    expect(pdp.config.tasks).to(equal(["hello"]))


def test_pdp_scaffold(hello_world_tasks, pdp):
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


def test_pdp_runs_task_by_name(pdp):
    task = pdp.create_task("hello")
    task.task_config.update_config({"entrypoint": "make"})

    mock_result = subprocess.CompletedProcess(
        args=["make"], returncode=0, stdout="hello\n"
    )

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        return_code = pdp.run_task("hello")
        mock_run.assert_called_once_with("make", cwd=task.task_directory)
        expect(return_code).to(equal(0))


def test_pdp_raises_error_if_task_not_found(pdp):
    pdp.create_task("hello")

    with pytest.raises(ValueError) as excinfo:
        pdp.run_task("world")

    expect(str(excinfo.value)).to(equal("Task world not found"))


def test_pdp_detects_current_directory(hello_world_tasks, pdp):
    pdp.scaffold()

    expect(pdp.current_path).to(equal(Path(".")))

    os.chdir("hello")

    expect(pdp.current_path).to(equal(Path("hello")))


def test_pdp_detects_current_task(hello_world_tasks, pdp):
    pdp.scaffold()

    expect(pdp.current_task).to(equal("."))

    os.chdir("hello")

    expect(pdp.current_task.task_name).to(equal("hello"))

    os.mkdir("dummy")

    os.chdir("dummy")

    expect(pdp.current_task).to(be_none)


def test_pdp_creates_task_from_root(pdp):
    pdp.create_task_from_current_location("hello")
    expect(pdp.config.tasks).to(equal(["hello"]))

    hello_path = Path("hello")
    hello_path_input = hello_path / "input"
    hello_path_output = hello_path / "output"

    expect(hello_path_input.exists()).to(be_true)
    expect(hello_path_output.exists()).to(be_true)


def test_pdp_creates_task_from_current_location(hello_world_tasks, pdp):
    pdp.scaffold()

    os.chdir("hello")

    pdp.create_task_from_current_location("foo")

    expect(pdp.config.tasks).to(equal(["hello", "world"]))

    yaml = YAML()
    task_yaml = dict(yaml.load(Path("/hello/task.yml")))

    expect(task_yaml["name"]).to(equal("hello"))
    expect(task_yaml["entrypoint"]).to(equal(""))
    expect(task_yaml["subtasks"]).to(equal(["foo"]))


def test_pdp_runs_all_tasks(make_task, pdp):
    pdp.scaffold()

    pdp.run_all()

    make_task.run.assert_called_once()


def test_pdp_picks_up_name_from_config(pdp):
    pdp.scaffold()

    pdp2 = PDP()
    pdp2.initialize()

    expect(pdp2.project_name).to(equal("test"))


def test_pdp_task_tree_generates_tree(pdp):
    pdp.scaffold()

    pdp.create_task("hello")
    pdp.create_task("world")

    os.chdir("/hello")
    pdp.create_task_from_current_location("foo")

    os.chdir("/world")
    pdp.create_task_from_current_location("bar")

    tree = pdp.task_tree()

    expect(tree.label).to(equal("1. test"))
    expect(tree.children[0].label).to(equal("2. hello"))
    expect(tree.children[0].children[0].label).to(equal("3. foo"))
    expect(tree.children[1].label).to(equal("4. world"))
    expect(tree.children[1].children[0].label).to(equal("5. bar"))


def test_pdp_create_task_from_current_location_raises_if_not_in_task(fs):
    pdp = PDP()
    pdp.initialize()

    Path("/not_a_task").mkdir(parents=True, exist_ok=True)
    os.chdir("/not_a_task")

    with pytest.raises(ValueError) as excinfo:
        pdp.create_task_from_current_location("foo")
