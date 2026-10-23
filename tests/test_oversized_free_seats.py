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


class TestSizeOptionsFreeSeats(unittest.TestCase):
    def _opts(self, **over):
        return utils.infantry_size_options(_dcn(**over))

    def test_example_a(self):
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11)),
                         [(6, 3), (7, 2), (8, 2), (9, 2)])
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11, 9)),
                         [(6, 1), (7, 1), (8, 1), (9, 1)])
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9)), [(6, 0)])
        self.assertEqual(self._opts(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 6)), [(6, 0)])

    def test_example_b(self):
        self.assertEqual(self._opts(squads=_squads(*SIX11)), [(6, 3)])

    def test_example_c(self):
        self.assertEqual(self._opts(), [(6, 14), (7, 12), (8, 10), (9, 8)])
        self.assertEqual(self._opts(squads=_squads(9)), [(6, 10), (7, 8), (8, 8), (9, 7)])

    def test_example_d_and_e(self):
        self.assertEqual(self._opts(dont_waste_pairs=False, dont_waste_max_squads=1,
                                    squads=_squads(*SIX11, 9)), [(6, 1)])
        self.assertEqual(self._opts(dont_waste_slots=False, dont_waste_pairs=False,
                                    squads=_squads(*SIX11, 9, 9)), [(6, 0)])

    def test_switch_on_with_odd_counts(self):
        self.assertEqual(self._opts(squads=_squads(*SIX11, 9)), [(6, 0), (9, 1)])
        self.assertEqual(self._opts(squads=_squads(*[6] * 10, 9, 8)), [(6, 0)])

    def test_player_mode_and_edge_inputs(self):
        self.assertEqual(self._opts(mode="player"), [(6, 14)])
        legacy = _dcn(squads={"s0": {"name": "x", "type": "infantry"}})
        self.assertEqual(utils.infantry_size_options(legacy), self._opts(squads=_squads(6)))
        veh = _dcn(squads={"v": {"type": "vehicle", "size": 2}, "h": {"type": "heli", "size": 1}})
        self.assertEqual(utils.infantry_size_options(veh), self._opts())


class TestFreeSeatInvariants(unittest.TestCase):
    """Seeded random walks through the real gate, both pair rules."""

    CONFIGS = [dict(), dict(max_player_slots=90), dict(max_player_slots=91),
               dict(dont_waste_allowed_sizes=[7, 9]), dict(dont_waste_max_squads=2),
               dict(dont_waste_max_squads=3),
               dict(infantry_squad_size=7, max_vehicle_squads=0, max_heli_squads=0),
               dict(max_player_slots=8, max_vehicle_squads=0, max_heli_squads=0),
               dict(infantry_squad_size=1, max_player_slots=40, max_vehicle_squads=0, max_heli_squads=0)]

    _ids = itertools.count()

    def _add(self, ev, size):
        ev["squads"][f"p{next(self._ids)}"] = {"name": "x", "type": "infantry", "size": size}

    def _check(self, ev, trace):
        base, pairs = ev["infantry_squad_size"], utils.dont_waste_pairs(ev)
        S, cap = utils.infantry_seat_budget(ev), utils._max_squads_for_type(ev, "infantry")
        inf = list(ev["squads"].values())
        ctx = f"pairs={pairs} trace={trace}"
        self.assertLessEqual(sum(d["size"] for d in inf), S, ctx)
        self.assertLessEqual(len(inf), cap, ctx)
        counts = utils._oversized_counts(ev)
        if ev.get("dont_waste_max_squads"):
            m = ev["dont_waste_max_squads"]
            used = sum(c + (c % 2 if pairs else 0) for c in counts.values())
            self.assertLessEqual(used, m - m % 2 if pairs else m, ctx)
        opts = dict(utils.infantry_size_options(ev))
        for k in range(base, utils.MAX_SQUAD_PLAYERS + 1):
            self.assertEqual(opts.get(k, 0) > 0, utils.infantry_block_reason(ev, k) is None, f"{k} {ctx}")
        self.assertGreaterEqual(utils.infantry_wasted_seats(ev), 0, ctx)
        if pairs:
            probe = {**ev, "squads": dict(ev["squads"])}
            for k in sorted(k for k, c in counts.items() if c % 2):
                self.assertIsNone(utils.infantry_block_reason(probe, k), f"mirror {k} {ctx}")
                self._add(probe, k)
            self.assertFalse(any(c % 2 for c in utils._oversized_counts(probe).values()), ctx)
            n_reg = sum(1 for d in probe["squads"].values() if d["size"] <= base)
            if n_reg % 2 and cap >= 2:
                self.assertIsNone(utils.infantry_block_reason(probe, base), f"parity {ctx}")

    def test_random_walks(self):
        rng = random.Random(42)
        for cfg in self.CONFIGS:
            for pairs in (True, False):
                for _run in range(10):
                    ev = _dcn(dont_waste_pairs=pairs, **cfg)
                    trace = []
                    for _step in range(150):
                        if rng.random() < 0.6 or not ev["squads"]:
                            k = rng.choice([s for s, _ in utils.infantry_size_options(ev)])
                            if utils.infantry_block_reason(ev, k) is None:
                                self._add(ev, k)
                                trace.append(f"+{k}")
                        else:
                            sid = rng.choice(sorted(ev["squads"]))
                            trace.append(f"-{ev['squads'].pop(sid)['size']}")
                        self._check(ev, trace[-12:])


