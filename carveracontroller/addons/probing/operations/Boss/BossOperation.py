import copy

from carveracontroller.addons.probing.operations.Boss.BossParameterDefinitions import \
    BossParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import \
    SingleAxisProbeParameterDefinitions


class BossOperation(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        return "M462 " + self.config_to_gcode(config)


    def get_missing_config(self, config: dict[str, float]):

        required_definitions = {name: value for name, value in BossParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}

        return super().validate_required(required_definitions, config)
