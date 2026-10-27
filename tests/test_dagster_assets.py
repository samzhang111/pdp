import subprocess
import sys
from pathlib import Path

import dagster as dg
import pytest
from dagster_pipes import decode_param
from expects import *

from pdp.dagster_assets import (
    PdpResource,
    build_assets,
    build_definitions,
    output_data_version,
    reconcile,
)
from pdp.pdp_errors import InvalidConfigError
from pdp.slurm_client import PdpSlurmClient
from tests.helpers import make_current, write_task_yml


def materialize(
    pdp, force=False, instance=None, pipes=None
) -> dg.ExecuteInProcessResult:
    return dg.materialize(
        build_assets(pdp),
        resources={
            "pdp": PdpResource(force=force),
            "pipes": pipes or dg.PipesSubprocessClient(),
        },
        instance=instance,
        raise_on_error=False,
    )


def materializations(result) -> dict[str, dg.AssetMaterialization]:
    return {
        e.asset_key.to_user_string(): e.materialization
        for e in result.get_asset_materialization_events()
    }


def ran(materialization) -> bool:
    return materialization.metadata["pdp/ran"].value


class TestAssetProperties:
    def test_asset_keys_and_deps_match_tasks(self, import_and_clean_project):
        import_and_clean_project.create_task("clean-data")
        write_task_yml("clean-data", depends_on=["import", "clean"])

        specs = [
            next(iter(asset.specs)) for asset in build_assets(import_and_clean_project)
        ]

        expect(
            {
                spec.key.to_user_string(): sorted(
                    dep.asset_key.to_user_string() for dep in spec.deps
                )
                for spec in specs
            }
        ).to(
            equal(
                {"import": [], "clean": ["import"], "clean-data": ["clean", "import"]}
            )
        )


class TestAssetRuns:
    def test_stale_tasks_run_in_order(self, import_and_clean_project):
        write_task_yml("import", entrypoint="touch output/data.csv")
        write_task_yml(
            "clean",
            entrypoint="cp input/import/data.csv output/ran",
            depends_on=["import"],
        )

        result = materialize(import_and_clean_project)

        expect(result.success).to(be_true)
        expect(Path("clean/output/ran").exists()).to(be_true)
        mats = materializations(result)
        expect(ran(mats["import"])).to(be_true)
        expect(ran(mats["clean"])).to(be_true)

    def test_stale_task_runs_after_a_current_dependent_task(self, real_pdp):
        make_current(real_pdp, "import")
        real_pdp.create_task("clean")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        result = materialize(real_pdp)

        mats = materializations(result)
        expect(ran(mats["import"])).to(be_false)
        expect(ran(mats["clean"])).to(be_true)
        expect(Path("import/output/ran").exists()).to(be_false)
        expect(Path("clean/output/ran").exists()).to(be_true)

    def test_if_all_current_tasks_nothing_runs(self, real_pdp):
        make_current(real_pdp, "import")
        make_current(real_pdp, "clean", depends_on=["import"])

        result = materialize(real_pdp)

        expect(result.success).to(be_true)
        expect({run: ran(mats) for run, mats in materializations(result).items()}).to(
            equal({"import": False, "clean": False})
        )
        expect(Path("import/output/ran").exists()).to(be_false)
        expect(Path("clean/output/ran").exists()).to(be_false)

    def test_force_runs_a_current_task(self, real_pdp):
        make_current(real_pdp, "task1")

        result = materialize(real_pdp, force=True)

        expect(ran(materializations(result)["task1"])).to(be_true)
        expect(Path("task1/output/ran").exists()).to(be_true)

    def test_success_without_output_warns_in_metadata(self, real_pdp):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="true")

        result = materialize(real_pdp)

        expect(result.success).to(be_true)
        mats = materializations(result)
        expect(mats["task1"].metadata["pdp/no_output"].value).to(be_true)


