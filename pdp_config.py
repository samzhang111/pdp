from pathlib import Path
from abc import ABC, abstractmethod

from ruamel.yaml import YAML

from pdp_errors import UninitializedProjectError


def requires_initialization(method):
    def wrapper(self, *args, **kwargs):
        if not self.initialized:
            raise UninitializedProjectError("Config not initialized.")
        return method(self, *args, **kwargs)

    return wrapper


class GenericConfig(ABC):
    def __init__(self, task_key, path_to_config) -> None:
        self.yaml = YAML()

        self.task_key = task_key
        self.path_to_config = Path(path_to_config).resolve()
        self.config = self.read_config_file()

    def read_config_file(self):
        try:
            return dict(self.yaml.load(self.path_to_config))
        except (TypeError, FileNotFoundError):
            return {}

    @requires_initialization
    def update_config(self, config):
        self.yaml.dump(config, self.path_to_config)
        self.config = config

    @requires_initialization
    def update_config_key(self, key, value):

        self.config[key] = value
        self.update_config(self.config)

    @property
    def initialized(self):
        if not self.path_to_config.exists():
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

    def __repr__(self):
        try:
            return f"{self.__class__.__name__}({self.task_name}, {self.path_to_config})"
        except AttributeError:
            return f"{self.__class__.__name__}({self.path_to_config})"

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def validate(self):
        pass


class PDPConfig(GenericConfig):
    def __init__(self, path_to_config) -> None:
        super().__init__("tasks", path_to_config)

    def initialize(self):
        if self.initialized:
            return

        self.yaml.dump({"tasks": []}, self.path_to_config)

        self.config = self.read_config_file()

    def validate(self):
        if "tasks" not in self.config:
            return False

        if not isinstance(self.config["tasks"], list):
            return False

        return True


class TaskConfig(GenericConfig):
    def __init__(self, task_name, path_to_config) -> None:
        self.task_name = task_name
        super().__init__("subtasks", path_to_config)

    def initialize(self):
        if self.initialized:
            self.config = self.read_config_file()
            return

        self.yaml.dump({"entrypoint": "", "subtasks": []}, self.path_to_config)

        self.config = self.read_config_file()

    def validate(self):
        if "subtasks" not in self.config or "entrypoint" not in self.config:
            return False

        if not isinstance(self.config["subtasks"], list):
            return False

        return True

    @property
    @requires_initialization
    def entrypoint(self):
        self.config = self.read_config_file()
        return self.config["entrypoint"]
