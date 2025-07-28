from pathlib import Path

from ruamel.yaml import YAML


def read_yaml(filename):
    return dict(YAML().load(Path(filename)))
