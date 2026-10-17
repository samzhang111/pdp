import os
import subprocess
import sys
from pathlib import Path

from expects import *

from tests.helpers import write_task_yml


def run_wrapper(task_id: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pdp.pipes_wrapper", task_id],
        check=False,
        cwd=Path.cwd(),
    )


class TestPipesWrapper:
    def test_exit_code_matches_entrypoint(self, real_pdp):
        real_pdp.create_task("task1")
        write_task_yml("task1", entrypoint="exit 3")

        result = run_wrapper("task1")

        expect(result.returncode).to(equal(3))

    def test_pipes_create_input_symlinks(self, import_and_clean_project):
        write_task_yml("clean", entrypoint="touch output/ran", depends_on=["import"])

        result = run_wrapper("clean")

        expect(result.returncode).to(equal(0))
        expect(os.path.islink("clean/input/import")).to(be_true)
        expect(Path("clean/output/ran").exists()).to(be_true)