def _dcn_embed(**over):
    ev = _dcn(name="Test Event", date="01.01.2099", time="20:00", server_max_players=100,
              max_caster_slots=2, player_slots_used=0, caster_slots_used=0, casters={},
              infantry_waitlist=[], vehicle_waitlist=[], heli_waitlist=[], caster_waitlist=[],
              tentative=[], declined=[])
    ev.update(over)
    return ev


class TestBestCaseAndEmbed(unittest.TestCase):
    def _embed(self, **over):
        return utils.format_event_details(_dcn_embed(**over), "de")

    def _inf_name(self, embed):
        return next(f.name for f in embed.fields if "Infan" in f.name)

    def _values(self, embed):
        return "\n".join(str(f.value) for f in embed.fields)

    def test_best_case_values(self):
        self.assertEqual(utils.infantry_best_case(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9))), (84, 13))
        self.assertEqual(utils.infantry_best_case(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 6))), (81, 13))
        self.assertEqual(utils.infantry_best_case(_dcn(squads=_squads(9))), (84, 12))
        self.assertEqual(utils.infantry_best_case(_dcn(squads=_squads(9, 9, *[6] * 10))), (78, 12))
        self.assertEqual(utils.infantry_best_case(_dcn(dont_waste_pairs=False, dont_waste_max_squads=1,
                                                       squads=_squads(*SIX11, 9))), (81, 13))

    def test_header_example_a(self):
        name = self._inf_name(self._embed(dont_waste_pairs=False, squads=_squads(*SIX11, 9)))
        self.assertIn("(12/13) [(11/12) Größe: 6 | (0/1) Größe: 7 | (0/1) Größe: 8 | (1/2) Größe: 9]", name)

    def test_header_example_b_plain(self):
        self.assertIn("(11/14) [Größe: 6]", self._inf_name(self._embed(squads=_squads(*SIX11))))

    def test_header_example_c(self):
        name = self._inf_name(self._embed(squads=_squads(9)))
        self.assertIn("(1/12) [(0/10) Größe: 6 | (0/8) Größe: 7 | (0/8) Größe: 8 | (1/8) Größe: 9]", name)

    def test_unused(self):
        self.assertIn("Ungenutzt: 3", self._values(self._embed(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 6))))
        self.assertIn("Ungenutzt: 6", self._values(self._embed(squads=_squads(9, 9, *[6] * 10))))
        self.assertNotIn("Ungenutzt", self._values(self._embed(squads=_squads(9))))       # best case fills 84
        self.assertNotIn("Ungenutzt", self._values(self._embed(dont_waste_pairs=False, squads=_squads(*SIX11))))

    def test_overbooked_header_never_negative(self):
        embed = self._embed(max_vehicle_squads=7, squads=_squads(*[6] * 14))
        self.assertIn("(14/14)", self._inf_name(embed))
        self.assertNotIn("Ungenutzt", self._values(embed))
        self.assertEqual(utils.infantry_wasted_seats(_dcn(squads=_squads(*[6] * 12, 12))), 0)

    def test_base_one_is_fast(self):
        for pairs in (True, False):
            ev = _dcn(infantry_squad_size=1, max_player_slots=200, max_vehicle_squads=0,
                      max_heli_squads=0, dont_waste_pairs=pairs)
            t0 = time.monotonic()
            opts = utils.infantry_size_options(ev)
            utils.infantry_best_case(ev)
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertLessEqual(len(opts), 9)


