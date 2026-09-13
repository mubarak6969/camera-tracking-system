"""Local-calendar-day helpers.

Everything persisted in storage/ is UTC (see storage/db.py), but "today's
total" is a user-facing concept and must follow the user's local calendar
day, not a UTC day - otherwise the total resets at the wrong wall-clock
time for anyone not in UTC+0. Isolated here as a pure function (takes an
explicit `reference` instead of always reading the system clock) so it is
testable across timezones without changing the machine's actual timezone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def local_midnight_utc(reference: Optional[datetime] = None) -> datetime:
    """Returns the UTC instant of local midnight at the start of
    `reference`'s calendar day.

    `reference` may be:
    - omitted (defaults to the current moment in the system's real local
      timezone - what the running app actually uses);
    - naive (assumed to already be local time, like `datetime.now()`); or
    - timezone-aware, in which case its own tzinfo IS treated as "local"
      as-is (not converted to the system's timezone) - this is what makes
      the function testable across timezones without touching the test
      machine's actual system timezone.
    """
    if reference is None:
        local_now = datetime.now().astimezone()
    elif reference.tzinfo is None:
        local_now = reference.astimezone()
    else:
        local_now = reference
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)
