#!/usr/bin/env python3
"""Oversized squads from all free infantry seats + configurable pair rule.

Spec: docs/superpowers/specs/2026-10-23-oversized-squads-free-seats-design.md
"""

import itertools
import os
import random
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import bot  # noqa: E402
import database  # noqa: E402
import utils  # noqa: E402
from i18n import t, _STRINGS  # noqa: E402

SIX11 = [6] * 11


def _dcn(**over):
    # The motivating event "Oktober DCN": 100 server − 2 casters = 98 player
    # seats, 6×2 vehicle + 2×1 heli → S = 84 infantry seats = exactly 14 × 6.
    ev = {"mode": "rep", "dont_waste_slots": True, "max_player_slots": 98,
          "infantry_squad_size": 6, "vehicle_squad_size": 2, "heli_squad_size": 1,
          "max_vehicle_squads": 6, "max_heli_squads": 2, "squads": {}}
    ev.update(over)
    return ev


def _squads(*sizes):
    return {f"s{i}": {"name": "x", "type": "infantry", "size": s} for i, s in enumerate(sizes)}


def _reason(ev, size):
    return utils.infantry_block_reason(ev, size)


class TestPairRulePlumbing(unittest.TestCase):
    def test_default_carry_over_backfill(self):
        settings = dict(database.DEFAULT_GUILD_SETTINGS)
        self.assertIs(database.build_default_event(settings, "E", "01.01.2030", "20:00")["dont_waste_pairs"], True)
        self.assertIs(database.build_default_event(settings, "E", "01.01.2030", "20:00",
                                                   dont_waste_pairs=False)["dont_waste_pairs"], False)
        self.assertIn("dont_waste_pairs", database._CARRY_OVER_KEYS)
        ev = {}
        bot._ensure_event_keys(ev)
        self.assertIs(ev["dont_waste_pairs"], True)
        self.assertTrue(utils.dont_waste_pairs({}))
        self.assertFalse(utils.dont_waste_pairs({"dont_waste_pairs": False}))


class TestBlockReason(unittest.TestCase):
    def test_seat_budget(self):
        self.assertEqual(utils.infantry_seat_budget(_dcn()), 84)
        self.assertEqual(utils.infantry_unused_pool(_dcn()), 0)
        self.assertEqual(utils.infantry_seat_budget(_dcn(max_vehicle_squads=60)), 0)

    def test_rep_mode_active_without_leftover(self):
        self.assertTrue(utils.dont_waste_slots_active(_dcn()))
        self.assertFalse(utils.dont_waste_slots_active(_dcn(infantry_squad_size=9)))

    def test_example_a_pairs_off(self):
        ev = _dcn(dont_waste_pairs=False, squads=_squads(*SIX11))
        for k in (6, 7, 8, 9):
            self.assertIsNone(_reason(ev, k), k)
        ev = _dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9))
        for k in (6, 7, 8, 9):
            self.assertEqual(_reason(ev, k), "seats", k)

    def test_example_b_pairs_on_enabled_late(self):
        ev = _dcn(squads=_squads(*SIX11))
        self.assertIsNone(_reason(ev, 6))
        for k in (7, 8, 9):
            self.assertEqual(_reason(ev, k), "size", k)

    def test_example_c_pairs_on_enabled_early(self):
        self.assertIsNone(_reason(_dcn(), 9))
        ev = _dcn(squads=_squads(9, *[6] * 10))
        self.assertIsNone(_reason(ev, 9))               # mirror
        self.assertEqual(_reason(ev, 6), "mirror")
        # Pair complete, 10 regular: an 11th would make the regular count odd.
        self.assertEqual(_reason(_dcn(squads=_squads(9, 9, *[6] * 10)), 6), "full")

    def test_example_d_max_one_pairs_off(self):
        ev = _dcn(dont_waste_pairs=False, dont_waste_max_squads=1, squads=_squads(*SIX11, 9))
        self.assertIsNone(_reason(ev, 6))
        self.assertEqual(_reason(ev, 7), "size")
        self.assertEqual(_reason(ev, 9), "size")

    def test_example_e_mode_off_checks_seats(self):
        ev = _dcn(dont_waste_slots=False, dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9))
        self.assertEqual(_reason(ev, 6), "seats")       # 13 < cap 14, but 0 seats left

    def test_mode_off_no_oversize_no_reservation(self):
        self.assertEqual(_reason(_dcn(dont_waste_slots=False), 7), "size")
        self.assertIsNone(_reason(_dcn(dont_waste_slots=False, squads=_squads(9, *[6] * 10)), 6))

    def test_whitelist(self):
        ev = _dcn(dont_waste_pairs=False, dont_waste_allowed_sizes=[7])
        self.assertIsNone(_reason(ev, 7))
        self.assertEqual(_reason(ev, 8), "size")
        # Pairs on: the mirror of a no-longer-allowed size stays registerable — only the mirror.
        self.assertIsNone(_reason(_dcn(dont_waste_allowed_sizes=[7], squads=_squads(9)), 9))
        self.assertEqual(_reason(_dcn(dont_waste_allowed_sizes=[7], squads=_squads(9, 9)), 9), "size")

    def test_max_cap(self):
        self.assertEqual(_reason(_dcn(dont_waste_max_squads=2, squads=_squads(9, 9)), 7), "size")
        self.assertIsNone(_reason(_dcn(dont_waste_max_squads=2, squads=_squads(9, 9, 7)), 7))  # mirror beats cap
        self.assertIsNone(_reason(_dcn(dont_waste_pairs=False, dont_waste_max_squads=3,
                                       squads=_squads(9, 9)), 7))
        self.assertEqual(_reason(_dcn(dont_waste_pairs=False, dont_waste_max_squads=3,
                                      squads=_squads(9, 9, 7)), 7), "size")

    def test_tiny_cap_keeps_base_registrable(self):
        ev = _dcn(max_player_slots=8, max_vehicle_squads=0, max_heli_squads=0)  # S 8, cap 1
        self.assertIsNone(_reason(ev, 6))
        self.assertEqual(_reason(ev, 7), "size")

    def test_unreachable_mirror_reserves_nothing(self):
        # Pair rule switched on after pairs-off sign-ups: 10×6 + 9 + 8 = 77, 7 free.
        ev = _dcn(squads=_squads(*[6] * 10, 9, 8))
        self.assertEqual(_reason(ev, 9), "seats")
        self.assertEqual(_reason(ev, 8), "seats")
        self.assertEqual(_reason(ev, 6), "full")        # no reservation; parity blocks the 11th

    def test_overbooked_after_override(self):
        self.assertEqual(_reason(_dcn(max_vehicle_squads=7, squads=_squads(*[6] * 14)), 6), "full")
        self.assertEqual(_reason(_dcn(squads=_squads(*[6] * 12, 12)), 6), "seats")


if __name__ == "__main__":
    unittest.main()