class TestSquadGate(unittest.TestCase):
    def test_regular_outcomes(self):
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(*SIX11)), "infantry", 6, None), (6, "ok"))
        self.assertEqual(bot._squad_gate(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11, 9, 9)),
                                         "infantry", 6, None), (6, "seats"))
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(9, *[6] * 10)), "infantry", 6, None), (6, "mirror"))
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(*[6] * 14)), "infantry", 6, None), (6, "full"))

    def test_oversized_pick(self):
        self.assertEqual(bot._squad_gate(_dcn(dont_waste_pairs=False, squads=_squads(*SIX11)),
                                         "infantry", 6, 9), (9, "ok"))
        self.assertEqual(bot._squad_gate(_dcn(squads=_squads(*SIX11)), "infantry", 6, 9), (9, "unavailable"))

    def test_other_types_count_only(self):
        full = _dcn(squads={f"v{i}": {"type": "vehicle", "size": 2} for i in range(6)})
        self.assertEqual(bot._squad_gate(full, "vehicle", 2, None), (2, "full"))
        self.assertEqual(bot._squad_gate(_dcn(), "heli", 1, None), (1, "ok"))


class TestWaitlistPromotion(unittest.IsolatedAsyncioTestCase):
    async def _promote(self, ev, free):
        with patch.object(bot, "save_event"), \
             patch.object(bot, "_send_squad_dm", new=AsyncMock()), \
             patch.object(bot, "send_to_log_channel", new=AsyncMock()), \
             patch.object(bot, "get_guild_language", return_value="de"), \
             patch.object(bot, "_build_event_message_link", return_value=None):
            await bot._process_squad_waitlist(ev, {}, 1, 1, 2, free, freed_type="infantry")

    def _ev(self, squads, entry_size=6, **over):
        return _dcn(squads=_squads(*squads), player_slots_used=0, vehicle_waitlist=[], heli_waitlist=[],
                    infantry_waitlist=[("W", "infantry", entry_size, "w1", "Rep")], **over)

    async def test_no_promotion_without_infantry_seats(self):
        # Example E: option switched off after a pairs-off 9er pair — 13 < cap 14, but 0 seats.
        ev = self._ev([*SIX11, 9, 9], dont_waste_slots=False, dont_waste_pairs=False)
        await self._promote(ev, 6)
        self.assertNotIn("w1", ev["squads"])

    async def test_promotion_when_seats_free(self):
        ev = self._ev([*SIX11, 9], dont_waste_pairs=False)
        await self._promote(ev, 9)
        self.assertIn("w1", ev["squads"])

    async def test_freed_oversized_squad_promotes_by_free_seats(self):
        # Spec §5.5: a freed oversized squad plus stranded seats can let several
        # 6ers move up. 11×6 + 9 + 6 (3 seats stranded), then the 9 leaves → 12 free.
        ev = self._ev([*SIX11, 6], dont_waste_pairs=False)
        ev["infantry_waitlist"].append(("W2", "infantry", 6, "w2", "Rep"))
        await self._promote(ev, 9)
        self.assertIn("w1", ev["squads"])
        self.assertIn("w2", ev["squads"])

    async def test_freed_pair_promotes_up_to_regular_capacity(self):
        # Pair rule: the last 9 of a pair leaves (mirror no longer held) → B 10 → 14.
        ev = self._ev([6] * 10)
        ev["infantry_waitlist"] += [("W2", "infantry", 6, "w2", "Rep"), ("W3", "infantry", 6, "w3", "Rep")]
        await self._promote(ev, 9)
        self.assertTrue(all(w in ev["squads"] for w in ("w1", "w2", "w3")))

    async def test_stale_smaller_entry_promoted(self):
        ev = self._ev([6] * 13, entry_size=5)
        await self._promote(ev, 6)
        self.assertIn("w1", ev["squads"])


