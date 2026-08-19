#!/usr/bin/env python3
"""Unit tests for player-mode "declined" (Abgemeldet) marks.

A declined player actively signals "I'm not coming". They pick nothing and hold
no seat/waitlist/tentative spot, so entries are minimal ({"user_id","name"}).
The Unregister button toggles the mark when the user has no other status; gaining
any real/tentative status clears it. Declined renders as the very last embed field.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))


class _AttrStub(types.ModuleType):
    def __getattr__(self, name):
        placeholder = type(name, (), {})
        setattr(self, name, placeholder)
        return placeholder


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

import utils  # noqa: E402
from i18n import t  # noqa: E402


def _infantry_squads(seats, inf, veh, heli, max_veh, max_heli):
    """Translate a legacy seat budget into the composition it used to imply, so
    these fixtures keep expressing capacity the way the tests read best."""
    inf_seats = max(0, seats - max_veh * veh - max_heli * heli)
    count = inf_seats // inf if inf else 0
    if count >= 2:
        count -= count % 2
    return [[inf, count]]


def _make_event(inf=6, heli=1, max_heli=1):
    return {
        "name": "Test Event",
        "date": "01.01.2099",
        "time": "20:00",
        "mode": "player",
        "infantry_squads": _infantry_squads(17, inf, 2, heli, 2, max_heli),
        "vehicle_squad_size": 2,
        "heli_squad_size": heli,
        "max_vehicle_squads": 2,
        "max_heli_squads": max_heli,
        "squads": {},
        "casters": {},
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
        "caster_waitlist": [],
        "tentative": [],
        "declined": [],
    }


class AddDeclinedTest(unittest.TestCase):
    def test_add_declined_adds_minimal_entry(self):
        event = _make_event()
        utils._add_declined(event, "u1", "Alice")
        self.assertEqual(event["declined"], [{"user_id": "u1", "name": "Alice"}])

    def test_add_declined_one_entry_per_user(self):
        event = _make_event()
        utils._add_declined(event, "u1", "Alice")
        utils._add_declined(event, "u1", "Alice (renamed)")
        self.assertEqual(len(event["declined"]), 1)
        self.assertEqual(event["declined"][0]["name"], "Alice (renamed)")

    def test_add_declined_creates_list_when_missing(self):
        event = _make_event()
        del event["declined"]
        utils._add_declined(event, "u1", "Alice")
        self.assertEqual(event["declined"], [{"user_id": "u1", "name": "Alice"}])

    def test_add_declined_does_not_touch_squads_slots_or_tentative(self):
        event = _make_event()
        utils._add_tentative(event, "u2", "Bob", "infantry")
        utils._add_declined(event, "u1", "Alice")
        self.assertEqual(event["squads"], {})
        self.assertEqual(event.get("player_slots_used", 0), 0)
        self.assertEqual(len(event["tentative"]), 1)  # Bob's tentative untouched


class RemoveAndLookupDeclinedTest(unittest.TestCase):
    def test_remove_declined_returns_entry_and_empties(self):
        event = _make_event()
        utils._add_declined(event, "u1", "Alice")
        removed = utils._remove_declined(event, "u1")
        self.assertEqual(removed["user_id"], "u1")
        self.assertEqual(event["declined"], [])

    def test_remove_declined_missing_returns_none(self):
        event = _make_event()
        self.assertIsNone(utils._remove_declined(event, "ghost"))

    def test_remove_declined_noop_when_list_missing(self):
        event = _make_event()
        del event["declined"]
        self.assertIsNone(utils._remove_declined(event, "u1"))

    def test_entry_lookup_non_destructive(self):
        event = _make_event()
        utils._add_declined(event, "u1", "Alice")
        self.assertIsNotNone(utils._player_declined_entry(event, "u1"))
        self.assertEqual(len(event["declined"]), 1)
        self.assertIsNone(utils._player_declined_entry(event, "ghost"))


class ClearOnStatusGainTest(unittest.TestCase):
    def test_register_seated_clears_declined(self):
        event = _make_event()
        ua = {}
        utils._add_declined(event, "u1", "Alice")
        _name, status = utils._player_register(event, ua, "u1", "Alice", "infantry")
        self.assertEqual(status, "registered")
        self.assertIsNone(utils._player_declined_entry(event, "u1"))

    def test_register_waitlisted_clears_declined(self):
        # Heli caps at one squad of size 1 → the second heli sign-up waitlists.
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "seat", "Seat", "heli")
        utils._add_declined(event, "u1", "Alice")
        _name, status = utils._player_register(event, ua, "u1", "Alice", "heli")
        self.assertEqual(status, "waitlisted")
        self.assertIsNone(utils._player_declined_entry(event, "u1"))

    def test_going_tentative_clears_declined(self):
        event = _make_event()
        utils._add_declined(event, "u1", "Alice")
        utils._add_tentative(event, "u1", "Alice", "infantry")
        self.assertIsNone(utils._player_declined_entry(event, "u1"))


class DeclinedEmbedTest(unittest.TestCase):
    def _find_field(self, embed, needle):
        for f in embed.fields:
            if needle in f.name:
                return f
        return None

    def test_declined_field_is_last_with_count(self):
        event = _make_event()
        utils._add_declined(event, "u1", "Alice")
        utils._add_declined(event, "u2", "Bob")
        embed = utils.format_event_details(event, "de")
        last = embed.fields[-1]
        self.assertIn(t("embed.declined_label", "de", count=2), last.name)
        self.assertIn("**Alice**", last.value)
        self.assertIn("**Bob**", last.value)

    def test_no_declined_field_when_empty(self):
        event = _make_event()
        embed = utils.format_event_details(event, "de")
        for f in embed.fields:
            self.assertNotIn("Abgemeldet", f.name)

    def test_declined_field_respects_1024_char_cap(self):
        event = _make_event()
        for i in range(60):
            utils._add_declined(event, f"u{i}", "N" * 32)  # worst-case long names
        embed = utils.format_event_details(event, "de")
        field = self._find_field(embed, "Abgemeldet")
        self.assertIsNotNone(field)
        self.assertLessEqual(len(field.value), 1024)
        self.assertIn("weitere", field.value)  # overflow collapsed to "+X weitere"
        # The label count still reflects the true total, not the shown subset.
        self.assertIn("(60)", field.name)


class I18nKeysTest(unittest.TestCase):
    def test_new_keys_present(self):
        for key in ("embed.declined_label", "embed.declined_more",
                    "player.declined_added", "player.declined_removed",
                    "log.player_declined", "log.player_declined_removed"):
            for lang in ("de", "en"):
                self.assertNotIn("missing", t(key, lang), f"{key}/{lang} missing")


if __name__ == "__main__":
    unittest.main()
