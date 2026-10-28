import json
import os
from dataclasses import asdict
from pathlib import Path

import dagster as dg
import pytest
from expects import *

from pdp.dagster_run import run_dagster
from tests.helpers import make_current, write_task_yml


class TestRunDagster:
    def test_slurm_run_of_selection_records_and_restores_cwd_and_env(
        self, stale_dag, slurm_log
    ):
        root = stale_dag.project_root
        os.chdir("clean")

        report = run_dagster(stale_dag, {"import", "clean"}, slurm=True)

        expect(report.ran).to(equal(["import", "clean"]))
        expect((root / "report/output/ran").exists()).to(be_false)
        srun_lines = (slurm_log / "srun").read_text().splitlines()
        expect(srun_lines).to(have_len(2))
        expect(srun_lines[0]).to(end_with("pdp.pipes_wrapper import"))
        expect(srun_lines[1]).to(end_with("pdp.pipes_wrapper clean"))

        expect(Path.cwd()).to(equal(root / "clean"))
        for key in ("DAGSTER_HOME", "PDP_PROJECT_ROOT", "PDP_SLURM"):
            expect(os.environ).not_to(have_key(key))

        last_run = json.loads((root / ".dagster/last-run.json").read_text())
        expect(last_run).to(have_keys(**asdict(report), exit_code=0))
        expect(last_run).to(have_key("finished"))
        with dg.DagsterInstance.from_config(str(root / ".dagster")) as instance:
            runs = instance.get_runs()
        expect(runs).to(have_len(1))
        expect(runs[0].is_success).to(be_true)

    def test_report_sorts_each_task_by_outcome(self, real_pdp):
        make_current(real_pdp, "current")
        real_pdp.create_task("no-entry")
        for tid, entrypoint, deps in [
            ("fails", "exit 1", ()),
            ("after", "touch output/ran", ["fails"]),
            ("empty", "true", ()),
        ]:
            real_pdp.create_task(tid)
            write_task_yml(tid, entrypoint=entrypoint, depends_on=deps)

        report = run_dagster(real_pdp, set(real_pdp.flatten_tasks()))

        expect(asdict(report)).to(
            equal(
                {
                    "failed": ["fails"],
                    "skipped": ["after"],
                    "ran": ["empty"],
                    "current": ["current"],
                    "no_entrypoint": ["no-entry"],
                    "no_output": ["empty"],
                }
            )
        )
        expect(report.exit_code).to(equal(1))

    @pytest.mark.parametrize("verbose", [False, True])
    def test_dagster_logs_show_only_when_verbose(self, real_pdp, capfd, verbose):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="echo from-task; touch output/ran")

        run_dagster(real_pdp, {"task1"}, verbose=verbose)

        output = "".join(capfd.readouterr())
        expect(output).to(contain("from-task"))
        expect("STEP_WORKER_STARTED" in output).to(equal(verbose))
        if not verbose:
            expect(output).not_to(contain("dagster - "))
            expect(output).not_to(contain("Warning"))
            expect(output).not_to(contain("Telemetry"))

    def test_interrupt_raises_keyboard_interrupt_without_report(
        self, stale_dag, monkeypatch
    ):
        calls = []

        def interrupted(*args, **kwargs):
            calls.append(kwargs)
            raise dg.DagsterExecutionInterruptedError()

        monkeypatch.setattr(dg, "execute_job", interrupted)

        with pytest.raises(KeyboardInterrupt):
            run_dagster(stale_dag, {"clean"}, force=True)
        expect(Path(".dagster/last-run.json").exists()).to(be_false)
        expect(calls[0]["asset_selection"]).to(equal([dg.AssetKey("clean")]))
        expect(calls[0]["run_config"]["resources"]).to(
            equal({"pdp": {"config": {"force": True}}})
        )
