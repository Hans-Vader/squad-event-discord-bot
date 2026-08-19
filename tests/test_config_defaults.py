#!/usr/bin/env python3
"""Unit tests for the /config_defaults DM editor.

Covers the guild-defaults property table, _GUILD_TARGET helpers,
_persist_guild_edit (happy path and min-validation), and the event-path
regression (session_target defaults to _EVENT_TARGET, leaving the existing
tests unchanged).
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import database  # noqa: E402
import bot       # noqa: E402
from database import DEFAULT_GUILD_SETTINGS, init_db, save_guild_settings, get_guild_settings
from i18n import t, _STRINGS  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GUILD_ID = 111111


def _run(coro):
    """Drive an async coroutine synchronously in tests."""
    return asyncio.run(coro)


class TestGuildEditPropertiesTable(unittest.TestCase):
    """1. Property-table sanity checks."""

    def test_every_key_in_default_guild_settings(self):
        for num, key, label_key, vtype, special in bot._GUILD_EDIT_PROPERTIES:
            self.assertIn(key, DEFAULT_GUILD_SETTINGS,
                          f"key '{key}' (num={num}) not in DEFAULT_GUILD_SETTINGS")

    def test_label_keys_resolve_de_and_en(self):
        for num, key, label_key, vtype, special in bot._GUILD_EDIT_PROPERTIES:
            for lang in ("de", "en"):
                val = t(label_key, lang)
                self.assertNotIn("missing", val,
                                 f"label key '{label_key}' missing for lang={lang}")

    def test_every_vtype_has_an_editor(self):
        """A vtype with no editor silently falls through to the free-text modal,
        which is exactly what the dropdowns replaced — pin it."""
        handled = set(bot._NUMERIC_PRESETS) | {"bool", "composition"}
        for num, key, label_key, vtype, special in bot._GUILD_EDIT_PROPERTIES:
            self.assertIn(vtype, handled,
                          f"key '{key}' has no editor for vtype '{vtype}'")

    def test_special_all_none(self):
        for num, key, label_key, vtype, special in bot._GUILD_EDIT_PROPERTIES:
            self.assertIsNone(special,
                              f"key '{key}' has non-None special '{special}'")

    def test_nums_one_to_ten(self):
        nums = [p[0] for p in bot._GUILD_EDIT_PROPERTIES]
        self.assertEqual(nums, list(range(1, 11)),
                         "Property numbers must be 1..10 in order")

    def test_exactly_ten_properties(self):
        self.assertEqual(len(bot._GUILD_EDIT_PROPERTIES), 10)


class TestGuildTargetLoad(unittest.TestCase):
    """2. _GUILD_TARGET.load returns defaults-merged dict with formattable values."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmpfile.close()
        database.DB_FILE = self._tmpfile.name
        init_db()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            path = self._tmpfile.name + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_load_returns_default_dict_when_no_settings(self):
        obj = bot._GUILD_TARGET.load(GUILD_ID, 0, None)
        self.assertIsNotNone(obj)
        for key in DEFAULT_GUILD_SETTINGS:
            self.assertIn(key, obj)

    def test_format_property_value_non_not_set_for_each_field(self):
        obj = bot._GUILD_TARGET.load(GUILD_ID, 0, None)
        not_set = t("edit.not_set", "en")
        for num, key, label_key, vtype, special in bot._GUILD_EDIT_PROPERTIES:
            display = bot._format_property_value(obj, key, vtype, "en")
            self.assertNotEqual(display, not_set,
                                f"key '{key}' (vtype={vtype}) formatted as not_set")

    def test_load_returns_saved_settings(self):
        settings = dict(DEFAULT_GUILD_SETTINGS)
        settings["infantry_squads"] = [[6, 10], [8, 4]]
        save_guild_settings(GUILD_ID, settings)
        obj = bot._GUILD_TARGET.load(GUILD_ID, 0, None)
        self.assertEqual(obj["infantry_squads"], [[6, 10], [8, 4]])


