#!/usr/bin/env python3
"""Unit tests for player-mode registration helpers."""

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

import utils  # noqa: E402


def _make_event(seats=17, inf=6, veh=2, heli=1, max_veh=2, max_heli=1):
    veh_slots = max_veh * veh
    heli_slots = max_heli * heli
    return {
        "max_player_slots": seats,
        "infantry_squad_size": inf,
        "vehicle_squad_size": veh,
        "heli_squad_size": heli,
        "max_vehicle_squads": max_veh,
        "max_heli_squads": max_heli,
        "squads": {},
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
    }


class CapacityTest(unittest.TestCase):
    def test_infantry_cap_from_remaining_seats(self):
        # 17 - 4 (veh) - 1 (heli) = 12 / 6 = 2 infantry squads
        event = _make_event()
        self.assertEqual(utils._max_squads_for_type(event, "infantry"), 2)

    def test_vehicle_and_heli_caps_direct(self):
        event = _make_event()
        self.assertEqual(utils._max_squads_for_type(event, "vehicle"), 2)
        self.assertEqual(utils._max_squads_for_type(event, "heli"), 1)

    def test_infantry_cap_with_no_remainder(self):
        # 12 seats, 2 veh × 2 = 4, 0 heli. Remaining = 8 → 8/6 = 1 infantry squad
        event = _make_event(seats=12, max_veh=2, max_heli=0, heli=1)
        self.assertEqual(utils._max_squads_for_type(event, "infantry"), 1)


