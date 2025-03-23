from enum import Enum
from carveracontroller.addons.probing.operations.Boss.BossOperation import BossOperation

class BossOperationType(Enum):
    CenterX = BossOperation("Boss - Center X", True, False, "")
    CenterY = BossOperation("Boss - Center Y", False, True, "")
    CenterBoss = BossOperation("Boss - Center Boss", True, True, "")
    CenterBlock = BossOperation("Boss - Center Block", True, True, "")