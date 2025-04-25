from pathlib import Path

from task import Task
from pdp_config import PDPConfig, TaskConfig
from pdp_errors import InvalidConfigError


class PDP(object):
    def __init__(self, config: PDPConfig) -> None:
        self.config = config
        self.tasks = []

    def initialize(self) -> None:
        if self.initialized and not self.validate():
            raise InvalidConfigError("Invalid config file")

        self.config.initialize()

        for task in self.config.tasks:
            self.create_task(task)

    def validate(self) -> bool:
        if not self.initialized:
            return False

        if not self.config.validate():
            return False

        return True

    def create_task(self, task_name: str) -> None:
        self.config.add_task(task_name)

        task_config = TaskConfig(task_name, config_path=Path(task_name) / "task.yml")
        task = Task(task_name, Path("."), task_config)
        task.scaffold()

        self.tasks.append(task)

    def scaffold(self) -> None:
        for task in self.tasks:
            task.scaffold()

    @property
    def initialized(self) -> bool:
        return self.config.initialized
