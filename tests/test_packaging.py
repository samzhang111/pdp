import subprocess
import sys

from expects import equal
from expects.factory import expect


def test_cli_does_not_depend_on_dagster():
    code = "import sys, pdp.cli; assert 'dagster' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code], check=False)
    expect(result.returncode).to(equal(0))