def _pev(**over):
    # 27 seats, base 6 → cap 4, leftover pool 3.
    ev = _dcn(mode="player", max_player_slots=27, max_vehicle_squads=0, max_heli_squads=0,
              player_slots_used=0, infantry_waitlist=[])
    ev.update(over)
    return ev


class TestPlayerModePairRule(unittest.TestCase):
    def test_layout_pool_three(self):
        self.assertEqual(utils.planned_infantry_capacities(_pev()), [6, 6, 7, 7])
        self.assertEqual(utils.infantry_wasted_seats(_pev()), 1)
        self.assertEqual(utils.planned_infantry_capacities(_pev(dont_waste_pairs=False)), [6, 6, 6, 9])
        self.assertEqual(utils.infantry_wasted_seats(_pev(dont_waste_pairs=False)), 0)

    def test_single_leftover_seat(self):
        self.assertFalse(utils.dont_waste_slots_active(_pev(max_player_slots=25)))
        self.assertEqual(utils.planned_infantry_capacities(_pev(max_player_slots=25)), [6, 6, 6, 6])
        ev = _pev(max_player_slots=25, dont_waste_pairs=False)
        self.assertTrue(utils.dont_waste_slots_active(ev))
        self.assertEqual(utils.planned_infantry_capacities(ev), [6, 6, 6, 7])

    def test_max_cap_counts_squads(self):
        ev = _pev(max_player_slots=44, dont_waste_pairs=False)           # cap 6, pool 8
        self.assertEqual(utils.planned_infantry_capacities(ev), [6, 6, 6, 8, 9, 9])
        ev["dont_waste_max_squads"] = 1
        self.assertEqual(utils.planned_infantry_capacities(ev), [6, 6, 6, 6, 6, 9])
        self.assertEqual(utils.infantry_wasted_seats(ev), 5)

    def test_consolidation_singles(self):
        ev, ua = _pev(dont_waste_pairs=False), {}
        for i in range(27):
            utils._player_register(ev, ua, f"u{i}", f"P{i}", "infantry")
        utils.consolidate_all_player_squads(ev, ua)
        self.assertEqual(sorted(d["size"] for d in ev["squads"].values()), [6, 6, 6, 9])
        self.assertEqual(sum(len(d["members"]) for d in ev["squads"].values()), 27)


def _apply(ev, key, vtype, value):
    return bot._apply_property_change(ev, key, vtype, None, value, "de")


