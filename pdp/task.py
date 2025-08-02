from pathlib import Path
import subprocess
import time
import re

from rich.tree import Tree

from .pdp_config import TaskConfig


def is_empty(directory):
    return not directory.exists() or not any(directory.iterdir())


class Task:
    def __init__(self, task_name: str, task_directory: str | Path):
        self.task_name = task_name
        self.task_directory = Path(task_directory).resolve()
        self.task_config = TaskConfig(task_name, task_directory / "task.yml")
        self.input_folder = task_directory / "input"
        self.output_folder = task_directory / "output"
        self.src_folder = task_directory / "src"
        self.subtasks = []

    def scaffold(self):
        self.task_directory.mkdir(parents=True, exist_ok=True)

        self.task_config.initialize()

        for subtask in self.task_config.tasks:
            self.create_subtask(subtask)

        if len(self.subtasks) == 0:
            self.input_folder.mkdir(parents=True, exist_ok=True)
            self.output_folder.mkdir(parents=True, exist_ok=True)
            self.src_folder.mkdir(parents=True, exist_ok=True)

    def run(self):
        returncodes = []
        for subtask in self.subtasks:
            returncodes.append(subtask.run())

        if self.entrypoint:
            if self.task_config.uses_slurm:
                result = self._run_slurm_task()
            else:
                result = subprocess.run(self.entrypoint, shell=True, cwd=self.task_directory)
            returncodes.append(result.returncode)

        all_success = all([rc == 0 for rc in returncodes])

        if all_success:
            return 0

        return 1

    def _run_slurm_task(self):
        script_path = self.task_directory / self.task_config.slurm_script
        if not script_path.exists():
            raise FileNotFoundError(f"SLURM script not found: {script_path}")
        
        # Submit job to SLURM
        result = subprocess.run(
            ["sbatch", str(script_path)], 
            cwd=self.task_directory, 
            capture_output=True, 
            text=True
        )
        
        if result.returncode != 0:
            return result
        
        # Extract job ID from sbatch output
        job_id = self._extract_job_id(result.stdout)
        if job_id:
            # Wait for job completion
            return self._wait_for_slurm_job(job_id)
        
        return result

    def _extract_job_id(self, sbatch_output):
        match = re.search(r'Submitted batch job (\d+)', sbatch_output)
        return match.group(1) if match else None

    def _wait_for_slurm_job(self, job_id):
        while True:
            result = subprocess.run(
                ["squeue", "-j", job_id, "-h"], 
                capture_output=True, 
                text=True
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                # Job no longer in queue, check final status
                break
            
            time.sleep(5)  # Check every 5 seconds
        
        # Get job exit status
        result = subprocess.run(
            ["sacct", "-j", job_id, "--format=ExitCode", "-n"], 
            capture_output=True, 
            text=True
        )
        
        if result.returncode == 0:
            exit_code_line = result.stdout.strip().split('\n')[0]
            exit_code = exit_code_line.split(':')[0].strip()
            mock_result = type('MockResult', (), {'returncode': int(exit_code) if exit_code.isdigit() else 1})()
            return mock_result
        
        # If we can't get the exit code, assume failure
        mock_result = type('MockResult', (), {'returncode': 1})()
        return mock_result

    def create_subtask(self, subtask_name: str) -> None:
        self.task_config.add_task(subtask_name)
        subtask_directory = self.task_directory / subtask_name

        subtask = Task(subtask_name, subtask_directory)
        subtask.scaffold()

        if (
            is_empty(self.input_folder)
            and is_empty(self.output_folder)
            and is_empty(self.src_folder)
        ):
            try:
                self.input_folder.rmdir()
            except FileNotFoundError:
                pass

            try:
                self.output_folder.rmdir()
            except FileNotFoundError:
                pass

            try:
                self.src_folder.rmdir()
            except FileNotFoundError:
                pass

        self.subtasks.append(subtask)

        return subtask

    def construct_subtree(self, counter, parent_tree) -> None:
        """Create a tree structure of the tasks and subtasks.
        Subtasks are recursively nested within tasks."""
        num = next(counter)
        node = parent_tree.add(f"{num}. {self.task_name}")
        for task in self.subtasks:
            task.construct_subtree(counter, node)

    def subtree_traversal(self, counter, callback) -> None:
        """Iterate over the tasks and subtasks in a tree structure.
        Subtasks are recursively nested within tasks."""
        num = next(counter)
        callback(num, self)
        for task in self.subtasks:
            task.subtree_traversal(counter, callback)

    @property
    def entrypoint(self) -> str:
        return self.task_config.entrypoint

    def __repr__(self):
        return f"Task({self.task_name}, {self.task_directory})"

    def __eq__(self, other):
        return repr(self) == repr(other)
