from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from rich.tree import Tree

from .pdp_config import PDPConfig
from .pdp_errors import InvalidConfigError
from .task import Task, latest_mtime_in_dir
from .utils import TASK_NAME_RULE, find_project_root, is_valid_task_name


def _reach(edges: dict[str, list[str]], start: str) -> set[str]:
    """start plus every node reachable from it along edges."""
    touched = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current not in touched:
            touched.add(current)
            stack.extend(edges[current])
    return touched


@dataclass
class RunReport:
    """Results of running each task in scope, if not cleanly exited.

    Failed, skipped, and no entrypoint determine exit code.
    """

    # Independent lists per result category
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    current: list[str] = field(default_factory=list)
    no_entrypoint: list[str] = field(default_factory=list)
    no_output: list[str] = field(default_factory=list)
    # task_id -> output/ files the run created or modified
    written: dict[str, list[str]] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed or self.skipped or self.no_entrypoint else 0


class PDP:
    def __init__(
        self, project_name: str | None = None, config: PDPConfig | None = None
    ) -> None:
        self.project_name: str | None = project_name

        if config:
            self.config = config
        else:
            self.config = PDPConfig(project_name, self.project_root / "pdp.yml")
        self.tasks: list[Task] = []

    def initialize(self) -> None:
        if self.initialized:
            self._validate_or_raise()

        self.config.initialize()
        self.project_name = self.config.name

        for task in self.config.tasks:
            self.create_task(task)

    def validation_errors(self) -> list[str]:
        """Reasons the project fails validation

        Checks pdp.yml, input dir, output dir, adn task.yml for each task.
        Checks that Depends_on references real task, and no dependency cycles.

        Returns:
            A list of strings of error messages. Empty if valid.
        """

        if not self.initialized:
            return ["Project not initialized."]

        errors = [f"pdp.yml: {error}" for error in self.config.validation_errors()]

        # Validate top level tasks. Each recurses through its own subtasks
        for task in self.tasks:
            errors += [
                f"{task.task_id}/task.yml: {error}"
                for error in task.validation_errors()
            ]

        # Flatten tasks to check circular dependencies
        flattened = self.flatten_tasks()

        for task_id, task in flattened.items():
            for dep in task.depends_on:
                if dep not in flattened:
                    errors.append(
                        f"{task_id}/task.yml: depends_on references unknown task '{dep}'"
                    )

        graph = {task_id: task.depends_on for task_id, task in flattened.items()}
        try:
            TopologicalSorter(graph).prepare()
        except CycleError:
            errors.append("depends_on contains a cycle.")

        return errors

    def validate(self) -> bool:
        return not self.validation_errors()

    def create_task(self, task_name: str) -> Task:
        if not is_valid_task_name(task_name):
            raise ValueError(
                f"invalid task name '{task_name}': must be {TASK_NAME_RULE}"
            )

        self.config.add_task(task_name)

        task_directory = self.project_root / task_name

        task = Task(task_name, task_directory)
        task.scaffold()

        self.tasks.append(task)

        return task

    def create_task_from_current_location(self, task_name: str) -> Task | None:
        if self.current_path == Path("."):
            return self.create_task(task_name)

        raise ValueError("tasks can only be created at the project root")

    def scaffold(self) -> None:
        """Set up folders for each task, then set symlinks for outputs"""
        for task in self.tasks:
            task.scaffold()
        task_ids: set[str] = set(self.flatten_tasks())
        for task in self.tasks:
            task.create_symlinks(task_ids)

    def _closure(self, flattened: dict[str, Task], task_id: str) -> set[str]:
        """Return task_id plus every task's task_id that it depends on.

        if project is import -> clean -> analyze, closure is {import, clean, analyze}

        Args:
            flattened: Every task in project
            task_id: Current task to run

        Returns:
            A set of every task_id in scope
        """
        return _reach({tid: t.depends_on for tid, t in flattened.items()}, task_id)

    def _descendants(self, flattened: dict[str, Task], task_id: str) -> set[str]:
        """Return task_id plus every task that depends on it, directly or indirectly"""
        dependents: dict[str, list[str]] = {tid: [] for tid in flattened}
        for tid, task in flattened.items():
            for dep in task.depends_on:
                dependents[dep].append(tid)
        return _reach(dependents, task_id)

    def order(self, flattened: dict[str, Task]) -> list[str]:
        graph = {tid: task.depends_on for tid, task in flattened.items()}
        return list(TopologicalSorter(graph).static_order())

    def select(
        self,
        task_ids: list[str],
        only: bool = False,
        from_: str | None = None,
        to: str | None = None,
    ) -> set[str]:
        """Get set of task_ids to run based on selection flags."""
        self._validate_or_raise()
        flattened = self.flatten_tasks()

        for tid in [*task_ids, from_, to]:
            if tid is not None and tid not in flattened:
                raise ValueError(f"Task {tid} not found")
        if task_ids and (from_ or to):
            raise ValueError("Task IDs can't be combined with --from/--to")
        if only and not task_ids:
            raise ValueError("--only needs a task ID")

        if task_ids:
            if only:
                return set(task_ids)
            return set().union(*(self._closure(flattened, tid) for tid in task_ids))

        selection = set(flattened)
        if from_:
            selection &= self._descendants(flattened, from_)
        if to:
            selection &= self._closure(flattened, to)
        if not selection:
            raise ValueError(f"{to} is not downstream of {from_}")
        return selection

    def stale_upstream(self, selection: set[str]) -> list[str]:
        """Get stale tasks outside the selection that are depended upon"""
        flattened = self.flatten_tasks()
        deps = {dep for tid in selection for dep in flattened[tid].depends_on}
        return [
            tid
            for tid in self.order(flattened)
            if tid in deps - selection and flattened[tid].is_stale
        ]

    def _run_many(
        self, flattened: dict[str, Task], task_ids, force: bool = False
    ) -> RunReport:
        order = [tid for tid in self.order(flattened) if tid in task_ids]

        all_task_ids = set(flattened)

        # Record issues for each task id to RunReport, then continue
        report = RunReport()
        for tid in order:
            task = flattened[tid]
            if any(
                dep in report.failed
                or dep in report.skipped
                or dep in report.no_entrypoint
                for dep in task.depends_on
            ):
                report.skipped.append(tid)
                continue
            if not task.entrypoint:
                report.no_entrypoint.append(tid)
                continue
            if not (force or task.is_stale):
                report.current.append(tid)
                continue
            task.create_symlinks(all_task_ids)
            before = task._output_snapshot()
            if task.run() != 0:
                report.failed.append(tid)
                continue
            report.ran.append(tid)
            if written := task.written_since(before):
                report.written[tid] = written
            if latest_mtime_in_dir(task.output_folder) is None:
                # Empty output = stale task
                report.no_output.append(tid)

        return report

    def _validate_or_raise(self) -> None:
        if not self.validate():
            raise InvalidConfigError("\n".join(self.validation_errors()))

    def run_selection(self, selection: set[str], force: bool = False) -> RunReport:
        self._validate_or_raise()
        return self._run_many(self.flatten_tasks(), selection, force)

    def run_all(self, force: bool = False) -> RunReport:
        return self.run_selection(self.select([]), force)

    def run_task(self, task_id: str, force: bool = False) -> RunReport:
        return self.run_selection(self.select([task_id]), force)

    def _find_task_by_id(self, task_id: str) -> Task | None:
        return self.flatten_tasks().get(task_id)

    def task_tree(self) -> Tree:
        """Flat numbered list of tasks under the project name, with dependencies."""
        tree = Tree(f"1. {self.project_name}")
        for num, task in enumerate(self.tasks, start=2):
            label = f"{num}. {task.task_id}"
            if task.depends_on:
                label += f" [dim] <- {', '.join(task.depends_on)}[/dim]"
            tree.add(label)
        return tree

    def flatten_tasks(self) -> dict[str, Task]:
        """Create dict of tasks. This is where subtask flattening would happen,
        temporarily deferred.

        Returns:
            dict[task_id, Task]: Tasks
        """
        flattened = {t.task_id: t for t in self.tasks}

        return flattened

    @property
    def current_path(self) -> Path:
        return Path.cwd().relative_to(self.project_root)

    @property
    def current_task(self) -> Task | None:
        return self._find_task_by_id(str(self.current_path))

    @property
    def project_root(self) -> Path:
        return find_project_root("pdp.yml")

    @property
    def initialized(self) -> bool:
        return self.config.initialized
