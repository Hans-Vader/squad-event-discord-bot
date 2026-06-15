#!/usr/bin/env python3
"""Unit tests for cross-squad consolidation (player/individual mode).

`consolidate_all_player_squads` packs partially-filled squads of every type into
the fewest squads, drops emptied squads, and keeps `user_assignments` in sync.
It is triggered automatically when the event starts and manually via the
organizer "consolidate" button.
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


def _m(uid, name, roles=None):
    d = {"user_id": uid, "name": name}
    if roles is not None:
        d["roles"] = roles
    return d


def _event(squads):
    return {
        "mode": "player",
        "squads": squads,
        "infantry_squad_size": 6,
        "vehicle_squad_size": 2,
        "heli_squad_size": 1,
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
    }


def _ua(squads):
    """Derive a user_assignments map from the squad layout."""
    ua = {}
    for name, data in squads.items():
        for m in data["members"]:
            ua.setdefault(m["user_id"], []).append(name)
    return ua


class ConsolidateTest(unittest.TestCase):
    def test_merges_two_partial_infantry_squads(self):
        # Exact mockup scenario: Infantry 1 (3/6) + Infantry 2 (1/6) -> Infantry 1 (4/6).
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("u1", "Starcrafter"), _m("u2", "Simply"), _m("u3", "Zyphix")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [
                _m("u4", "GeneralNiggles")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        removed = utils.consolidate_all_player_squads(event, ua)

        self.assertEqual(removed, 1)
        self.assertNotIn("Infantry 2", event["squads"])
        members = event["squads"]["Infantry 1"]["members"]
        self.assertEqual(len(members), 4)
        self.assertEqual(members[-1]["user_id"], "u4")  # merged member appended last

    def test_user_assignments_updated_for_moved_member(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [_m("u1", "A")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [_m("u2", "B")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        utils.consolidate_all_player_squads(event, ua)

        self.assertEqual(ua["u2"], ["Infantry 1"])
        self.assertEqual(ua["u1"], ["Infantry 1"])

    def test_full_squads_untouched(self):
        full = [_m(f"u{i}", f"P{i}") for i in range(6)]
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": list(full)},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [
                _m(f"v{i}", f"Q{i}") for i in range(6)]},
        }
        event = _event(squads)
        removed = utils.consolidate_all_player_squads(event, _ua(squads))

        self.assertEqual(removed, 0)
        self.assertEqual(len(event["squads"]), 2)

    def test_size_one_heli_squads_untouched(self):
        # Each heli squad is full at size 1; nothing can be pulled.
        squads = {
            "Heli 1": {"type": "heli", "size": 1, "members": [_m("h1", "A")]},
            "Heli 2": {"type": "heli", "size": 1, "members": [_m("h2", "B")]},
        }
        event = _event(squads)
        removed = utils.consolidate_all_player_squads(event, _ua(squads))

        self.assertEqual(removed, 0)
        self.assertEqual(set(event["squads"]), {"Heli 1", "Heli 2"})

    def test_all_types_consolidated_in_one_pass(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("u1", "A"), _m("u2", "B"), _m("u3", "C")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [_m("u4", "D")]},
            "Vehicle 1": {"type": "vehicle", "size": 2, "members": [_m("v1", "E")]},
            "Vehicle 2": {"type": "vehicle", "size": 2, "members": [_m("v2", "F")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        removed = utils.consolidate_all_player_squads(event, ua)

        self.assertEqual(removed, 2)
        self.assertNotIn("Infantry 2", event["squads"])
        self.assertNotIn("Vehicle 2", event["squads"])
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 4)
        self.assertEqual(len(event["squads"]["Vehicle 1"]["members"]), 2)
        self.assertEqual(ua["v2"], ["Vehicle 1"])

    def test_idempotent_second_pass_is_noop(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("u1", "A"), _m("u2", "B"), _m("u3", "C")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [_m("u4", "D")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        first = utils.consolidate_all_player_squads(event, ua)
        snapshot = {n: list(d["members"]) for n, d in event["squads"].items()}
        second = utils.consolidate_all_player_squads(event, ua)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual({n: list(d["members"]) for n, d in event["squads"].items()}, snapshot)

    def test_single_partial_squad_returns_zero(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("u1", "A"), _m("u2", "B"), _m("u3", "C")]},
        }
        event = _event(squads)
        removed = utils.consolidate_all_player_squads(event, _ua(squads))

        self.assertEqual(removed, 0)
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 3)

    def test_consolidation_follows_numeric_order_not_dict_order(self):
        # Squads stored out of numeric order (e.g. a middle squad removed then
        # recreated, appended at the end). Consolidation must still keep the
        # numerically-first squad (Infantry 1), not whatever happens to be first
        # in dict-iteration order.
        squads = {
            "Infantry 3": {"type": "infantry", "size": 6, "members": [_m("u3", "C")]},
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("u1a", "A1"), _m("u1b", "A2"), _m("u1c", "A3")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [_m("u2", "B")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        removed = utils.consolidate_all_player_squads(event, ua)

        # 3 + 1 + 1 = 5 members fit into one squad.
        self.assertEqual(removed, 2)
        self.assertEqual(set(event["squads"]), {"Infantry 1"})
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 5)

    def test_trailing_empty_squad_dropped(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("u1", "A"), _m("u2", "B"), _m("u3", "C")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": []},
        }
        event = _event(squads)
        removed = utils.consolidate_all_player_squads(event, _ua(squads))

        self.assertEqual(removed, 1)
        self.assertNotIn("Infantry 2", event["squads"])
        self.assertEqual(len(event["squads"]["Infantry 1"]["members"]), 3)


if __name__ == "__main__":
    unittest.main()
