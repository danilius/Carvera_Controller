from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
from carveracontroller.addons.probing.operations.Bore.BoreParameterDefinitions import BoreParameterDefinitions


class BoreSettings(BoxLayout):
    config_filename = "bore-probe-settings.json"
    config = {}

    def __init__(self, **kwargs):
        self.config = ConfigUtils.load_config(self.config_filename)
        super(BoreSettings, self).__init__(**kwargs)

    def setting_changed(self, key: str, value: float):
        param = getattr(BoreParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")

        self.config[param.code] = value
        ConfigUtils.save_config(self.config, self.config_filename)

    def get_setting(self, key: str) -> str:
        param = getattr(BoreParameterDefinitions, key, None)
        return str(self.config[param.code] if param.code in self.config else "")

    def get_config(self):
        return self.config;
