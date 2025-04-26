from pathlib import Path

from task import Task
from pdp_config import PDPConfig, TaskConfig
from pdp_errors import InvalidConfigError


def find_project_root(config_name) -> Path:
    current_path = Path.cwd()
    while current_path != current_path.parent:
        path_to_config = current_path / config_name
        if path_to_config.exists():
            return current_path.resolve()
        current_path = current_path.parent

    path_to_config = current_path / config_name
    if path_to_config.exists():
        return current_path.resolve()

    return Path.cwd().resolve()


class PDP(object):
    def __init__(self, config: PDPConfig | None = None) -> None:
        if config:
            self.config = config
        else:
            self.config = PDPConfig(self.project_root / "pdp.yml")
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

    def create_task(self, task_name: str) -> Task:
        self.config.add_task(task_name)

        task_directory = self.project_root / task_name

        task = Task(task_name, task_directory)
        task.scaffold()

        self.tasks.append(task)

        return task

    def create_task_from_current_location(self, task_name: str) -> None:
        current_task = self.current_task

        if isinstance(current_task, Task):
            current_task.create_subtask(task_name)

        elif current_task == ".":
            self.create_task(task_name)

    def scaffold(self) -> None:
        for task in self.tasks:
            task.scaffold()

    def run_task(self, task_name: str) -> int:
        task = self._find_task_by_name(task_name)
        if task is None:
            raise ValueError(f"Task {task_name} not found")

        return task.run()

    def run_all(self) -> int:
        for task in self.tasks:
            self.run_task(task.task_name)

        return 0

    def _find_task_by_name(self, task_name: str) -> Task | None:
        return next((t for t in self.tasks if t.task_name == task_name), None)

    @property
    def current_path(self) -> Path:
        return Path.cwd().relative_to(self.project_root)

    @property
    def current_task(self) -> Path:
        current_path = str(self.current_path)
        task = self._find_task_by_name(current_path)

        if task:
            return task

        if current_path == ".":
            return "."

        return None

    @property
    def project_root(self) -> Path:
        return find_project_root("pdp.yml")

    @property
    def initialized(self) -> bool:
        return self.config.initialized
