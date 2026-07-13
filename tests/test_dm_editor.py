#!/usr/bin/env python3
"""Unit tests for the view-based DM event editor.

Covers the pure helpers behind the editor — input validation and the
property-change invariants (the logic the old wait_for loop performed inline).
The Discord views themselves are exercised manually; here we lock down the
behaviour that's easy to regress: parsing, the registration-start special
cases (including the bug where the old code crashed on a NameError), the
vehicle/heli disable guard, slot recalculation, and the recurrence-fits check.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import bot  # noqa: E402
from i18n import t, _STRINGS  # noqa: E402

FUTURE_DATE = "31.12.2099"


def _event(**over):
    ev = {
        "name": "Test", "date": FUTURE_DATE, "time": "20:00",
        "server_max_players": 100, "max_caster_slots": 2,
        "max_vehicle_squads": 2, "max_heli_squads": 1,
        "duration_minutes": 120, "spawn_offset_minutes": 5,
        "recurrence": {"type": "never"}, "squads": {},
        "vehicle_waitlist": [], "heli_waitlist": [],
        "registration_open": False, "registration_start_time": None,
    }
    ev.update(over)
    return ev


class TestValidateEditText(unittest.TestCase):
    def test_string_required(self):
        self.assertEqual(bot._validate_edit_text("Cup Night", "string", "en"), ("Cup Night", None))
        v, err = bot._validate_edit_text("   ", "string", "en")
        self.assertIsNone(v)
        self.assertEqual(err, "edit.required")

    def test_string_nullable_clears(self):
        self.assertEqual(bot._validate_edit_text("empty", "string_nullable", "en"), (None, None))
        self.assertEqual(bot._validate_edit_text("leer", "string_nullable", "de"), (None, None))
        self.assertEqual(bot._validate_edit_text("hi", "string_nullable", "en"), ("hi", None))

    def test_date_and_time(self):
        self.assertEqual(bot._validate_edit_text("01.02.2099", "date", "en")[1], None)
        self.assertEqual(bot._validate_edit_text("nope", "date", "en")[1], "edit.invalid_date")
        self.assertEqual(bot._validate_edit_text("9:05", "time", "en"), ("09:05", None))
        self.assertEqual(bot._validate_edit_text("25:00", "time", "en")[1], "edit.invalid_time")

    def test_int_variants(self):
        self.assertEqual(bot._validate_edit_text("5", "int", "en"), (5, None))
        self.assertEqual(bot._validate_edit_text("0", "int", "en")[1], "edit.invalid_integer")
        self.assertEqual(bot._validate_edit_text("0", "int_zero", "en"), (0, None))
        self.assertEqual(bot._validate_edit_text("-1", "int_zero", "en")[1], "edit.invalid_integer")
        self.assertEqual(bot._validate_edit_text("0", "int_nullable", "en"), (None, None))
        self.assertEqual(bot._validate_edit_text("30", "int_nullable", "en"), (30, None))
        self.assertEqual(bot._validate_edit_text("x", "int", "en")[1], "edit.invalid_integer")

    def test_reg_start(self):
        self.assertEqual(bot._validate_edit_text("now", "reg_start", "en"), ("__immediate__", None))
        self.assertEqual(bot._validate_edit_text("sofort", "reg_start", "de"), ("__immediate__", None))
        self.assertEqual(bot._validate_edit_text("empty", "reg_start", "en"), (None, None))
        val, err = bot._validate_edit_text("01.02.2099 18:00", "reg_start", "en")
        self.assertIsNone(err)
        self.assertIsInstance(val, datetime)
        self.assertEqual(bot._validate_edit_text("garbage", "reg_start", "en")[1], "edit.invalid_date")


class TestApplyPropertyChange(unittest.TestCase):
    def test_reg_start_after_event_returns_error_not_crash(self):
        # The old code raised NameError(dm_channel) here; now it's a clean error.
        ev = _event()
        after = datetime(2099, 12, 31, 21, 0)  # after the 20:00 event start
        ok, err = bot._apply_property_change(
            ev, "registration_start_time", "reg_start", None, after, "en")
        self.assertFalse(ok)
        self.assertTrue(err)
        self.assertNotIn("missing", err)
        # Nothing was committed on the failure path.
        self.assertIsNone(ev["registration_start_time"])

    def test_reg_start_immediate(self):
        ev = _event()
        ok, err = bot._apply_property_change(
            ev, "registration_start_time", "reg_start", None, "__immediate__", "en")
        self.assertTrue(ok)
        self.assertTrue(ev["registration_open"])
        self.assertIsNone(ev["registration_start_time"])

    def test_reg_start_future_before_event(self):
        ev = _event()
        future = datetime(2099, 1, 1, 18, 0)  # well before the Dec 31 event
        ok, err = bot._apply_property_change(
            ev, "registration_start_time", "reg_start", None, future, "en")
        self.assertTrue(ok)
        self.assertEqual(ev["registration_start_time"], future)
        self.assertFalse(ev["registration_open"])

    def test_reg_start_past_opens_now(self):
        ev = _event()
        past = datetime(2000, 1, 1, 12, 0)
        ok, err = bot._apply_property_change(
            ev, "registration_start_time", "reg_start", None, past, "en")
        self.assertTrue(ok)
        self.assertTrue(ev["registration_open"])
        self.assertIsNone(ev["registration_start_time"])

    def test_reg_start_clear(self):
        ev = _event(registration_start_time=datetime(2099, 1, 1, 12, 0))
        ok, err = bot._apply_property_change(
            ev, "registration_start_time", "reg_start", None, None, "en")
        self.assertTrue(ok)
        self.assertIsNone(ev["registration_start_time"])

    def test_vehicle_disable_guard_blocks_when_squads_exist(self):
        ev = _event(squads={"s1": {"type": "vehicle"}})
        ok, err = bot._apply_property_change(
            ev, "max_vehicle_squads", "int_zero", None, 0, "en")
        self.assertFalse(ok)
        self.assertTrue(err)
        self.assertEqual(ev["max_vehicle_squads"], 2)  # unchanged

    def test_vehicle_disable_allowed_when_empty(self):
        ev = _event()
        ok, err = bot._apply_property_change(
            ev, "max_vehicle_squads", "int_zero", None, 0, "en")
        self.assertTrue(ok)
        self.assertEqual(ev["max_vehicle_squads"], 0)

    def test_recalc_slots_side_effect(self):
        ev = _event()
        ok, err = bot._apply_property_change(
            ev, "server_max_players", "int", "recalc_slots", 120, "en")
        self.assertTrue(ok)
        self.assertEqual(ev["server_max_players"], 120)
        self.assertEqual(ev["max_player_slots"], 120 - ev["max_caster_slots"])

    def test_recurrence_too_frequent_rejected(self):
        ev = _event()  # 120-min event, 5-min spawn offset
        ok, err = bot._apply_property_change(
            ev, "recurrence", "recurrence", None,
            {"type": "every_minutes", "interval": 1}, "en")
        self.assertFalse(ok)
        self.assertTrue(err)
        self.assertNotIn("missing", err)  # the prefixed key resolves

    def test_recurrence_valid_accepted(self):
        ev = _event()
        ok, err = bot._apply_property_change(
            ev, "recurrence", "recurrence", None,
            {"type": "every_days", "interval": 7}, "en")
        self.assertTrue(ok)
        self.assertEqual(ev["recurrence"], {"type": "every_days", "interval": 7})

    def test_rejected_recurrence_does_not_mutate_event(self):
        # A rejected change must validate before mutating: the invalid value
        # must not be written to the event (the caller relies on this).
        ev = _event()
        original = ev["recurrence"]
        ok, err = bot._apply_property_change(
            ev, "recurrence", "recurrence", None,
            {"type": "every_minutes", "interval": 1}, "en")
        self.assertFalse(ok)
        self.assertTrue(err)
        self.assertEqual(ev["recurrence"], original)


class TestOverviewEmbedFieldLimits(unittest.TestCase):
    """The overview embed must never build a field over Discord's 1024-char cap.

    Regression: a long description (or image URL) overflowed the 'general' field,
    so the refresh dm_msg.edit raised HTTPException, got swallowed, and orphaned
    the session on a view whose timeout never started — a stuck, never-expiring
    dialog.
    """

    def test_long_description_field_within_cap(self):
        ev = _event(description="D" * 1024)  # modal max_length
        embed = bot._build_edit_main_embed(ev, "de")
        for field in embed.fields:
            self.assertLessEqual(len(field.value), 1024, field.name)

    def test_long_image_url_field_within_cap(self):
        ev = _event(embed_image_url="https://example.com/" + "a" * 1024 + ".png")
        embed = bot._build_edit_main_embed(ev, "de")
        for field in embed.fields:
            self.assertLessEqual(len(field.value), 1024, field.name)


class TestStaleSessionSweep(unittest.TestCase):
    """The sweeper must force-close sessions whose view timeout never fired."""

    def setUp(self):
        bot._active_edit_sessions.clear()

    def tearDown(self):
        bot._active_edit_sessions.clear()

    def test_stale_session_closed_fresh_kept(self):
        now = bot.time.monotonic()
        bot._active_edit_sessions[1] = {  # stale: no dm_message → pure pop
            "lang": "de", "dm_message": None, "active_view": None,
            "last_activity": now - bot.SESSION_STALE_AFTER_SECONDS - 1,
        }
        bot._active_edit_sessions[2] = {  # fresh
            "lang": "de", "dm_message": None, "active_view": None,
            "last_activity": now,
        }
        asyncio.run(bot._sweep_stale_sessions())
        self.assertNotIn(1, bot._active_edit_sessions)
        self.assertIn(2, bot._active_edit_sessions)

    def test_stale_session_notify_disables_view_and_posts_notice(self):
        class FakeChannel:
            def __init__(self):
                self.sent = []

            async def send(self, text):
                self.sent.append(text)

        class FakeMessage:
            def __init__(self):
                self.channel = FakeChannel()
                self.edited_view = "unset"

            async def edit(self, *, view):
                self.edited_view = view

        dm = FakeMessage()
        now = bot.time.monotonic()
        bot._active_edit_sessions[1] = {
            "lang": "de", "dm_message": dm, "active_view": None,
            "last_activity": now - bot.SESSION_STALE_AFTER_SECONDS - 1,
        }
        asyncio.run(bot._sweep_stale_sessions())
        self.assertNotIn(1, bot._active_edit_sessions)
        self.assertIsNone(dm.edited_view)  # controls disabled
        self.assertEqual(dm.channel.sent, [t("edit.timeout", "de")])


class TestNewI18nKeys(unittest.TestCase):
    NEW_KEYS = [
        "edit.select_property_v2", "edit.footer_hint_v2", "edit.pick_property",
        "edit.pick_value", "edit.open_input", "edit.input_label", "edit.event_link",
        "edit.updated_inline", "edit.required", "edit.image_send", "edit.image_clear",
        "edit.image_waiting", "edit.recurrence.field.interval", "edit.recurrence.field.date",
        "edit.recurrence.field.weekdays", "edit.recurrence.field.month_days",
    ] + [f"edit.recurrence.opt.{v}" for v, _ in bot._RECURRENCE_OPTIONS]

    def test_all_present_in_both_languages(self):
        for key in self.NEW_KEYS:
            self.assertIn(key, _STRINGS, f"missing key {key}")
            for lang in ("de", "en"):
                self.assertNotIn("missing", t(key, lang))

    def test_recurrence_options_cover_twelve_types(self):
        self.assertEqual(len(bot._RECURRENCE_OPTIONS), 12)
        # Every option id has a label key and resolves with a {day} arg.
        for vid, _spec in bot._RECURRENCE_OPTIONS:
            label = t(f"edit.recurrence.opt.{vid}", "en", day="Friday")
            self.assertTrue(label and "missing" not in label)


if __name__ == "__main__":
    unittest.main()
