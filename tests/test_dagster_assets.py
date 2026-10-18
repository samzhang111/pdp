from pathlib import Path

import dagster as dg
import pytest
from expects import *

from pdp.dagster_assets import (
    PdpResource,
    build_assets,
    build_definitions,
    output_data_version,
    reconcile,
)
from pdp.pdp_errors import InvalidConfigError
from tests.helpers import backdate_task_yml, write_task_yml


def materialize(pdp, force=False, instance=None) -> dg.ExecuteInProcessResult:
    return dg.materialize(
        build_assets(pdp),
        resources={
            "pdp": PdpResource(force=force),
            "pipes": dg.PipesSubprocessClient(),
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


def make_current(pdp, task_id, depends_on=()):
    """Valid task with entrypoint task that is current"""
    task = pdp.create_task(task_id)
    write_task_yml(task_id, entrypoint="touch output/ran", depends_on=depends_on)
    backdate_task_yml(task)
    (task.output_folder / "result.csv").write_text("done")
    expect(task.is_stale).to(be_false)
    return task


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