class RegisterTest(unittest.TestCase):
    def test_first_infantry_creates_squad(self):
        event = _make_event()
        ua = {}
        name, status = utils._player_register(event, ua, "u1", "Alice", "infantry")
        self.assertEqual(status, "registered")
        self.assertEqual(name, "Infantry 1")
        self.assertEqual(event["squads"]["Infantry 1"]["members"], [{"user_id": "u1", "name": "Alice"}])
        self.assertEqual(ua, {"u1": ["Infantry 1"]})

    def test_second_infantry_joins_same_squad_until_full(self):
        event = _make_event()
        ua = {}
        for i in range(6):
            utils._player_register(event, ua, f"u{i}", f"Alice{i}", "infantry")
        self.assertEqual(list(event["squads"].keys()), ["Infantry 1"])
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 6)

    def test_seventh_infantry_opens_second_squad(self):
        event = _make_event()
        ua = {}
        for i in range(7):
            utils._player_register(event, ua, f"u{i}", f"Alice{i}", "infantry")
        self.assertEqual(list(event["squads"].keys()), ["Infantry 1", "Infantry 2"])
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 6)
        self.assertEqual(len(event["squads"]["Infantry 2"]["members"]), 1)

    def test_already_registered_rejected(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry")
        name, status = utils._player_register(event, ua, "u1", "Alice", "infantry")
        self.assertEqual(status, "already_registered")
        self.assertIsNone(name)

    def test_waitlist_when_infantry_cap_exceeded(self):
        # 2 infantry squads × 6 = 12 seats. 13th player → waitlist.
        event = _make_event()
        ua = {}
        for i in range(12):
            utils._player_register(event, ua, f"u{i}", f"Alice{i}", "infantry")
        name, status = utils._player_register(event, ua, "u13", "Overflow", "infantry")
        self.assertEqual(status, "waitlisted")
        self.assertIsNone(name)
        self.assertEqual(len(event["infantry_waitlist"]), 1)

    def test_vehicle_cap(self):
        # 2 vehicle squads × 2 seats = 4 seats. 5th → waitlist.
        event = _make_event()
        ua = {}
        for i in range(4):
            utils._player_register(event, ua, f"u{i}", f"Driver{i}", "vehicle")
        name, status = utils._player_register(event, ua, "u5", "Extra", "vehicle")
        self.assertEqual(status, "waitlisted")

    def test_invalid_type(self):
        event = _make_event()
        name, status = utils._player_register(event, {}, "u1", "Alice", "bogus")
        self.assertEqual(status, "invalid_type")


class UnregisterAndCompactTest(unittest.TestCase):
    def test_unregister_basic(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry")
        ok, squad, promoted = utils._player_unregister(event, ua, "u1")
        self.assertTrue(ok)
        self.assertEqual(squad, "Infantry 1")
        self.assertEqual(promoted, [])
        # Squad should be gone (trailing empty squad)
        self.assertNotIn("Infantry 1", event["squads"])
        self.assertEqual(ua, {})

    def test_unregister_not_found(self):
        event = _make_event()
        ok, squad, promoted = utils._player_unregister(event, {}, "u1")
        self.assertFalse(ok)
        self.assertEqual(promoted, [])

    def test_compact_shifts_last_member_up(self):
        event = _make_event()
        ua = {}
        # Register 7 players → Squad 1 (6 full) + Squad 2 (1)
        for i in range(7):
            utils._player_register(event, ua, f"u{i}", f"Alice{i}", "infantry")
        # Unregister u0 (first in Squad 1) — expect u6 (the one in Squad 2) to shift up
        utils._player_unregister(event, ua, "u0")
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 6)
        member_ids = [m["user_id"] for m in event["squads"]["Infantry 1"]["members"]]
        self.assertIn("u6", member_ids)
        # Squad 2 is now empty → dropped
        self.assertNotIn("Infantry 2", event["squads"])
        self.assertEqual(ua["u6"], ["Infantry 1"])

    def test_compact_with_multiple_trailing_partials(self):
        event = _make_event()
        ua = {}
        # Register 13 players → Squad 1 (6), Squad 2 (6), waitlist (u12).
        for i in range(13):
            utils._player_register(event, ua, f"u{i}", f"Alice{i}", "infantry")
        utils._player_unregister(event, ua, "u0")
        # After unregister: compact fills Squad 1 from Squad 2, then waitlist
        # promotes u12 into Squad 2. End state: both full, waitlist empty.
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 6)
        self.assertEqual(len(event["squads"]["Infantry 2"]["members"]), 6)
        self.assertEqual(len(event["infantry_waitlist"]), 0)
        self.assertIn("u12", ua)

    def test_waitlist_promotion_on_unregister(self):
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 registered + 1 on waitlist
            utils._player_register(event, ua, f"u{i}", f"Alice{i}", "infantry")
        self.assertEqual(len(event["infantry_waitlist"]), 1)
        utils._player_unregister(event, ua, "u0")
        self.assertEqual(len(event["infantry_waitlist"]), 0)
        # u12 is now registered
        self.assertIn("u12", ua)

    def test_unregister_returns_promoted_list_for_dm_notifications(self):
        """After an unregister triggers a waitlist promotion, the caller must
        receive (uid, name, squad_name) tuples so it can DM those users."""
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 registered + 1 waitlisted (u12)
            utils._player_register(event, ua, f"u{i}", f"Player{i}", "infantry")

        ok, squad_name, promoted = utils._player_unregister(event, ua, "u0")
        self.assertTrue(ok)
        self.assertEqual(len(promoted), 1)
        uid, name, squad = promoted[0]
        self.assertEqual(uid, "u12")
        self.assertEqual(name, "Player12")
        self.assertIn(squad, ("Infantry 1", "Infantry 2"))

    def test_unregister_no_promoted_when_waitlist_empty(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry")
        ok, squad_name, promoted = utils._player_unregister(event, ua, "u1")
        self.assertTrue(ok)
        self.assertEqual(promoted, [])

    def test_remove_from_waitlist_finds_and_removes(self):
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 registered + 1 waitlisted (u12)
            utils._player_register(event, ua, f"u{i}", f"Player{i}", "infantry")
        self.assertEqual(len(event["infantry_waitlist"]), 1)
        wl_type = utils._player_remove_from_waitlist(event, "u12")
        self.assertEqual(wl_type, "infantry")
        self.assertEqual(event["infantry_waitlist"], [])

    def test_remove_from_waitlist_missing_returns_none(self):
        event = _make_event()
        self.assertIsNone(utils._player_remove_from_waitlist(event, "nobody"))

    def test_waitlist_no_duplicate_when_capacity_exhausts_mid_promote(self):
        """Regression: when promoting from the waitlist, an entry that can't be
        placed (because capacity fills mid-promote) must NOT be duplicated."""
        # Heli: 1 squad, size 1. Max players per type = 1.
        event = _make_event(seats=1, max_veh=0, max_heli=1, heli=1, veh=2, inf=6)
        ua = {}
        utils._player_register(event, ua, "p1", "Alpha", "heli")
        utils._player_register(event, ua, "p2", "Bravo", "heli")
        utils._player_register(event, ua, "p3", "Charlie", "heli")
        self.assertEqual(len(event["heli_waitlist"]), 2)

        utils._player_unregister(event, ua, "p1")

        # After promote: p2 got placed, p3 still on waitlist — exactly once.
        self.assertEqual(len(event["squads"]), 1)
        self.assertEqual(event["squads"]["Heli 1"]["members"][0]["user_id"], "p2")
        self.assertEqual(len(event["heli_waitlist"]), 1)
        self.assertEqual(event["heli_waitlist"][0][3], "p3")

    def test_waitlist_promotion_survives_json_roundtrip(self):
        """Regression: waitlist entries come back as lists (not tuples) after JSON
        round-trip. _promote_player_waitlist used to drain the list without
        promoting anyone because of an `isinstance(entry, tuple)` check.
        """
        import json
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 registered + 1 waitlisted
            utils._player_register(event, ua, f"u{i}", f"Alice{i}", "infantry")
        self.assertEqual(len(event["infantry_waitlist"]), 1)

        # Simulate the DB save/load cycle — tuples become lists through JSON.
        event = json.loads(json.dumps(event))
        ua = json.loads(json.dumps(ua))
        self.assertIsInstance(event["infantry_waitlist"][0], list)

        utils._player_unregister(event, ua, "u0")

        self.assertEqual(len(event["infantry_waitlist"]), 0)
        self.assertIn("u12", ua)
        self.assertEqual(len(event["squads"]["Infantry 2"]["members"]), 6)


class SelfUnregisterTest(unittest.TestCase):
    """Self-service player removal must work for waitlisted players too, not
    only for players holding a squad seat (admin-only fallback was the bug)."""

    def test_self_unregister_removes_squad_member(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry")
        status, name, promoted = utils._player_self_unregister(event, ua, "u1")
        self.assertEqual(status, "squad")
        self.assertEqual(name, "Infantry 1")
        self.assertEqual(promoted, [])
        self.assertNotIn("Infantry 1", event["squads"])
        self.assertEqual(ua, {})

    def test_self_unregister_removes_waitlisted_player(self):
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 seated + u12 waitlisted
            utils._player_register(event, ua, f"u{i}", f"Player{i}", "infantry")
        self.assertEqual(len(event["infantry_waitlist"]), 1)

        status, wl_type, promoted = utils._player_self_unregister(event, ua, "u12")

        self.assertEqual(status, "waitlist")
        self.assertEqual(wl_type, "infantry")
        self.assertEqual(promoted, [])
        self.assertEqual(event["infantry_waitlist"], [])

    def test_self_unregister_squad_member_promotes_from_waitlist(self):
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 seated + u12 waitlisted
            utils._player_register(event, ua, f"u{i}", f"Player{i}", "infantry")
        status, name, promoted = utils._player_self_unregister(event, ua, "u0")
        self.assertEqual(status, "squad")
        self.assertEqual(len(event["infantry_waitlist"]), 0)
        self.assertEqual([p[0] for p in promoted], ["u12"])

    def test_self_unregister_unknown_user_returns_none(self):
        event = _make_event()
        status, name, promoted = utils._player_self_unregister(event, {}, "ghost")
        self.assertIsNone(status)
        self.assertIsNone(name)
        self.assertEqual(promoted, [])

    def test_waitlist_type_lookup_is_non_destructive(self):
        event = _make_event()
        ua = {}
        for i in range(13):  # u12 waitlisted on infantry
            utils._player_register(event, ua, f"u{i}", f"Player{i}", "infantry")

        self.assertEqual(utils._player_waitlist_type(event, "u12"), "infantry")
        # Lookup must NOT remove the entry.
        self.assertEqual(len(event["infantry_waitlist"]), 1)
        # A seated player is not "waitlisted".
        self.assertIsNone(utils._player_waitlist_type(event, "u0"))
        self.assertIsNone(utils._player_waitlist_type(event, "ghost"))


class AutoNamingTest(unittest.TestCase):
    def test_name_sequence(self):
        event = _make_event()
        self.assertEqual(utils._next_auto_squad_name(event, "infantry"), "Infantry 1")
        event["squads"]["Infantry 1"] = {"type": "infantry", "members": []}
        self.assertEqual(utils._next_auto_squad_name(event, "infantry"), "Infantry 2")

    def test_per_type_naming(self):
        event = _make_event()
        self.assertEqual(utils._next_auto_squad_name(event, "vehicle"), "Vehicle 1")
        self.assertEqual(utils._next_auto_squad_name(event, "heli"), "Heli 1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
