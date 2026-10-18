import importlib
import sys

import dagster as dg
import pytest
from expects import *

from tests.helpers import backdate_task_yml, write_task_yml


def import_defs_module(monkeypatch):
    """Remove stored copy of defs, import again fresh so it can be reused"""
    monkeypatch.delitem(sys.modules, "pdp.dagster_defs", raising=False)
    return importlib.import_module("pdp.dagster_defs")


def set_env(monkeypatch, project_root):
    monkeypatch.setenv("PDP_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("DAGSTER_HOME", str(project_root / ".dagster"))
    (project_root / ".dagster").mkdir()


class TestDagsterDefs:
    def test_missing_project_root_throws_error(self, monkeypatch):
        # Remove project root from environment
        monkeypatch.delenv("PDP_PROJECT_ROOT", raising=False)

        with pytest.raises(RuntimeError, match="PDP_PROJECT_ROOT"):
            import_defs_module(monkeypatch)

    def test_defs_load_tasks_from_project_root(
        self, import_and_clean_project, monkeypatch
    ):
        set_env(monkeypatch, import_and_clean_project.project_root)
        defs = import_defs_module(monkeypatch).defs

        expect(set(defs.resolve_all_asset_keys())).to(
            equal({dg.AssetKey("import"), dg.AssetKey("clean")})
        )

    def test_reconciles_when_defs_load_current_tasks(self, real_pdp, monkeypatch):
        task = real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="true")
        backdate_task_yml(task)
        (task.output_folder / "result.csv").write_text("done")
        set_env(monkeypatch, real_pdp.project_root)

        import_defs_module(monkeypatch)

        with dg.DagsterInstance.get() as instance:
            records = instance.fetch_observations(dg.AssetKey("task1"), limit=10)
        expect(records.records).to(have_len(1))
