"""BlazeBVD paper reimplementation.

The authors did not release official source code or weights.  This package
implements the equations and the architecture table from the paper/supplement,
while isolating undisclosed choices in :mod:`blazebvd.config`.
"""

from .config import BlazeBVDConfig
from .correction import apply_accessibility_corrections
from .models.pipeline import BlazeBVD, BlazeBVDOutput
from .ste import DeflickerPriors, ScaleTimeEqualization

__all__ = [
    "BlazeBVD",
    "BlazeBVDConfig",
    "BlazeBVDOutput",
    "DeflickerPriors",
    "ScaleTimeEqualization",
    "apply_accessibility_corrections",
]

__version__ = "0.1.0"
