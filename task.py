from pathlib import Path
import subprocess

from pdp_config import TaskConfig


class Task:
    def __init__(self, task_name: str, task_parent: Path, task_config: TaskConfig):
        self.task_name = task_name
        self.task_parent = task_parent
        self.task_path = task_parent / task_name
        self.task_config = TaskConfig(task_name, self.task_path / "task.yml")
        self.input_folder = self.task_path / "input"
        self.output_folder = self.task_path / "output"
        self.src_folder = self.task_path / "src"

    def scaffold(self):
        self.input_folder.mkdir(parents=True, exist_ok=True)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.src_folder.mkdir(parents=True, exist_ok=True)

        self.task_config.initialize()

    def run(self):
        result = subprocess.run(self.task_config.entrypoint)
        return result.returncode
