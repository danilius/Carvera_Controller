from enum import Enum
from carveracontroller.addons.probing.operations.Angle.AngleOperation import AngleOperation

class AngleOperationType(Enum):
    XBelow = AngleOperation("Angle - X Below", True, False,False, "")
    XAbove = AngleOperation("Angle - X Above", True, False,True, "")
    YLeft = AngleOperation("Angle - Y Left", False, True,False, "")
    YRight = AngleOperation("Angle - Y Right", False, True,True, "")
    ArbitraryNegative = AngleOperation("Angle - Arbitrary Negative", True, False,True,"")
    ArbitraryPositive = AngleOperation("Angle - Arbitrary Positive", True, False,False, "")
