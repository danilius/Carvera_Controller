from enum import Enum
from carveracontroller.addons.probing.operations.Bore.BoreOperation import BoreOperation

class BoreOperationType(Enum):
    CenterX = BoreOperation("Bore - Center X", True, False, "")
    CenterY = BoreOperation("Bore - Center Y", False, True, "")
    CenterBore = BoreOperation("Bore - Center Bore", True, True, "")
    CenterPocket = BoreOperation("Bore - Center Pocket", True, True, "")