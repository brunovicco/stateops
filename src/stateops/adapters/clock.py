"""System clock adapter."""

from datetime import UTC, datetime


class SystemClock:
    """Return timezone-aware UTC timestamps."""

    def now(self) -> datetime:
        """Return the current instant in UTC."""
        return datetime.now(UTC)
