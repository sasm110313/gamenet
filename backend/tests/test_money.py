from __future__ import annotations

import pytest

from apps.core.money import session_cost


@pytest.mark.parametrize(
    ("rate", "seconds", "expected"),
    [
        (40_000, 0, 0),
        (40_000, 1, 11),          # 11.11 -> 11
        (40_000, 60, 667),        # 666.67 -> 667
        (40_000, 1800, 20_000),   # exactly half an hour
        (40_000, 3600, 40_000),   # exactly one hour
        (40_000, 5400, 60_000),   # 1.5 hours
        (60_000, 3599, 59_983),   # 59_983.33 -> 59_983
        (12_345, 7, 24),          # 24.004... -> 24
        (1, 1800, 1),             # 0.5 -> 1 (half-up)
        (0, 7200, 0),
    ],
)
def test_session_cost_is_integer_half_up(rate: int, seconds: int, expected: int) -> None:
    result = session_cost(rate, seconds)
    assert result == expected
    assert isinstance(result, int)


def test_session_cost_never_uses_floats() -> None:
    # A float implementation drifts here; exact integer arithmetic does not.
    assert session_cost(40_000, 1_000_000) == (40_000 * 1_000_000 + 1800) // 3600


@pytest.mark.parametrize(("rate", "seconds"), [(-1, 60), (40_000, -1)])
def test_session_cost_rejects_negative_inputs(rate: int, seconds: int) -> None:
    with pytest.raises(ValueError):
        session_cost(rate, seconds)


def test_default_business_values() -> None:
    from django.conf import settings

    assert settings.DEFAULT_HOURLY_RATE == 40_000
    assert settings.DEFAULT_CREDIT_LIMIT == 60_000
