"""Money is integer Toman. No floats, ever.

The only rounding policy in the MVP is half-up to the nearest Toman. It lives here
so every price path (edge today, quotes/reports later) uses the same function.
"""

from __future__ import annotations

SECONDS_PER_HOUR = 3600


def session_cost(hourly_rate: int, elapsed_seconds: int) -> int:
    """cost = hourly_rate * elapsed_seconds / 3600, rounded half-up.

    Integer-only: (rate * secs + 1800) // 3600. Negative inputs are a bug, not a
    discount, so they raise instead of silently producing credits.
    """
    if hourly_rate < 0:
        raise ValueError("hourly_rate must be >= 0")
    if elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be >= 0")
    return (hourly_rate * elapsed_seconds + SECONDS_PER_HOUR // 2) // SECONDS_PER_HOUR
