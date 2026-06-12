"""Quiet-hours gating shared by the poller and engagement loops."""
from datetime import UTC, datetime

from recall.schedule import in_quiet_hours

TZ = "Asia/Kolkata"  # UTC+5:30


def test_inside_simple_window():
    # 21:30 UTC == 03:00 IST -> inside the 01:00-07:00 quiet window
    now = datetime(2026, 6, 12, 21, 30, tzinfo=UTC)
    assert in_quiet_hours(now, 1, 7, TZ) is True


def test_outside_simple_window():
    # 03:30 UTC == 09:00 IST -> outside 01:00-07:00
    now = datetime(2026, 6, 12, 3, 30, tzinfo=UTC)
    assert in_quiet_hours(now, 1, 7, TZ) is False


def test_equal_bounds_means_no_quiet_hours():
    now = datetime(2026, 6, 12, 21, 30, tzinfo=UTC)
    assert in_quiet_hours(now, 0, 0, TZ) is False


def test_wrap_around_window_inside():
    # 17:30 UTC == 23:00 IST -> inside a 22:00-06:00 overnight window
    now = datetime(2026, 6, 12, 17, 30, tzinfo=UTC)
    assert in_quiet_hours(now, 22, 6, TZ) is True


def test_wrap_around_window_outside():
    # 06:30 UTC == 12:00 IST -> outside a 22:00-06:00 overnight window
    now = datetime(2026, 6, 12, 6, 30, tzinfo=UTC)
    assert in_quiet_hours(now, 22, 6, TZ) is False