class TestConfigUi(unittest.TestCase):
    def test_step_available(self):
        self.assertTrue(bot._dont_waste_step_available(_dcn()))
        self.assertFalse(bot._dont_waste_step_available(_dcn(infantry_squad_size=9)))
        self.assertFalse(bot._dont_waste_step_available(_dcn(mode="player")))                    # pool 0
        self.assertTrue(bot._dont_waste_step_available(_dcn(mode="player", max_player_slots=99)))  # pool 1

    def test_editor_enable_rules(self):
        ev = _dcn(dont_waste_slots=False)
        self.assertTrue(_apply(ev, "dont_waste_slots", "bool", True)[0])               # rep, no leftover
        ok, err = _apply(_dcn(mode="player", dont_waste_slots=False), "dont_waste_slots", "bool", True)
        self.assertFalse(ok)
        self.assertIn("keine ungenutzten Slots", err)
        ev = _dcn(mode="player", max_player_slots=99, dont_waste_slots=False)
        ok, err = _apply(ev, "dont_waste_slots", "bool", True)
        self.assertFalse(ok)
        self.assertIn("nur 1 Slot", err)
        ev["dont_waste_pairs"] = False
        self.assertTrue(_apply(ev, "dont_waste_slots", "bool", True)[0])
        ok, err = _apply(_dcn(infantry_squad_size=9, dont_waste_slots=False), "dont_waste_slots", "bool", True)
        self.assertFalse(ok)
        self.assertIn("maximal 9 Spieler", err)

    def test_editor_max_values(self):
        ev = _dcn()
        for good in (1, 3, 4):
            self.assertTrue(_apply(ev, "dont_waste_max_squads", "int_nullable", good)[0], good)
        self.assertFalse(_apply(ev, "dont_waste_max_squads", "int_nullable", -2)[0])
        self.assertTrue(_apply(ev, "dont_waste_max_squads", "int_nullable", None)[0])
        self.assertIsNone(ev["dont_waste_max_squads"])

    def test_pair_property_row(self):
        self.assertIn((26, "dont_waste_pairs", "edit.property.dont_waste_pairs", "bool", None), bot._EDIT_PROPERTIES)
        for ev in (_dcn(), _dcn(mode="player"), _dcn(max_caster_slots=0)):
            keys = [p[1] for p in bot._visible_edit_properties(ev)]
            self.assertIn("dont_waste_pairs", keys)
            self.assertLessEqual(len(keys), 25)

    def test_wizard_view(self):
        with patch.object(bot, "get_guild_language", return_value="de"):
            view = bot.WizardDontWasteSlotsView(0, 0, _dcn(), {}, {}, None)
        self.assertEqual({o.value for o in view.pairs_select.options}, {"yes", "no"})
        self.assertEqual([o.value for o in view.sizes_select.options], ["7", "8", "9"])
        self.assertLessEqual(len(view.max_select.options), 25)
        self.assertTrue(all(c.row is not None and c.row <= 4 for c in view.children))

    def test_summary_shows_pair_rule(self):
        ev = _dcn_embed(dont_waste_pairs=False)   # summary reads only name/date by index, rest via .get
        with patch.object(bot, "get_guild_language", return_value="de"):
            fields = {f.name: f.value for f in bot._build_confirmation_embed(ev, 0).fields}
        self.assertIn(t("wizard.summary_dont_waste_pairs_off", "de"), fields[t("wizard.summary_dont_waste", "de")])
        self.assertIn("Übergroße Squads", t("wizard.summary_dont_waste", "de"))
        self.assertIn("Oversized squads", t("wizard.summary_dont_waste", "en"))

    def test_i18n_keys(self):
        for key in ("edit.property.dont_waste_pairs", "wizard.dont_waste_step_desc_player",
                    "wizard.dont_waste_pairs_placeholder", "wizard.dont_waste_pairs_on",
                    "wizard.dont_waste_pairs_off", "wizard.summary_dont_waste_pairs_on",
                    "wizard.summary_dont_waste_pairs_off"):
            for lang in ("de", "en"):
                self.assertIn(lang, _STRINGS.get(key, {}), f"{key}:{lang}")
        self.assertNotIn("{", t("wizard.dont_waste_step_desc", "de"))


if __name__ == "__main__":
    unittest.main()
