from pathlib import Path

from task import Task
from pdp_config import PDPConfig
from pdp_errors import InvalidConfigError


class PDP(object):
    def __init__(self):
        self.config = PDPConfig()
        self.tasks = []

    def initialize(self):
        if self.config.initialized and not self.validate():
            raise InvalidConfigError("Invalid config file")

        return self.config.initialize()

    def validate(self):
        if not self.config.initialized:
            return False

        if "tasks" not in self.config.data:
            return False

        if not isinstance(self.config.data["tasks"], list):
            return False

        return True

    def create_task(self, task_name: str) -> None:
        self.config.add_task(task_name)

        task = Task(task_name, Path("."))
        task.scaffold()

        self.tasks.append(task)

    @property
    def initialized(self):
        return self.config.initialized
