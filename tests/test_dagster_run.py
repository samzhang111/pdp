import json
import os
from dataclasses import asdict
from pathlib import Path

import dagster as dg
import pytest
from expects import *

from pdp.dagster_run import asset_job, run_dagster
from tests.helpers import make_current, write_task_yml


@pytest.fixture(autouse=True)
def default_dagster_home(monkeypatch):
    monkeypatch.delenv("DAGSTER_HOME", raising=False)
    monkeypatch.delenv("PDP_SLURM", raising=False)
    monkeypatch.delenv("PDP_PROJECT_ROOT", raising=False)


@pytest.fixture
def stale_chain(import_and_clean_project):
    write_task_yml("import", entrypoint="touch output/data.csv")
    write_task_yml(
        "clean",
        entrypoint="cp input/import/data.csv output/ran",
        depends_on=["import"],
    )
    return import_and_clean_project


class TestRunDagster:
    def test_stale_chain_runs_in_order_and_writes_last_run(self, stale_chain):
        report = run_dagster(stale_chain, {"import", "clean"})

        expect(report.ran).to(equal(["import", "clean"]))
        expect(report.exit_code).to(equal(0))
        expect(Path("clean/output/ran").exists()).to(be_true)

        last_run = json.loads(Path(".dagster/last-run.json").read_text())
        expect(last_run).to(have_keys(**asdict(report), exit_code=0))
        expect(last_run).to(have_key("finished"))

    def test_current_tasks_are_current_and_force_runs_them(self, real_pdp):
        make_current(real_pdp, "task1")

        expect(run_dagster(real_pdp, {"task1"}).current).to(equal(["task1"]))
        expect(Path("task1/output/ran").exists()).to(be_false)

        expect(run_dagster(real_pdp, {"task1"}, force=True).ran).to(equal(["task1"]))
        expect(Path("task1/output/ran").exists()).to(be_true)

    def test_failed_task_skips_its_dependent(self, import_and_clean_project):
        write_task_yml("import", entrypoint="exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        report = run_dagster(import_and_clean_project, {"import", "clean"})

        expect(report.failed).to(equal(["import"]))
        expect(report.ran).to(equal([]))
        expect(report.skipped).to(equal(["clean"]))
        expect(report.exit_code).to(equal(1))

    def test_task_without_entrypoint_is_no_entrypoint(self, real_pdp):
        real_pdp.create_task("task1")

        report = run_dagster(real_pdp, {"task1"})

        expect(report.no_entrypoint).to(equal(["task1"]))
        expect(report.failed).to(equal([]))
        expect(report.exit_code).to(equal(1))

    def test_success_without_output_is_no_output(self, real_pdp):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="true")

        report = run_dagster(real_pdp, {"task1"})

        expect(report.ran).to(equal(["task1"]))
        expect(report.no_output).to(equal(["task1"]))

    def test_selection_materializes_only_selected_tasks(self, import_and_clean_project):
        write_task_yml("import", entrypoint="touch output/ran")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        report = run_dagster(import_and_clean_project, {"clean"})

        expect(report.ran).to(equal(["clean"]))
        expect(Path("import/output/ran").exists()).to(be_false)
        expect(Path("clean/output/ran").exists()).to(be_true)

    def test_quiet_run_shows_task_output_but_no_dagster_logs_or_warnings(
        self, real_pdp, capfd
    ):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="echo from-task; touch output/ran")

        run_dagster(real_pdp, {"task1"})

        out, err = capfd.readouterr()
        expect(out + err).to(contain("from-task"))
        expect(out + err).not_to(contain("dagster - "))
        expect(out + err).not_to(contain("Warning"))
        expect(out + err).not_to(contain("Telemetry"))

    def test_verbose_run_shows_dagster_logs(self, stale_chain, capfd):
        run_dagster(stale_chain, {"import"}, verbose=True)

        _, err = capfd.readouterr()
        expect(err).to(contain("STEP_WORKER_STARTED"))

    def test_working_directory_is_restored(self, stale_chain):
        os.chdir("clean")

        run_dagster(stale_chain, {"import"})

        expect(Path.cwd()).to(equal(stale_chain.project_root / "clean"))

    def test_slurm_submits_each_stale_task_with_srun(self, stale_chain, slurm_log):
        report = run_dagster(stale_chain, {"import", "clean"}, slurm=True)

        expect(report.ran).to(equal(["import", "clean"]))
        srun_lines = (slurm_log / "srun").read_text().splitlines()
        expect(srun_lines).to(have_len(2))
        expect(srun_lines[0]).to(end_with("pdp.pipes_wrapper import"))
        expect(srun_lines[1]).to(end_with("pdp.pipes_wrapper clean"))

    def test_interrupt_raises_keyboard_interrupt_without_report(
        self, stale_chain, monkeypatch
    ):
        def interrupted(*args, **kwargs):
            raise dg.DagsterExecutionInterruptedError()

        monkeypatch.setattr(dg, "execute_job", interrupted)

        with pytest.raises(KeyboardInterrupt):
            run_dagster(stale_chain, {"import", "clean"})
        expect(Path(".dagster/last-run.json").exists()).to(be_false)

    def test_slurm_job_keeps_max_concurrent(self, stale_chain, monkeypatch):
        monkeypatch.setenv("PDP_MAX_CONCURRENT", "3")
        job = asset_job(str(Path.cwd()), slurm=True)

        resolved = dg.validate_run_config(job, {})
        expect(resolved["execution"]["multiprocess"]["max_concurrent"]).to(equal(3))

    def test_run_is_recorded_in_dagster_home_and_env_restored(self, stale_chain):
        run_dagster(stale_chain, {"import", "clean"})

        expect(os.environ).not_to(have_key("DAGSTER_HOME"))
        expect(os.environ).not_to(have_key("PDP_PROJECT_ROOT"))
        with dg.DagsterInstance.from_config(str(Path.cwd() / ".dagster")) as instance:
            runs = instance.get_runs()
        expect(runs).to(have_len(1))
        expect(runs[0].is_success).to(be_true)