class TestPersistGuildEdit(unittest.TestCase):
    """3 + 4. Happy path and min-validation for _persist_guild_edit."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmpfile.close()
        database.DB_FILE = self._tmpfile.name
        init_db()
        # Seed settings so save_guild_settings can UPDATE
        save_guild_settings(GUILD_ID, dict(DEFAULT_GUILD_SETTINGS))

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            path = self._tmpfile.name + suffix
            if os.path.exists(path):
                os.unlink(path)

    def _prop(self, key):
        return next(p for p in bot._GUILD_EDIT_PROPERTIES if p[1] == key)

    def test_happy_path_ok_and_reloads(self):
        prop = self._prop("max_caster_slots")
        # Stub bot.get_guild → None to skip log channel
        with patch.object(bot.bot, "get_guild", return_value=None):
            status, payload = _run(
                bot._persist_guild_edit(GUILD_ID, prop, 5, "en", "tester"))
        self.assertEqual(status, "ok")
        self.assertIsNone(payload)
        reloaded = get_guild_settings(GUILD_ID)
        self.assertEqual(reloaded["max_caster_slots"], 5)

    def test_max_vehicle_squads_zero_succeeds_for_defaults(self):
        """max_vehicle_squads=0 must succeed for guild defaults (no event guard)."""
        prop = self._prop("max_vehicle_squads")
        with patch.object(bot.bot, "get_guild", return_value=None):
            status, payload = _run(
                bot._persist_guild_edit(GUILD_ID, prop, 0, "en", "tester"))
        self.assertEqual(status, "ok")
        reloaded = get_guild_settings(GUILD_ID)
        self.assertEqual(reloaded["max_vehicle_squads"], 0)

    def test_squads_per_user_zero_returns_error(self):
        """A per-user squad limit of 0 would lock everyone out → below min=1."""
        prop = self._prop("max_squads_per_user")
        with patch.object(bot.bot, "get_guild", return_value=None):
            status, payload = _run(
                bot._persist_guild_edit(GUILD_ID, prop, 0, "en", "tester"))
        self.assertEqual(status, "error")
        self.assertIsNotNone(payload)
        # Value must NOT have been saved
        reloaded = get_guild_settings(GUILD_ID)
        self.assertNotEqual(reloaded["max_squads_per_user"], 0)

    def test_negative_int_zero_returns_error(self):
        """int_zero type: negative values are rejected."""
        prop = self._prop("registration_countdown_seconds")
        with patch.object(bot.bot, "get_guild", return_value=None):
            status, payload = _run(
                bot._persist_guild_edit(GUILD_ID, prop, -5, "en", "tester"))
        self.assertEqual(status, "error")
        self.assertIsNotNone(payload)

    def test_bool_prop_persists(self):
        prop = self._prop("caster_registration_enabled")
        with patch.object(bot.bot, "get_guild", return_value=None):
            status, payload = _run(
                bot._persist_guild_edit(GUILD_ID, prop, False, "en", "tester"))
        self.assertEqual(status, "ok")
        reloaded = get_guild_settings(GUILD_ID)
        self.assertFalse(reloaded["caster_registration_enabled"])


class TestEventPathRegression(unittest.TestCase):
    """5. Event-path regression: session_target, _EVENT_TARGET, _EDIT_PROPERTIES."""

    def test_session_target_no_session_returns_event_target(self):
        user_id = 9999999
        # Ensure no session exists for this user
        bot._active_edit_sessions.pop(user_id, None)
        result = bot._session_target(user_id)
        self.assertIs(result, bot._EVENT_TARGET)

    def test_event_target_properties_is_edit_properties(self):
        self.assertIs(bot._EVENT_TARGET.properties(), bot._EDIT_PROPERTIES)

    def test_guild_target_properties_is_guild_edit_properties(self):
        self.assertIs(bot._GUILD_TARGET.properties(), bot._GUILD_EDIT_PROPERTIES)

    def test_session_target_with_guild_session_returns_guild_target(self):
        user_id = 8888888
        bot._active_edit_sessions[user_id] = {
            "guild_id": 1, "channel_id": 1, "db_id": 0,
            "lang": "en", "dm_message": None, "active_view": None,
            "last_activity": 0,
            "target": bot._GUILD_TARGET,
        }
        try:
            result = bot._session_target(user_id)
            self.assertIs(result, bot._GUILD_TARGET)
        finally:
            bot._active_edit_sessions.pop(user_id, None)

    def test_session_target_with_event_session_returns_event_target(self):
        user_id = 7777777
        bot._active_edit_sessions[user_id] = {
            "guild_id": 1, "channel_id": 1, "db_id": 1,
            "lang": "en", "dm_message": None, "active_view": None,
            "last_activity": 0,
            "target": bot._EVENT_TARGET,
        }
        try:
            result = bot._session_target(user_id)
            self.assertIs(result, bot._EVENT_TARGET)
        finally:
            bot._active_edit_sessions.pop(user_id, None)


class TestConfigDefaultsI18nKeys(unittest.TestCase):
    """i18n completeness for all config_defaults.* keys."""

    CONFIG_DEFAULTS_KEYS = [
        "config_defaults.title",
        "config_defaults.intro",
        "config_defaults.footer",
        "config_defaults.finished",
        "config_defaults.channel_link",
        "config_defaults.log_changed",
    ] + [f"config_defaults.prop.{p[1]}" for p in bot._GUILD_EDIT_PROPERTIES]

    def test_all_keys_present_in_both_languages(self):
        for key in self.CONFIG_DEFAULTS_KEYS:
            self.assertIn(key, _STRINGS, f"missing key: {key}")
            for lang in ("de", "en"):
                val = t(key, lang)
                self.assertNotIn("missing", val,
                                 f"key '{key}' missing for lang={lang}")


if __name__ == "__main__":
    unittest.main()
