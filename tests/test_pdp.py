from pathlib import Path

from pdp import PDP, PDPConfig
from pdp_errors import InvalidConfigError
from expects import *
import pytest


# Pre-existing task fixture
@pytest.fixture
def hello_world_tasks(fs):
    with open("pdp.yml", "w") as f:
        f.write("tasks:\n  - hello\n  - world\n")

    Path("hello").mkdir(parents=True, exist_ok=True)
    Path("world").mkdir(parents=True, exist_ok=True)

    yield fs


@pytest.fixture
def config(fs):
    config = PDPConfig()

    yield config


@pytest.fixture
def empty_pdp_yaml(fs):
    config_path = Path("pdp.yml")
    config_path.touch()

    yield fs


@pytest.fixture
def yaml_without_tasks(fs):
    with open("pdp.yml", "w") as f:
        f.write("hello:\n  - hello\n  - world\n")

    yield fs


@pytest.fixture
def pdp(config, fs):
    pdp = PDP(config)
    pdp.initialize()

    yield pdp


def test_pdp_uninitialized_when_config_file_does_not_exist(config, fs):
    pdp = PDP(config)

    expect(pdp.initialized).to(be_false)


def test_pdp_uninitialized_when_config_file_empty(empty_pdp_yaml, config, fs):
    path = Path("pdp.yml")
    path.touch()

    pdp = PDP(config)
    expect(pdp.initialized).to(be_false)

    pdp.initialize()

    expect(pdp.initialized).to(be_true)


def test_pdp_inits_empty_task_list(fs, pdp):
    with open("pdp.yml") as f:
        expect(f.read().strip()).to(equal("tasks: []"))


def test_pdp_init_is_idempotent_on_files(hello_world_tasks, pdp):
    expect(pdp.config.config).to(equal({"tasks": ["hello", "world"]}))


def test_pdp_validate_fails_if_config_has_no_tasks(config, empty_pdp_yaml):
    pdp = PDP(config)
    expect(pdp.validate()).to(be_false)


def test_pdp_initialize_raises_error_if_invalid_config(yaml_without_tasks):
    config = PDPConfig()
    with pytest.raises(InvalidConfigError):
        pdp = PDP(config)
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
