"""Dev entry point: picks the role from GAMENET_ROLE."""

from .base import *  # noqa: F401,F403
from .base import GAMENET_ROLE

if GAMENET_ROLE == "cloud":  # pragma: no cover - selected by env
    from .cloud import *  # noqa: F401,F403
else:
    from .edge import *  # noqa: F401,F403