class TestAssetFailures:
    def test_failed_task_skips_dependent_tasks_but_runs_unrelated_tasks(
        self, import_and_clean_project
    ):
        import_and_clean_project.create_task("other")
        write_task_yml("import", entrypoint="exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])
        write_task_yml("other", entrypoint="touch output/ran")

        result = materialize(import_and_clean_project)

        expect(result.success).to(be_false)
        expect(set(materializations(result))).to(equal({"other"}))
        expect(Path("clean/output/ran").exists()).to(be_false)
        expect(Path("other/output/ran").exists()).to(be_true)

    def test_task_without_entrypoint_fails_and_skips_dependent_tasks(
        self, import_and_clean_project
    ):
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        result = materialize(import_and_clean_project)

        expect(result.success).to(be_false)
        expect(materializations(result)).to(equal({}))
        expect(Path("clean/output/ran").exists()).to(be_false)


class TestDataVersion:
    def test_data_version_same_whether_real_run_or_no_run(self, real_pdp):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="echo x > output/a.txt")

        def materialize_and_version(**kwargs):
            mat = materializations(materialize(real_pdp, **kwargs))["task1"]
            return mat.tags["dagster/data_version"]  # ty: ignore[not-subscriptable]

        # First run: stale, so it should run
        # Second run: current, so it should skip
        # Third run: current but force, so it should run
        run_stale = materialize_and_version()
        no_run_current = materialize_and_version()
        force_current = materialize_and_version(force=True)

        # no_run_current should not have changed data version
        expect(no_run_current).to(equal(run_stale))

        # force_current should have different data version
        expect(force_current).not_to(equal(run_stale))


class TestReconcile:
    @pytest.fixture
    def instance(self):
        with dg.instance_for_test() as instance:
            yield instance

    def observations(self, instance, task_id):
        return instance.fetch_observations(dg.AssetKey(task_id), limit=100).records

    def test_current_task_without_dagster_history_gets_an_observation(
        self, real_pdp, instance
    ):
        task = make_current(real_pdp, "task1")

        reconcile(real_pdp, instance)

        records = self.observations(instance, "task1")
        expect(records).to(have_len(1))
        expect(records[0].asset_observation.tags["dagster/data_version"]).to(
            equal(output_data_version(task).value)
        )

    def test_reconciling_twice_without_changes_does_nothing(self, real_pdp, instance):
        make_current(real_pdp, "task1")

        reconcile(real_pdp, instance)
        reconcile(real_pdp, instance)

        expect(self.observations(instance, "task1")).to(have_len(1))

    def test_reconciling_after_materialization_does_nothing(self, real_pdp, instance):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="touch output/ran")
        expect(materialize(real_pdp, instance=instance).success).to(be_true)

        reconcile(real_pdp, instance)

        expect(self.observations(instance, "task1")).to(have_len(0))

    def test_changes_to_output_creates_new_observation(self, real_pdp, instance):
        task = make_current(real_pdp, "task1")
        reconcile(real_pdp, instance)

        (task.output_folder / "result.csv").write_text("changed")
        reconcile(real_pdp, instance)

        expect(self.observations(instance, "task1")).to(have_len(2))

    def test_stale_and_entrypointless_tasks_get_nothing(self, real_pdp, instance):
        real_pdp.create_task("stale")
        write_task_yml("stale", entrypoint="touch output/ran")
        real_pdp.create_task("entrypointless")

        reconcile(real_pdp, instance)

        expect(self.observations(instance, "stale")).to(have_len(0))
        expect(self.observations(instance, "entrypointless")).to(have_len(0))

    def test_current_task_does_not_write_a_materialization(self, real_pdp, instance):
        make_current(real_pdp, "task1")

        reconcile(real_pdp, instance)

        expect(instance.get_latest_materialization_event(dg.AssetKey("task1"))).to(
            be_none
        )


class TestBuildDefinitions:
    def test_invalid_project_raises(self, import_and_clean_project):
        write_task_yml("clean", depends_on=["nope"])

        with pytest.raises(InvalidConfigError):
            build_definitions(Path.cwd())

    @pytest.mark.parametrize("slurm", [False, True])
    def test_pdp_run_job_covers_every_task(self, import_and_clean_project, slurm):
        defs = build_definitions(Path.cwd(), slurm=slurm)

        job = defs.resolve_job_def("pdp_run")
        expect(job.asset_layer.executable_asset_keys).to(
            equal({dg.AssetKey("import"), dg.AssetKey("clean")})
        )

    def max_concurrent(self, defs):
        job = defs.resolve_implicit_global_asset_job_def()
        resolved = dg.validate_run_config(job, {})
        return resolved["execution"]["multiprocess"]["max_concurrent"]

    def test_slurm_uses_client_and_max_concurrency(
        self, import_and_clean_project, monkeypatch
    ):
        monkeypatch.delenv("PDP_MAX_CONCURRENT", raising=False)
        defs = build_definitions(Path.cwd(), slurm=True)

        expect(defs.resources["pipes"]).to(be_a(PdpSlurmClient))  # ty: ignore[not-subscriptable]
        expect(self.max_concurrent(defs)).to(equal(8))

    def test_slurm_reads_env_for_max_concurrent(
        self, import_and_clean_project, monkeypatch
    ):
        monkeypatch.setenv("PDP_MAX_CONCURRENT", "3")
        defs = build_definitions(Path.cwd(), slurm=True)

        expect(self.max_concurrent(defs)).to(equal(3))


