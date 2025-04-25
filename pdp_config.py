from ruamel.yaml import YAML
from pathlib import Path
from abc import ABC, abstractmethod

from pdp_errors import UninitializedProjectError


def find_config_path_from_parents(config_name) -> Path:
    current_path = Path.cwd()
    while current_path != current_path.parent:
        config_path = current_path / config_name
        if config_path.exists():
            return config_path
        current_path = current_path.parent

    config_path = current_path / config_name
    if config_path.exists():
        return config_path

    return Path.cwd() / config_name


def requires_initialization(method):
    def wrapper(self, *args, **kwargs):
        if not self.initialized:
            raise UninitializedProjectError("Config not initialized.")
        return method(self, *args, **kwargs)

    return wrapper


class GenericConfig(ABC):
    def __init__(self, task_key, config_path) -> None:
        self.yaml = YAML()

        self.task_key = task_key
        self.config_path = Path(config_path)
        self.config = self.read_config_file()

    def read_config_file(self):
        try:
            return dict(self.yaml.load(self.config_path))
        except (TypeError, FileNotFoundError):
            return {}

    @requires_initialization
    def update_config(self, config):
        self.yaml.dump(config, self.config_path)
        self.config = config

    @requires_initialization
    def update_config_key(self, key, value):

        self.config[key] = value
        self.update_config(self.config)

    @property
    def initialized(self):
        if not self.config_path.exists():
            return False

        if len(self.config) == 0:
            return False

        return True

    @requires_initialization
    def add_task(self, task_name):
        tasks = self.config[self.task_key]

        if task_name not in tasks:
            tasks.append(task_name)

            self.update_config_key(self.task_key, tasks)

    @property
    def tasks(self):
        return self.config.get(self.task_key, [])

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def validate(self):
        pass


class PDPConfig(GenericConfig):
    def __init__(self, config_path=None) -> None:
        if config_path is None:
            config_path = find_config_path_from_parents("pdp.yml")

        super().__init__("tasks", config_path)

    def initialize(self):
        if self.initialized:
            return

        self.yaml.dump({"tasks": []}, self.config_path)

        self.config = self.read_config_file()

    def validate(self):
        if "tasks" not in self.config:
            return False

        if not isinstance(self.config["tasks"], list):
            return False

        return True


class TaskConfig(GenericConfig):
    def __init__(self, task_name, config_path="task.yml") -> None:
        self.task_name = task_name
        super().__init__("subtasks", config_path)

    def initialize(self):
        if self.initialized:
            return

        self.yaml.dump({"entrypoint": "make", "subtasks": []}, self.config_path)

        self.config = self.read_config_file()

    def validate(self):
        if "subtasks" not in self.config or "entrypoint" not in self.config:
            return False

        if not isinstance(self.config["subtasks"], list):
            return False

        return True
