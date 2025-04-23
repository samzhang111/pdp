from pathlib import Path

from pdp import PDP
from pdp_errors import InvalidConfigError
from ruamel.yaml import YAML
from expects import *
import pytest


# Pre-existing task fixture
@pytest.fixture
def hello_world_tasks(fs):
    with open("pdp.yml", "w") as f:
        f.write("tasks:\n  - hello\n  - world\n")

    yield fs


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
def pdp(fs):
    pdp = PDP()
    pdp.initialize()

    yield pdp


def test_pdp_inits_empty_task_list(fs):
    pdp = PDP()
    pdp.initialize()

    with open("pdp.yml") as f:
        expect(f.read().strip()).to(equal("tasks: []"))


def test_pdp_uninitialized_when_config_file_does_not_exist(fs):
    pdp = PDP()

    expect(pdp.initialized).to(be_false)


def test_pdp_uninitialized_when_config_file_empty(fs):
    path = Path("pdp.yml")
    path.touch()

    pdp = PDP()
    expect(pdp.initialized).to(be_false)

    pdp.initialize()

    expect(pdp.initialized).to(be_true)


def test_pdp_init_is_idempotent_on_files(hello_world_tasks):
    pdp = PDP()
    pdp.initialize()

    yaml = YAML()
    config_path = Path("pdp.yml")
    data = dict(yaml.load(config_path))

    expect(data).to(equal({"tasks": ["hello", "world"]}))


def test_pdp_validate_fails_if_config_has_no_tasks(empty_pdp_yaml):
    pdp = PDP()
    expect(pdp.validate()).to(be_false)


def test_pdp_initialize_raises_error_if_invalid_config(yaml_without_tasks):
    pdp = PDP()
    with pytest.raises(InvalidConfigError):
        pdp.initialize()


def test_pdp_create_task(pdp):
    pdp.create_task("hello")

    hello_path = Path("hello")
    hello_path_input = hello_path / "input"
    hello_path_output = hello_path / "output"
    hello_path_src = hello_path / "src"

    expect(hello_path_input.exists()).to(be_true)
    expect(hello_path_output.exists()).to(be_true)
    expect(hello_path_src.exists()).to(be_true)