class TestSlurmClient:
    @pytest.fixture
    def dagster_home(self, tmp_path_factory, monkeypatch):
        home = tmp_path_factory.mktemp("dagster_home")
        monkeypatch.setenv("DAGSTER_HOME", str(home))
        return home

    @pytest.fixture
    def instance(self):
        with dg.instance_for_test() as instance:
            yield instance

    def srun_line(self, run_id, task_id, flags):
        return " ".join(
            [
                "--export=ALL",
                "--quit-on-interrupt",
                f"--job-name=pdp-{run_id}-{task_id}",
                *flags,
                sys.executable,
                "-m",
                "pdp.pipes_wrapper",
                task_id,
            ]
        )

    def test_stale_chain_runs_through_srun_with_merged_flags(
        self, import_and_clean_project, slurm_log, dagster_home
    ):
        import_and_clean_project.config.update_config_key(
            "slurm", {"partition": "general", "mem": "4G"}
        )
        write_task_yml("import", entrypoint="touch output/data.csv")
        write_task_yml(
            "clean",
            entrypoint="cp input/import/data.csv output/ran",
            depends_on=["import"],
            slurm={"mem": "16G"},
        )

        result = materialize(import_and_clean_project, pipes=PdpSlurmClient())

        expect(result.success).to(be_true)
        expect(Path("clean/output/ran").exists()).to(be_true)
        expect((slurm_log / "srun").read_text().splitlines()).to(
            equal(
                [
                    self.srun_line(
                        result.run_id, "import", ["--mem=4G", "--partition=general"]
                    ),
                    self.srun_line(
                        result.run_id, "clean", ["--mem=16G", "--partition=general"]
                    ),
                ]
            )
        )

    def test_pipes_messages_reach_the_run_logs(
        self, real_pdp, slurm_log, dagster_home, instance
    ):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="touch output/ran")

        result = materialize(real_pdp, instance=instance, pipes=PdpSlurmClient())

        messages = [entry.user_message for entry in instance.all_logs(result.run_id)]
        expect(messages).to(contain(contain("task1 returncode: 0")))

    def test_pipes_files_live_under_dagster_home_and_are_cleaned_up(
        self, real_pdp, slurm_log, dagster_home
    ):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="touch output/ran")

        result = materialize(real_pdp, pipes=PdpSlurmClient())

        pipes_dir = dagster_home / "pipes" / result.run_id / "task1"
        context = decode_param((slurm_log / "pipes_context").read_text().strip())
        messages = decode_param((slurm_log / "pipes_messages").read_text().strip())
        expect(context["path"]).to(equal(str(pipes_dir / "context.json")))
        expect(messages["path"]).to(equal(str(pipes_dir / "messages.jsonl")))
        expect(list(pipes_dir.iterdir())).to(be_empty)

    def test_failed_task_cleans_up_and_skips_dependent_tasks(
        self, import_and_clean_project, slurm_log, dagster_home
    ):
        write_task_yml("import", entrypoint="touch output/partial && exit 1")
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        result = materialize(import_and_clean_project, pipes=PdpSlurmClient())

        expect(result.success).to(be_false)
        expect(materializations(result)).to(equal({}))
        expect(Path("import/output/partial").exists()).to(be_false)
        expect(Path("clean/output/ran").exists()).to(be_false)

    def test_interrupt_cancels_the_slurm_job(
        self, real_pdp, slurm_log, dagster_home, monkeypatch
    ):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="sleep 30")

        # runs can't be terminated from outside, so interrupt have to interrupt srun wait
        original_wait = subprocess.Popen.wait
        interrupted = []

        def interrupt_srun_once(self, timeout=None):
            if self.args[0] == "srun" and not interrupted:
                interrupted.append(True)
                raise dg.DagsterExecutionInterruptedError()
            return original_wait(self, timeout=timeout)

        monkeypatch.setattr(subprocess.Popen, "wait", interrupt_srun_once)

        result = materialize(real_pdp, pipes=PdpSlurmClient())

        expect(result.success).to(be_false)
        expect((slurm_log / "scancel").read_text().splitlines()).to(
            equal([f"--name=pdp-{result.run_id}-task1"])
        )
