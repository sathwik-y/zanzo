"""Quiet-hours window shared by the poller and engagement loops.

A quiet window suppresses Instagram activity during the account's local night
so the automation pattern reads as human (real users don't poll/comment at 4am).
Bounds are whole hours [start_hour, end_hour) interpreted in `tz_name`;
start == end disables the window.
"""
from datetime import datetime
from zoneinfo import ZoneInfo


def in_quiet_hours(now_utc: datetime, start_hour: int, end_hour: int, tz_name: str) -> bool:
    if start_hour == end_hour:
        return False
    hour = now_utc.astimezone(ZoneInfo(tz_name)).hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    # Overnight wrap (e.g. 22:00 -> 06:00).
    return hour >= start_hour or hour < end_hour
