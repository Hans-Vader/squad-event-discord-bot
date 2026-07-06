#!/usr/bin/env python3
"""Unit tests for keeping a Squad Leader (SL) in every infantry squad.

When a squad loses its only SL, `_rebalance_squad_leaders` moves a spare SL from
a squad that has a surplus (2+) into the leaderless one; if the receiver is full
a non-SL member swaps back so both stay within size. When no spare SL exists the
squad is left leaderless and `format_event_details` flags it with a ⚠️ warning.
SL is an infantry-only role, so vehicle/heli squads are never touched or flagged.
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

SL = ["Squad Leader"]
RIFLE = ["Rifleman"]


def _m(uid, name, roles=None):
    d = {"user_id": uid, "name": name}
    if roles is not None:
        d["roles"] = roles
    return d


def _event(squads):
    return {
        "name": "Test Event",
        "date": "01.01.2099",
        "time": "20:00",
        "mode": "player",
        "max_player_slots": 24,
        "infantry_squad_size": 6,
        "vehicle_squad_size": 2,
        "heli_squad_size": 1,
        "max_vehicle_squads": 2,
        "max_heli_squads": 1,
        "player_slots_used": sum(len(s["members"]) for s in squads.values()),
        "squads": squads,
        "casters": {},
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
        "caster_waitlist": [],
        "tentative": [],
        "declined": [],
    }


def _ua(squads):
    ua = {}
    for name, data in squads.items():
        for m in data["members"]:
            ua.setdefault(m["user_id"], []).append(name)
    return ua


def _sl_count(squad):
    return sum(1 for m in squad["members"] if "Squad Leader" in utils._get_member_roles(m))


class RebalanceLogicTest(unittest.TestCase):
    def test_simple_move_when_receiver_has_room(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("a", "A", SL), _m("b", "B", SL),
                _m("r1", "R1"), _m("r2", "R2"), _m("r3", "R3"), _m("r4", "R4")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [  # 5/6, 0 SL
                _m("r5", "R5"), _m("r6", "R6"), _m("r7", "R7"),
                _m("r8", "R8"), _m("r9", "R9")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        moved = utils._rebalance_squad_leaders(event, ua)

        inf1, inf2 = event["squads"]["Infantry 1"], event["squads"]["Infantry 2"]
        self.assertEqual(_sl_count(inf1), 1)
        self.assertEqual(_sl_count(inf2), 1)
        self.assertEqual(len(inf1["members"]), 5)  # donor lost its spare SL
        self.assertEqual(len(inf2["members"]), 6)  # receiver filled its free seat
        self.assertEqual(ua["b"], ["Infantry 2"])  # the surplus SL (B) moved
        self.assertEqual(moved, [("b", "B", "Infantry 2")])

    def test_full_receiver_swaps_a_non_sl_out(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("a", "A", SL), _m("b", "B", SL),
                _m("r1", "R1"), _m("r2", "R2"), _m("r3", "R3"), _m("r4", "R4")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [  # 6/6, 0 SL
                _m("r5", "R5"), _m("r6", "R6"), _m("r7", "R7"),
                _m("r8", "R8"), _m("r9", "R9"), _m("r10", "R10")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        utils._rebalance_squad_leaders(event, ua)

        inf1, inf2 = event["squads"]["Infantry 1"], event["squads"]["Infantry 2"]
        self.assertEqual(len(inf1["members"]), 6)  # both stay within size after swap
        self.assertEqual(len(inf2["members"]), 6)
        self.assertEqual(_sl_count(inf1), 1)
        self.assertEqual(_sl_count(inf2), 1)
        self.assertEqual(ua["b"], ["Infantry 2"])
        swapped_out = [uid for uid in ("r5", "r6", "r7", "r8", "r9", "r10")
                       if ua[uid] == ["Infantry 1"]]
        self.assertEqual(len(swapped_out), 1)  # exactly one non-SL bumped to the donor

    def test_no_spare_sl_leaves_squad_leaderless(self):
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("a", "A", SL), _m("r1", "R1")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [  # 0 SL, no donor
                _m("r2", "R2"), _m("r3", "R3")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        moved = utils._rebalance_squad_leaders(event, ua)

        self.assertEqual(moved, [])
        self.assertEqual(_sl_count(event["squads"]["Infantry 1"]), 1)
        self.assertEqual(_sl_count(event["squads"]["Infantry 2"]), 0)

    def test_non_infantry_squads_untouched(self):
        squads = {
            "Vehicle 1": {"type": "vehicle", "size": 2, "members": [_m("v1", "A")]},
            "Vehicle 2": {"type": "vehicle", "size": 2, "members": [_m("v2", "B")]},
        }
        event = _event(squads)
        ua = _ua(squads)
        before = {n: list(d["members"]) for n, d in event["squads"].items()}

        moved = utils._rebalance_squad_leaders(event, ua)

        self.assertEqual(moved, [])
        self.assertEqual({n: list(d["members"]) for n, d in event["squads"].items()}, before)


class RebalanceOnUnregisterTest(unittest.TestCase):
    def test_spare_sl_moves_into_leaderless_squad_on_unregister(self):
        # The pasted scenario: Inf 1 holds two SLs, Inf 2's only SL unregisters.
        squads = {
            "Infantry 1": {"type": "infantry", "size": 6, "members": [
                _m("a", "Hightex", SL), _m("b", "Willy", SL),
                _m("r1", "R1"), _m("r2", "R2"), _m("r3", "R3"), _m("r4", "R4")]},
            "Infantry 2": {"type": "infantry", "size": 6, "members": [
                _m("c", "SL2", SL), _m("r5", "R5"), _m("r6", "R6"),
                _m("r7", "R7"), _m("r8", "R8"), _m("r9", "R9")]},
        }
        event = _event(squads)
        ua = _ua(squads)

        ok, name, _promoted = utils._player_unregister(event, ua, "c")

        self.assertTrue(ok)
        inf1, inf2 = event["squads"]["Infantry 1"], event["squads"]["Infantry 2"]
        self.assertEqual(_sl_count(inf1), 1)
        self.assertEqual(_sl_count(inf2), 1)  # Willy backfilled the leaderless squad
        self.assertEqual(ua["b"], ["Infantry 2"])
        self.assertIn("b", [m["user_id"] for m in inf2["members"]])
        self.assertEqual(event["player_slots_used"], 11)  # only the decliner left; move is seat-neutral


class LeaderlessWarningEmbedTest(unittest.TestCase):
    def _inf_value(self, embed, lang="de"):
        label = t("embed.type_infantry", lang)
        for f in embed.fields:
            if f.name.startswith(label):
                return f.value
        return None

    def test_warning_for_leaderless_infantry_squad(self):
        squads = {"Infantry 1": {"type": "infantry", "size": 6, "members": [
            _m("r1", "R1", RIFLE), _m("r2", "R2", RIFLE)]}}
        val = self._inf_value(utils.format_event_details(_event(squads), "de"))
        self.assertIn(t("embed.no_squad_leader", "de"), val)

    def test_no_warning_when_squad_has_sl(self):
        squads = {"Infantry 1": {"type": "infantry", "size": 6, "members": [
            _m("a", "SL", SL), _m("r1", "R1", RIFLE)]}}
        val = self._inf_value(utils.format_event_details(_event(squads), "de"))
        self.assertNotIn(t("embed.no_squad_leader", "de"), val)

    def test_no_warning_when_roles_disabled(self):
        squads = {"Infantry 1": {"type": "infantry", "size": 6, "members": [
            _m("r1", "R1", RIFLE)]}}
        event = _event(squads)
        event["player_roles_enabled"] = False
        val = self._inf_value(utils.format_event_details(event, "de"))
        self.assertNotIn(t("embed.no_squad_leader", "de"), val)

    def test_no_warning_for_empty_squad(self):
        squads = {"Infantry 1": {"type": "infantry", "size": 6, "members": []}}
        val = self._inf_value(utils.format_event_details(_event(squads), "de"))
        self.assertNotIn(t("embed.no_squad_leader", "de"), val)

    def test_no_warning_for_vehicle_squad(self):
        squads = {"Vehicle 1": {"type": "vehicle", "size": 2, "members": [
            _m("v1", "Driver", ["Driver"])]}}
        embed = utils.format_event_details(_event(squads), "de")
        label = t("embed.type_vehicle", "de")
        veh_val = next((f.value for f in embed.fields if f.name.startswith(label)), None)
        self.assertIsNotNone(veh_val)
        self.assertNotIn(t("embed.no_squad_leader", "de"), veh_val)


class I18nKeyTest(unittest.TestCase):
    def test_no_squad_leader_key_present(self):
        for lang in ("de", "en"):
            self.assertNotIn("missing", t("embed.no_squad_leader", lang))


if __name__ == "__main__":
    unittest.main()
