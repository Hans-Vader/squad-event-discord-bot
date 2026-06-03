#!/usr/bin/env python3
"""Unit tests for recurrence helpers: compute_next_occurrence, compute_event_end,
validate_recurrence_fits."""

import os
import sys
import types
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _AttrStub(types.ModuleType):
    def __getattr__(self, name):
        placeholder = type(name, (), {})
        setattr(self, name, placeholder)
        return placeholder


# Prefer the real libraries when installed (dev/CI always has discord.py as a
# hard dependency). Only fall back to a lightweight stub when they are absent, so
# this module never replaces a real `discord` in sys.modules and thereby breaks a
# sibling test that does `import bot` (which needs the real discord.ext.commands).
try:
    import discord  # noqa: F401
except ImportError:
    sys.modules["discord"] = _AttrStub("discord")
try:
    import dotenv  # noqa: F401
except ImportError:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = dotenv_stub

from utils import (  # noqa: E402
    compute_next_occurrence,
    compute_event_start,
    compute_event_end,
    validate_recurrence_fits,
)


class NeverAndMissingTest(unittest.TestCase):
    def test_never_returns_none(self):
        self.assertIsNone(compute_next_occurrence(datetime(2026, 4, 1, 20, 0), {"type": "never"}))

    def test_none_or_empty(self):
        self.assertIsNone(compute_next_occurrence(datetime(2026, 4, 1, 20, 0), None))
        self.assertIsNone(compute_next_occurrence(datetime(2026, 4, 1, 20, 0), {}))


class IntervalTypesTest(unittest.TestCase):
    def test_every_minutes(self):
        cur = datetime(2026, 4, 1, 20, 0)
        now = datetime(2026, 4, 1, 20, 1)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "every_minutes", "interval": 30}, now=now),
            datetime(2026, 4, 1, 20, 30),
        )

    def test_every_hours(self):
        cur = datetime(2026, 4, 1, 20, 0)
        now = datetime(2026, 4, 1, 21, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "every_hours", "interval": 2}, now=now),
            datetime(2026, 4, 1, 22, 0),
        )

    def test_every_days(self):
        cur = datetime(2026, 4, 1, 20, 0)
        now = datetime(2026, 4, 2, 10, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "every_days", "interval": 3}, now=now),
            datetime(2026, 4, 4, 20, 0),
        )

    def test_every_weeks(self):
        cur = datetime(2026, 4, 1, 20, 0)
        now = datetime(2026, 4, 2, 10, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "every_weeks", "interval": 2}, now=now),
            datetime(2026, 4, 15, 20, 0),
        )

    def test_every_month(self):
        cur = datetime(2026, 4, 15, 20, 0)
        now = datetime(2026, 4, 16, 10, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "every_month"}, now=now),
            datetime(2026, 5, 15, 20, 0),
        )

    def test_every_month_end_of_month_cap(self):
        cur = datetime(2026, 1, 31, 20, 0)
        now = datetime(2026, 2, 1, 10, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "every_month"}, now=now),
            datetime(2026, 2, 28, 20, 0),
        )

    def test_interval_invalid_returns_none(self):
        cur = datetime(2026, 4, 1, 20, 0)
        for bad in (0, -1, "3", None):
            rec = {"type": "every_days", "interval": bad}
            self.assertIsNone(compute_next_occurrence(cur, rec, now=cur))


class WeekdayPresetsTest(unittest.TestCase):
    def test_first_weekday_next_month(self):
        # 2026-04-01 is Wednesday. Next month's first Wednesday: 2026-05-06.
        cur = datetime(2026, 4, 1, 20, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "first_weekday"}, now=cur),
            datetime(2026, 5, 6, 20, 0),
        )

    def test_fourth_weekday_next_month(self):
        cur = datetime(2026, 4, 1, 20, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "fourth_weekday"}, now=cur),
            datetime(2026, 5, 27, 20, 0),
        )

    def test_last_weekday_next_month(self):
        # 2026-04-26 is last Sunday of April; next month's last Sun = 2026-05-31.
        cur = datetime(2026, 4, 26, 20, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "last_weekday"}, now=cur),
            datetime(2026, 5, 31, 20, 0),
        )


class SpecificDateTest(unittest.TestCase):
    def test_specific_date_with_time(self):
        cur = datetime(2026, 4, 1, 20, 0)
        rec = {"type": "specific_date", "date": "20.06.2026", "time": "21:30"}
        self.assertEqual(
            compute_next_occurrence(cur, rec, now=cur),
            datetime(2026, 6, 20, 21, 30),
        )

    def test_specific_date_past_returns_none(self):
        # One-shot: if target ≤ current, no more.
        cur = datetime(2026, 4, 1, 20, 0)
        rec = {"type": "specific_date", "date": "01.03.2026", "time": "20:00"}
        self.assertIsNone(compute_next_occurrence(cur, rec, now=cur))

    def test_specific_date_missing_time_uses_current_hhmm(self):
        cur = datetime(2026, 4, 1, 20, 0)
        rec = {"type": "specific_date", "date": "15.04.2026"}
        self.assertEqual(
            compute_next_occurrence(cur, rec, now=cur),
            datetime(2026, 4, 15, 20, 0),
        )


