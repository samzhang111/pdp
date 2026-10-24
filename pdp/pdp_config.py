from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from ruamel.yaml import YAML

from .pdp_errors import UninitializedProjectError
from .utils import TASK_NAME_RULE, input_env_var, is_valid_task_name


def requires_initialization(method):
    def wrapper(self, *args, **kwargs):
        if not self.initialized:
            raise UninitializedProjectError("Config not initialized.")
        return method(self, *args, **kwargs)

    return wrapper


def _yaml_type_name(value) -> str:
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def slurm_errors(config: dict) -> list[str]:
    if "slurm" not in config:
        return []

    slurm = config["slurm"]
    if not isinstance(slurm, dict):
        return [
            f"slurm should be a mapping, like 'slurm: {{mem: 4G}}', but got {_yaml_type_name(slurm)}"
        ]

    errors = []
    for key, value in slurm.items():
        if not isinstance(key, str):
            errors.append(f"slurm key {key!r} must be a string")
        elif not isinstance(value, (str, int, float, bool)):
            errors.append(
                f"slurm.{key} must be a string, number or boolean, "
                f"got {_yaml_type_name(value)}"
            )
    return errors


class GenericConfig(ABC):
    def __init__(self, name, path_to_config) -> None:
        self.yaml = YAML()

        self.path_to_config = Path(path_to_config).resolve()
        self.config = self.read_config_file()
        self.name = name or self.config.get("name", None)

    def read_config_file(self):
        try:
            return dict(self.yaml.load(self.path_to_config))
        except (TypeError, FileNotFoundError):
            return {}

    @requires_initialization
    def update_config(self, config):
        """Write new config, overwrites old config"""
        self.yaml.dump(config, self.path_to_config)
        self.config = config

    @requires_initialization
    def update_config_key(self, key, value) -> None:

        self.config[key] = value
        self.update_config(self.config)

    @property
    def initialized(self):
        if not self.path_to_config.exists():
            return False

        return len(self.config) != 0

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name}, {self.path_to_config})"

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def validation_errors(self) -> list[str]:
        """Reasons self.config fails validation. Empty if valid."""

    def validate(self) -> bool:
        return not self.validation_errors()


class PDPConfig(GenericConfig):
    def __init__(self, project_name, path_to_config) -> None:
        super().__init__(project_name, path_to_config)
        self.task_key = "tasks"

    def initialize(self):
        if self.initialized:
            return

        self.yaml.dump({"name": self.name, "tasks": []}, self.path_to_config)

        self.config = self.read_config_file()

    @requires_initialization
    def add_task(self, task_name):
        tasks = self.config[self.task_key]

        if task_name not in tasks:
            tasks.append(task_name)

            self.update_config_key(self.task_key, tasks)

    @property
    def tasks(self):
        return self.config.get(self.task_key, [])

    @property
    def slurm(self) -> dict:
        return self.config.get("slurm", {})

    def validation_errors(self) -> list[str]:
        errors = []

        missing_keys = [key for key in ("tasks", "name") if key not in self.config]
        if missing_keys:
            errors.append(f"Missing key(s) in pdp.yml: {(',').join(missing_keys)}")
        else:
            if not isinstance(self.config["tasks"], list):
                errors.append(
                    f"tasks must be a list, got {_yaml_type_name(self.config['tasks'])}"
                )
            else:
                errors += [
                    f"invalid task name '{task}': must be {TASK_NAME_RULE}"
                    for task in self.config["tasks"]
                    if not is_valid_task_name(task)
                ]

                # Check for name collision of PDP_INPUT_ vars after mutating
                by_env_var: dict[str, list[str]] = {}
                for task in self.config["tasks"]:
                    if is_valid_task_name(task):
                        by_env_var.setdefault(input_env_var(task), []).append(task)
                errors += [
                    f"task names {', '.join(names)} all map to {env_var}"
                    for env_var, names in by_env_var.items()
                    if len(names) > 1
                ]

        errors += slurm_errors(self.config)

        return errors


class TaskConfig(GenericConfig):
    CONFIG_DEFAULTS: ClassVar[dict[str, object]] = {
        "entrypoint": "",
        "depends_on": [],
    }

    def initialize(self) -> None:
        if self.initialized:
            self.config = self.read_config_file()
            return

        self.yaml.dump({"name": self.name, **self.CONFIG_DEFAULTS}, self.path_to_config)

        self.config = self.read_config_file()

    def validation_errors(self) -> list[str]:
        """Error messages from failed self.config validation. Empty if valid."""

        # Validate task yml
        allowed_keys = {"name", *self.CONFIG_DEFAULTS}
        errors = []

        unexpected = set(self.config.keys()) - allowed_keys - {"slurm"}
        missing = allowed_keys - set(self.config.keys())

        if unexpected:
            errors.append(f"Unexpected key(s): {', '.join(sorted(unexpected))}")

        if missing:
            errors.append(f"Missing key(s): {', '.join(sorted(missing))}")

        if not self.config.get("name"):
            errors.append("name must be a non-empty string")

        # Organize all errors for output
        for key, default in self.CONFIG_DEFAULTS.items():
            if key in self.config and not isinstance(self.config[key], type(default)):
                errors.append(
                    f"{key} must be {type(default).__name__}, "
                    f"got {_yaml_type_name(self.config[key])}"
                )

        errors += slurm_errors(self.config)

        return errors

    @property
    @requires_initialization
    def entrypoint(self):
        self.config = self.read_config_file()
        return self.config["entrypoint"]

    @property
    @requires_initialization
    def depends_on(self):
        self.config = self.read_config_file()
        return self.config.get("depends_on", [])

    @property
    @requires_initialization
    def slurm(self) -> dict:
        self.config = self.read_config_file()
        return self.config.get("slurm", {})
