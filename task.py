from pathlib import Path


class Task:
    def __init__(self, task_name: str, task_parent: Path):
        self.task_name = task_name
        self.task_parent = task_parent
        self.task_path = task_parent / task_name
        self.input_folder = self.task_path / "input"
        self.output_folder = self.task_path / "output"
        self.src_folder = self.task_path / "src"

    def scaffold(self):
        self.input_folder.mkdir(parents=True, exist_ok=True)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.src_folder.mkdir(parents=True, exist_ok=True)