class SpecificWeekdaysTest(unittest.TestCase):
    def test_next_match_strictly_after(self):
        # Apr 1 2026 = Wed. Set = Mon(0), Wed(2), Fri(4). Next match > Wed = Fri.
        cur = datetime(2026, 4, 1, 20, 0)
        rec = {"type": "specific_weekdays", "weekdays": [0, 2, 4]}
        self.assertEqual(
            compute_next_occurrence(cur, rec, now=cur),
            datetime(2026, 4, 3, 20, 0),
        )

    def test_wraps_week(self):
        cur = datetime(2026, 4, 3, 20, 0)  # Fri
        rec = {"type": "specific_weekdays", "weekdays": [0]}  # Mon
        self.assertEqual(
            compute_next_occurrence(cur, rec, now=cur),
            datetime(2026, 4, 6, 20, 0),
        )

    def test_empty_set_none(self):
        cur = datetime(2026, 4, 1, 20, 0)
        rec = {"type": "specific_weekdays", "weekdays": []}
        self.assertIsNone(compute_next_occurrence(cur, rec, now=cur))


class SpecificMonthDaysTest(unittest.TestCase):
    def test_same_month(self):
        cur = datetime(2026, 4, 1, 20, 0)
        rec = {"type": "specific_month_days", "month_days": [1, 15]}
        self.assertEqual(
            compute_next_occurrence(cur, rec, now=cur),
            datetime(2026, 4, 15, 20, 0),
        )

    def test_rolls_to_next_month(self):
        cur = datetime(2026, 4, 28, 20, 0)
        rec = {"type": "specific_month_days", "month_days": [5]}
        self.assertEqual(
            compute_next_occurrence(cur, rec, now=cur),
            datetime(2026, 5, 5, 20, 0),
        )


class CatchUpTest(unittest.TestCase):
    def test_catchup_weekly(self):
        # Bot was down for 5 weeks; weekly rule should return the first future Thursday.
        cur = datetime(2026, 1, 1, 20, 0)  # Thursday
        now = datetime(2026, 2, 10, 12, 0)
        result = compute_next_occurrence(cur, {"type": "every_weeks", "interval": 1}, now=now)
        self.assertIsNotNone(result)
        self.assertGreater(result, now)
        self.assertEqual(result.weekday(), 3)

    def test_catchup_daily(self):
        cur = datetime(2026, 1, 1, 20, 0)
        now = datetime(2026, 1, 10, 12, 0)
        self.assertEqual(
            compute_next_occurrence(cur, {"type": "every_days", "interval": 1}, now=now),
            datetime(2026, 1, 10, 20, 0),
        )


class EventEndTest(unittest.TestCase):
    def test_event_end_default_duration(self):
        event = {"date": "01.04.2026", "time": "20:00"}
        self.assertEqual(compute_event_end(event), datetime(2026, 4, 1, 22, 0))

    def test_event_end_custom_duration(self):
        event = {"date": "01.04.2026", "time": "20:00", "duration_minutes": 90}
        self.assertEqual(compute_event_end(event), datetime(2026, 4, 1, 21, 30))

    def test_event_end_missing_date(self):
        self.assertIsNone(compute_event_end({"time": "20:00"}))

    def test_event_start_matches(self):
        event = {"date": "01.04.2026", "time": "20:00"}
        self.assertEqual(compute_event_start(event), datetime(2026, 4, 1, 20, 0))


class FitValidationTest(unittest.TestCase):
    START = datetime(2026, 4, 1, 20, 0)

    def test_never_always_ok(self):
        end = datetime(2026, 4, 1, 22, 0)
        ok, reason = validate_recurrence_fits(self.START, end, {"type": "never"}, 5)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_hourly_fails_for_2h_event(self):
        end = datetime(2026, 4, 1, 22, 0)
        rec = {"type": "every_hours", "interval": 1}
        ok, reason = validate_recurrence_fits(self.START, end, rec, 5)
        self.assertFalse(ok)
        self.assertEqual(reason, "recurrence.error.next_before_spawn")

    def test_hourly_ok_for_short_event(self):
        end = datetime(2026, 4, 1, 20, 30)  # 30-min event
        rec = {"type": "every_hours", "interval": 1}
        ok, reason = validate_recurrence_fits(self.START, end, rec, 5)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_weekly_always_fits_for_short_event(self):
        end = datetime(2026, 4, 1, 22, 0)
        rec = {"type": "every_weeks", "interval": 1}
        ok, reason = validate_recurrence_fits(self.START, end, rec, 60)
        self.assertTrue(ok)

    def test_specific_date_past_fails(self):
        end = datetime(2026, 4, 1, 22, 0)
        rec = {"type": "specific_date", "date": "01.03.2026", "time": "20:00"}
        ok, reason = validate_recurrence_fits(self.START, end, rec, 5)
        self.assertFalse(ok)
        self.assertEqual(reason, "recurrence.error.no_next")

    def test_spawn_offset_exactly_at_next_fails(self):
        # Every 2h with event duration 1h and spawn offset 60min:
        #   start=20:00, end=21:00, spawn_at=22:00, next=22:00 → not strictly after → fail.
        end = datetime(2026, 4, 1, 21, 0)
        rec = {"type": "every_hours", "interval": 2}
        ok, reason = validate_recurrence_fits(self.START, end, rec, 60)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
