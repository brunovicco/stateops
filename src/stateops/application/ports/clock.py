"""Clock capability."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Provide timezone-aware timestamps without hiding time in domain logic."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""
        ...
