from ruamel.yaml import YAML
from pathlib import Path

from pdp_errors import ProjectUninitializedError


class PDPConfig(object):
    def __init__(self):
        self.yaml = YAML()

        self.config_path = Path("pdp.yml")

    def initialize(self):
        if self.initialized:
            return

        self.config_path.touch()
        self.yaml.dump({"tasks": []}, self.config_path)

    def add_task(self, task_name):
        if not self.initialized:
            raise ProjectUninitializedError("PDP is not initialized")

        data = self.data
        data["tasks"].append(task_name)
        self.yaml.dump(data, self.config_path)

    @property
    def initialized(self):
        if not self.config_path.exists():
            return False

        if len(self.data) == 0:
            return False

        return True

    @property
    def data(self):
        try:
            return dict(self.yaml.load(self.config_path))
        except TypeError:
            return {}
