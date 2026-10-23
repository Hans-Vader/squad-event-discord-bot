#!/usr/bin/env python3
"""Unit tests for the "don't waste slots" mode (oversized infantry squads).

Covers the pure option math (single-size regime, strict pairs, mirror-slot
reservation), the select option/value plumbing, model defaults/carry-over,
and presence of the new i18n keys.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import bot  # noqa: E402
import database  # noqa: E402
import utils  # noqa: E402
from i18n import _STRINGS  # noqa: E402


def _event(**over):
    # max_player_slots 90, vehicle 6*2=12, heli 2*1=2 → 76 infantry seats:
    # 12 base squads of 6 (even, so both teams get the same count) + 4 unused.
    ev = {
        "mode": "rep",
        "dont_waste_slots": True,
        "max_player_slots": 90,
        "infantry_squad_size": 6,
        "vehicle_squad_size": 2,
        "heli_squad_size": 1,
        "max_vehicle_squads": 6,
        "max_heli_squads": 2,
        "squads": {},
    }
    ev.update(over)
    return ev


def _inf(size=6):
    return {"name": "x", "type": "infantry", "size": size}


def _squads(*sizes):
    return {f"s{i}": _inf(s) for i, s in enumerate(sizes)}


class TestUnusedPool(unittest.TestCase):
    def test_remainders(self):
        self.assertEqual(utils.infantry_unused_pool(_event()), 4)
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=91)), 5)
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=86)), 0)
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=87)), 1)

    def test_odd_base_cap_feeds_pool(self):
        # 82 infantry seats → 13 base squads would be odd; the cap rounds down
        # to 12 and the 13th squad's 6 seats join the 4-seat remainder.
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=96)), 10)

    def test_degenerate_config_clamps(self):
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=0)), 0)
        self.assertEqual(utils.infantry_unused_pool(_event(infantry_squad_size=0)), 0)


class TestSizeOptions(unittest.TestCase):
    def test_mode_off_base_only(self):
        opts = utils.infantry_size_options(_event(dont_waste_slots=False))
        self.assertEqual(opts, [(6, 12)])

    def test_player_mode_base_only(self):
        opts = utils.infantry_size_options(_event(mode="player"))
        self.assertEqual(opts, [(6, 12)])

    def test_odd_base_cap_rounds_down_and_feeds_pool(self):
        # User-reported scenario: server 100, casters 2, 2 vehicle, 2 heli →
        # 92 infantry seats = 15 base squads. 15 can't split into two equal
        # teams, so the cap becomes 14 and 6+2=8 seats feed the oversized pool.
        # The even cap holds regardless of the toggle — those seats just stay
        # unused when the mode is off.
        self.assertEqual(utils.infantry_size_options(
            _event(max_player_slots=98, max_vehicle_squads=2, max_heli_squads=2,
                   dont_waste_slots=False)),
            [(6, 14)])
        # Caps below 2 are exempt so tiny configs stay usable.
        tiny = _event(max_player_slots=20, dont_waste_slots=False)  # 6 inf seats
        self.assertEqual(utils.infantry_size_options(tiny), [(6, 1)])

    def test_active_gate(self):
        self.assertTrue(utils.dont_waste_slots_active(_event()))
        # Player mode is supported too (capacities are pre-planned by the bot).
        self.assertTrue(utils.dont_waste_slots_active(_event(mode="player")))
        self.assertFalse(utils.dont_waste_slots_active(_event(dont_waste_slots=False)))
        # Rep mode uses every free infantry seat, so no leftover is needed.
        self.assertTrue(utils.dont_waste_slots_active(_event(max_player_slots=87)))  # U=1
        self.assertTrue(utils.dont_waste_slots_active(_event(max_player_slots=86)))  # U=0
        # Player mode plans the leftover: a lone seat only fits without the pair rule.
        self.assertFalse(utils.dont_waste_slots_active(_event(mode="player", max_player_slots=87)))
        self.assertTrue(utils.dont_waste_slots_active(
            _event(mode="player", max_player_slots=87, dont_waste_pairs=False)))
        # An odd base cap always makes the mode meaningful (a whole squad feeds the pool).
        self.assertTrue(utils.dont_waste_slots_active(_event(max_player_slots=96)))
        # Base size at the in-game limit → no bigger squads can ever exist.
        self.assertFalse(utils.dont_waste_slots_active(
            _event(infantry_squad_size=9, max_player_slots=104)))


def _embed_event(**over):
    ev = _event(name="Test Event", date="01.01.2099", time="20:00",
                server_max_players=92, max_caster_slots=2,
                player_slots_used=0, caster_slots_used=0,
                casters={}, infantry_waitlist=[], vehicle_waitlist=[],
                heli_waitlist=[], caster_waitlist=[], tentative=[], declined=[])
    ev.update(over)
    return ev


class TestEmbedHeader(unittest.TestCase):
    def _infantry_field(self, embed):
        for f in embed.fields:
            if "Infan" in f.name:  # "Infanterie" (de) / "Infantry" (en)
                return f
        return None

    def test_squad_rows_show_size_with_people_icon(self):
        ev = _embed_event(squads=_squads(7, 6))
        field = self._infantry_field(utils.format_event_details(ev, "de"))
        self.assertIn("👥 7", field.value)
        self.assertIn("👥 6", field.value)

    def test_header_plain_when_mode_off(self):
        ev = _embed_event(squads=_squads(6, 6), dont_waste_slots=False)
        field = self._infantry_field(utils.format_event_details(ev, "de"))
        self.assertIn("[Größe: 6]", field.name)

    def test_zero_capacity_type_hidden(self):
        # Vehicles consume every seat (50×2 = 100) → infantry derives to 0/0.
        # An empty type with no capacity must not appear at all.
        ev = _embed_event(server_max_players=100, max_vehicle_squads=50,
                          max_heli_squads=0, squads={})
        embed = utils.format_event_details(ev, "de")
        self.assertIsNone(self._infantry_field(embed))
        # ...but the type that does have capacity stays.
        self.assertTrue(any("Fahrz" in f.name for f in embed.fields))

    def test_zero_capacity_type_with_squads_still_shown(self):
        # Capacity edited down to 0 after a squad signed up: the registered
        # squad must stay visible instead of silently vanishing.
        ev = _embed_event(server_max_players=100, max_vehicle_squads=50,
                          max_heli_squads=0, dont_waste_slots=False,
                          squads=_squads(6))
        field = self._infantry_field(utils.format_event_details(ev, "de"))
        self.assertIsNotNone(field)
        self.assertIn("(1/0)", field.name)

    def test_embed_shows_even_squad_cap(self):
        # User-reported scenario: 92 infantry seats → 15 raw squads. The embed
        # must show an even cap (14) regardless of the toggle.
        ev = _embed_event(server_max_players=100, max_player_slots=98,
                          max_vehicle_squads=2, max_heli_squads=2,
                          squads=_squads(7))
        field = self._infantry_field(utils.format_event_details(ev, "de"))
        self.assertIn("(1/14)", field.name)
        ev["dont_waste_slots"] = False
        embed = utils.format_event_details(ev, "de")
        field = self._infantry_field(embed)
        self.assertIn("(1/14)", field.name)
        # With the mode off, the dropped squad's seats count as unused.
        self.assertIn("Ungenutzt: 8", self._all_values(embed))

    def _all_values(self, embed):
        return "\n".join(str(f.value) for f in embed.fields)

    def test_unused_line_hidden_only_when_active(self):
        embed = utils.format_event_details(_embed_event(), "de")
        self.assertNotIn("Ungenutzt", self._all_values(embed))
        embed = utils.format_event_details(_embed_event(dont_waste_slots=False), "de")
        self.assertIn("Ungenutzt", self._all_values(embed))

    def test_residual_shown_while_mode_active(self):
        # U=5, 8er pair registered: 1 seat can never be paired anymore — it
        # reappears as "Ungenutzt: 1" even though the mode is on.
        ev = _embed_event(server_max_players=93, max_player_slots=91,
                          squads=_squads(8, 8))
        embed = utils.format_event_details(ev, "de")
        self.assertIn("Ungenutzt: 1", self._all_values(embed))

    def test_unused_line_hidden_at_zero(self):
        # "Ungenutzt: 0" is noise — hide the line entirely when nothing is unused.
        ev = _embed_event(server_max_players=88, max_player_slots=86,
                          dont_waste_slots=False)  # 72 inf seats = 12 squads, U=0
        embed = utils.format_event_details(ev, "de")
        self.assertNotIn("Ungenutzt", self._all_values(embed))


class TestSelectValuePlumbing(unittest.TestCase):
    def test_parse_squad_type_value(self):
        self.assertEqual(bot._parse_squad_type_value("infantry"), ("infantry", None))
        self.assertEqual(bot._parse_squad_type_value("infantry:7"), ("infantry", 7))
        self.assertEqual(bot._parse_squad_type_value("vehicle"), ("vehicle", None))
        self.assertEqual(bot._parse_squad_type_value("heli"), ("heli", None))

    def test_squad_type_options_mode_off_unchanged(self):
        opts = bot._squad_type_options(_event(dont_waste_slots=False), "en")
        self.assertEqual([o.value for o in opts], ["infantry", "vehicle", "heli"])

    def test_squad_type_options_mode_on_expanded(self):
        opts = bot._squad_type_options(_event(), "en")
        self.assertEqual([o.value for o in opts],
                         ["infantry", "infantry:7", "infantry:8", "infantry:9", "vehicle", "heli"])
        # oversized labels carry the remaining count
        by_value = {o.value: o.label for o in opts}
        self.assertIn("10x", by_value["infantry:7"])

    def test_no_sizes_above_game_limit(self):
        # Squads hold at most 9 players in-game: a base size at/above the limit
        # yields no oversized options at all, and the select stays tiny.
        ev = _event(infantry_squad_size=9, max_player_slots=104)  # 90 seats, 10 squads
        self.assertEqual(utils.infantry_size_options(ev), [(9, 10)])
        opts = bot._squad_type_options(ev, "en")
        self.assertEqual([o.value for o in opts], ["infantry", "vehicle", "heli"])


class TestModelPlumbing(unittest.TestCase):
    def test_default_and_override(self):
        settings = dict(database.DEFAULT_GUILD_SETTINGS)
        ev = database.build_default_event(settings, "E", "01.01.2030", "20:00")
        self.assertIs(ev["dont_waste_slots"], False)
        ev = database.build_default_event(settings, "E", "01.01.2030", "20:00",
                                          dont_waste_slots=True)
        self.assertIs(ev["dont_waste_slots"], True)

    def test_carry_over_and_backfill(self):
        self.assertIn("dont_waste_slots", database._CARRY_OVER_KEYS)
        ev = {}
        bot._ensure_event_keys(ev)
        self.assertIs(ev["dont_waste_slots"], False)

    def test_edit_property_row(self):
        rows = [p for p in bot._EDIT_PROPERTIES if p[1] == "dont_waste_slots"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "bool")

    def test_edit_property_visible_in_both_modes(self):
        keys = [p[1] for p in bot._visible_edit_properties(_event(mode="player"))]
        self.assertIn("dont_waste_slots", keys)
        keys = [p[1] for p in bot._visible_edit_properties(_event())]
        self.assertIn("dont_waste_slots", keys)

    def test_enable_via_editor_requires_unused_slots(self):
        # Player mode plans only the leftover: no unused slots (72 infantry
        # seats = 12 even squads) → rejected.
        ev = _event(mode="player", max_player_slots=86, dont_waste_slots=False)
        ok, err = bot._apply_property_change(ev, "dont_waste_slots", "bool", None, True, "de")
        self.assertFalse(ok)
        self.assertIn("keine ungenutzten Slots", err)
        self.assertFalse(ev["dont_waste_slots"])
        # Rep mode uses every free infantry seat → accepted without leftover.
        ev = _event(max_player_slots=86, dont_waste_slots=False)
        ok, err = bot._apply_property_change(ev, "dont_waste_slots", "bool", None, True, "de")
        self.assertTrue(ok, err)
        # A single unused slot can never form a pair → rejected with its own message.
        ev = _event(mode="player", max_player_slots=87, dont_waste_slots=False)
        ok, err = bot._apply_property_change(ev, "dont_waste_slots", "bool", None, True, "de")
        self.assertFalse(ok)
        self.assertIn("nur 1 Slot", err)
        # Base size at the 9-player game limit → rejected even with unused slots.
        ev = _event(infantry_squad_size=9, max_player_slots=104, dont_waste_slots=False)
        ok, err = bot._apply_property_change(ev, "dont_waste_slots", "bool", None, True, "de")
        self.assertFalse(ok)
        self.assertIn("maximal 9 Spieler", err)
        # Enough unused slots → accepted.
        ev = _event(dont_waste_slots=False)
        ok, err = bot._apply_property_change(ev, "dont_waste_slots", "bool", None, True, "de")
        self.assertTrue(ok)
        self.assertTrue(ev["dont_waste_slots"])
        # Disabling is always allowed, even with no unused slots.
        ev = _event(max_player_slots=86)
        ok, err = bot._apply_property_change(ev, "dont_waste_slots", "bool", None, False, "de")
        self.assertTrue(ok)
        self.assertFalse(ev["dont_waste_slots"])

    def test_allowed_sizes_plumbing_and_validation(self):
        settings = dict(database.DEFAULT_GUILD_SETTINGS)
        ev = database.build_default_event(settings, "E", "01.01.2030", "20:00")
        self.assertIsNone(ev["dont_waste_allowed_sizes"])
        self.assertIn("dont_waste_allowed_sizes", database._CARRY_OVER_KEYS)
        ev = {}
        bot._ensure_event_keys(ev)
        self.assertIsNone(ev["dont_waste_allowed_sizes"])
        rows = [p for p in bot._EDIT_PROPERTIES if p[1] == "dont_waste_allowed_sizes"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "size_list")
        keys = [p[1] for p in bot._visible_edit_properties(_event(mode="player"))]
        self.assertIn("dont_waste_allowed_sizes", keys)
        # Text parsing: numbers, "all", garbage.
        self.assertEqual(bot._validate_edit_text("7, 8", "size_list", "de"), ([7, 8], None))
        self.assertEqual(bot._validate_edit_text("alle", "size_list", "de"), (None, None))
        self.assertEqual(bot._validate_edit_text("", "size_list", "de"), (None, None))
        self.assertEqual(bot._validate_edit_text("7, x", "size_list", "de"),
                         (None, "edit.invalid_size_list"))
        # Range validation via the editor: <= base or > 9 rejected.
        ev = _event()
        ok, err = bot._apply_property_change(ev, "dont_waste_allowed_sizes",
                                             "size_list", None, [6], "de")
        self.assertFalse(ok)
        ok, err = bot._apply_property_change(ev, "dont_waste_allowed_sizes",
                                             "size_list", None, [10], "de")
        self.assertFalse(ok)
        ok, _err = bot._apply_property_change(ev, "dont_waste_allowed_sizes",
                                              "size_list", None, [7, 8], "de")
        self.assertTrue(ok)
        self.assertEqual(ev["dont_waste_allowed_sizes"], [7, 8])
        ok, _err = bot._apply_property_change(ev, "dont_waste_allowed_sizes",
                                              "size_list", None, None, "de")
        self.assertTrue(ok)
        self.assertIsNone(ev["dont_waste_allowed_sizes"])

    def test_squad_sizes_capped_at_game_limit(self):
        # Editing any squad size above 9 is rejected; 9 itself is fine.
        for key in ("infantry_squad_size", "vehicle_squad_size", "heli_squad_size"):
            ev = _event()
            ok, err = bot._apply_property_change(ev, key, "int", None, 10, "de")
            self.assertFalse(ok, key)
            self.assertIn("maximal 9 Spieler", err)
        ev = _event()
        ok, _err = bot._apply_property_change(ev, "infantry_squad_size", "int", None, 9, "de")
        self.assertTrue(ok)
        self.assertEqual(ev["infantry_squad_size"], 9)


class TestMaxSquadsCap(unittest.TestCase):
    """Organizer cap on the total number of oversized squads
    (`dont_waste_max_squads`, always even — pairs)."""

    def _ev(self, **over):
        # pool 8 (98 seats, veh 2×2, heli 2×1 → 92 infantry seats, cap 14)
        return _event(max_player_slots=98, max_vehicle_squads=2,
                      max_heli_squads=2, **over)

    def test_pair_plan_capped(self):
        self.assertEqual(utils._pair_plan(8, [1, 2, 3]), {3: 1, 1: 1})
        # One pair only → best single pair absorbs 6, wastes 2.
        self.assertEqual(utils._pair_plan(8, [1, 2, 3], max_pairs=1), {3: 1})
        self.assertEqual(utils._pair_plan(8, [1, 2, 3], max_pairs=0), {})

    def test_pair_cover_capped(self):
        self.assertEqual(utils._pair_cover(6, [1, 2, 3], max_pairs=1), {3: 1})
        # Cap prevents covering the target → {} (replan keeps capacities).
        self.assertEqual(utils._pair_cover(8, [1, 2, 3], max_pairs=1), {})

    def test_cap_reached_stops_offers_and_reports_waste(self):
        ev = self._ev(dont_waste_max_squads=2, squads=_squads(9, 9))
        self.assertEqual(utils.infantry_size_options(ev)[1:], [])
        self.assertEqual(utils.infantry_wasted_seats(ev), 2)

    def test_empty_state_cap_floor_reported(self):
        # No squads yet + cap 2 on pool 8: only one 9er pair (6 seats) can ever
        # be absorbed, so 2 seats are stranded from the start — must show even
        # while the oversized option is still open.
        ev = self._ev(dont_waste_max_squads=2)
        self.assertEqual(utils.infantry_wasted_seats(ev), 2)
        # No cap (or a cap that fits) still absorbs the whole pool → 0.
        self.assertEqual(utils.infantry_wasted_seats(self._ev()), 0)
        self.assertEqual(
            utils.infantry_wasted_seats(self._ev(dont_waste_max_squads=4)), 0)

    def test_cap_floor_accounts_for_registrations(self):
        # The floor must use what's actually registered, not a from-scratch
        # plan: four oversized squads filling the whole pool waste nothing even
        # though a from-scratch cap-2 plan would absorb only 6 of 8.
        self.assertEqual(utils.infantry_wasted_seats(
            self._ev(dont_waste_max_squads=2, squads=_squads(9, 9, 7, 7))), 0)
        # 7er mirror still open (would reach full absorption) → nothing wasted.
        self.assertEqual(utils.infantry_wasted_seats(
            self._ev(dont_waste_max_squads=2, squads=_squads(9, 9, 7))), 0)
        # Cap lowered to 2 after a 9er pair registered: the second pair the pool
        # could take is now forbidden, so its 2 seats are genuinely stranded.
        self.assertEqual(utils.infantry_wasted_seats(
            self._ev(dont_waste_max_squads=2, squads=_squads(9, 9))), 2)

    def test_mirror_completion_beats_cap(self):
        # Cap lowered below the started pairs: the 7er mirror must stay
        # registerable (equal numbers win), nothing new is offered.
        ev = self._ev(dont_waste_max_squads=2, squads=_squads(9, 9, 7))
        opts = dict(utils.infantry_size_options(ev))
        self.assertEqual(opts.get(7), 1)
        self.assertNotIn(9, opts)

    def test_player_layout_capped(self):
        # 44 seats, base 6 → cap 6 squads, pool 8.
        ev = _event(mode="player", max_player_slots=44,
                    max_vehicle_squads=0, max_heli_squads=0)
        self.assertEqual(utils.planned_infantry_capacities(ev),
                         [6, 6, 7, 7, 9, 9])
        ev["dont_waste_max_squads"] = 2
        self.assertEqual(utils.planned_infantry_capacities(ev),
                         [6, 6, 6, 6, 9, 9])
        self.assertEqual(utils.infantry_wasted_seats(ev), 2)

    def test_editor_validation(self):
        ev = self._ev()
        for good in (3, 1):
            ok, err = bot._apply_property_change(
                ev, "dont_waste_max_squads", "int_nullable", None, good, "de")
            self.assertTrue(ok, f"cap {good} rejected: {err}")
        ok, _err = bot._apply_property_change(
            ev, "dont_waste_max_squads", "int_nullable", None, -2, "de")
        self.assertFalse(ok, "negative cap accepted")
        ok, err = bot._apply_property_change(
            ev, "dont_waste_max_squads", "int_nullable", None, 4, "de")
        self.assertTrue(ok, err)
        self.assertEqual(ev["dont_waste_max_squads"], 4)
        ok, _err = bot._apply_property_change(
            ev, "dont_waste_max_squads", "int_nullable", None, None, "de")
        self.assertTrue(ok)
        self.assertIsNone(ev["dont_waste_max_squads"])

    def test_model_plumbing(self):
        ev = database.build_default_event(
            dict(database.DEFAULT_GUILD_SETTINGS), "E", "01.01.2030", "20:00")
        self.assertIsNone(ev.get("dont_waste_max_squads", 0))
        self.assertIn("dont_waste_max_squads", database._CARRY_OVER_KEYS)


def _player_event(**over):
    # 26 seats, no vehicle/heli, base 6 → cap 4 (even), pool 2: plan = one
    # 7er pair → capacity layout [6, 6, 7, 7].
    ev = _event(mode="player", max_player_slots=26,
                max_vehicle_squads=0, max_heli_squads=0,
                player_slots_used=0)
    ev.setdefault("infantry_waitlist", [])
    ev.update(over)
    return ev


class TestPlayerMode(unittest.TestCase):
    def _fill(self, ev, ua, n, start=0):
        statuses = []
        for i in range(start, start + n):
            _name, status = utils._player_register(ev, ua, f"u{i}", f"P{i}", "infantry")
            statuses.append(status)
        return statuses

    def _capacities(self, ev):
        return sorted(d["size"] for d in ev["squads"].values()
                      if d.get("type") == "infantry")

    def test_planned_capacities(self):
        self.assertEqual(utils.planned_infantry_capacities(_player_event()),
                         [6, 6, 7, 7])
        self.assertEqual(utils.planned_infantry_capacities(
            _player_event(dont_waste_slots=False)), [6, 6, 6, 6])
        # Whitelist that can't fit the pool → all base.
        self.assertEqual(utils.planned_infantry_capacities(
            _player_event(dont_waste_allowed_sizes=[9])), [6, 6, 6, 6])

    def test_auto_creation_uses_planned_capacities(self):
        ev, ua = _player_event(), {}
        statuses = self._fill(ev, ua, 26)
        self.assertTrue(all(s == "registered" for s in statuses))
        self.assertEqual(self._capacities(ev), [6, 6, 7, 7])
        self.assertEqual(ev["player_slots_used"], 26)
        # Seat 27 exceeds the planned layout → waitlist.
        _name, status = utils._player_register(ev, ua, "u99", "P99", "infantry")
        self.assertEqual(status, "waitlisted")

    def test_mode_off_unchanged(self):
        ev, ua = _player_event(dont_waste_slots=False), {}
        statuses = self._fill(ev, ua, 26)
        self.assertEqual(statuses.count("registered"), 24)  # 4 squads x 6
        self.assertEqual(statuses.count("waitlisted"), 2)
        self.assertEqual(self._capacities(ev), [6, 6, 6, 6])

    def test_consolidation_replans_capacities(self):
        # Fill completely, then thin out to 20 players → replan needs no
        # oversized squads at all (4 x 6 = 24 >= 20).
        ev, ua = _player_event(), {}
        self._fill(ev, ua, 26)
        for i in range(20, 26):
            utils._player_unregister(ev, ua, f"u{i}")
        utils.consolidate_all_player_squads(ev, ua)
        self.assertEqual(self._capacities(ev), [6, 6, 6, 6])
        self.assertEqual(sum(len(d["members"]) for d in ev["squads"].values()), 20)
        # Full house consolidates back to the planned pair layout.
        ev, ua = _player_event(), {}
        self._fill(ev, ua, 26)
        utils.consolidate_all_player_squads(ev, ua)
        self.assertEqual(self._capacities(ev), [6, 6, 7, 7])
        self.assertEqual(sum(len(d["members"]) for d in ev["squads"].values()), 26)
        # Every member landed within its squad's capacity.
        for d in ev["squads"].values():
            self.assertLessEqual(len(d["members"]), d["size"])

    def test_unregister_does_not_shrink_capacities(self):
        # Review finding: the per-unregister compaction must NOT replan —
        # otherwise capacities shrink (26→24 players ⇒ all-base) and a new
        # registration could never grow back into the planned layout.
        ev, ua = _player_event(), {}
        self._fill(ev, ua, 26)
        utils._player_unregister(ev, ua, "u0")
        utils._player_unregister(ev, ua, "u1")
        self.assertEqual(self._capacities(ev), [6, 6, 7, 7])
        _name, status = utils._player_register(ev, ua, "n1", "N1", "infantry")
        self.assertEqual(status, "registered")

    def test_tiny_cap_never_plans_unpairable_oversize(self):
        # Cap 1 (exempt from the even rule) can't hold a pair → all base.
        ev = _player_event(max_player_slots=8)  # 8 seats → cap 1, pool 2
        self.assertEqual(utils.planned_infantry_capacities(ev), [6])

    def test_unregister_frees_oversized_seat_for_waitlist(self):
        ev, ua = _player_event(), {}
        self._fill(ev, ua, 26)
        utils._player_register(ev, ua, "w1", "W1", "infantry")  # waitlisted
        utils._player_unregister(ev, ua, "u0")
        self.assertEqual(sum(len(d["members"]) for d in ev["squads"].values()
                             if d.get("type") == "infantry"), 26)
        self.assertIn("w1", ua)

    def test_player_mode_wasted_seats(self):
        self.assertEqual(utils.infantry_wasted_seats(_player_event()), 0)
        # Pool 5 (31 seats): plan absorbs 4 → 1 seat can never be used.
        self.assertEqual(utils.infantry_wasted_seats(
            _player_event(max_player_slots=31)), 1)
        # Whitelist [9] with pool 2 → nothing absorbable, all 2 wasted.
        self.assertEqual(utils.infantry_wasted_seats(
            _player_event(dont_waste_allowed_sizes=[9])), 2)

    def test_player_mode_header_shows_planned_layout(self):
        ev = _player_event(name="E", date="01.01.2099", time="20:00",
                           server_max_players=28, max_caster_slots=2,
                           caster_slots_used=0, casters={}, vehicle_waitlist=[],
                           heli_waitlist=[], caster_waitlist=[], tentative=[],
                           declined=[])
        ua = {}
        self._fill(ev, ua, 13)  # squads 1+2 full, squad 3 (7er) partially
        embed = utils.format_event_details(ev, "de")
        field = next(f for f in embed.fields if "Infan" in f.name)
        self.assertIn("[(2/2) Größe: 6 | (1/2) Größe: 7]", field.name)


class TestI18nKeys(unittest.TestCase):
    KEYS = (
        "wizard.dont_waste_step_title",
        "wizard.dont_waste_step_desc",
        "wizard.dont_waste_select_placeholder",
        "wizard.dont_waste_enabled",
        "wizard.dont_waste_disabled",
        "wizard.summary_dont_waste",
        "wizard.summary_dont_waste_yes",
        "wizard.summary_dont_waste_no",
        "wizard.dont_waste_sizes_placeholder",
        "wizard.dont_waste_size_option",
        "edit.property.dont_waste_sizes",
        "edit.sizes_all",
        "edit.invalid_size_list",
        "edit.size_list_hint",
        "edit.dont_waste_sizes_invalid",
        "squad.type_infantry_sized",
        "squad.waitlisted_mirror",
        "embed.server_overview_value_no_unused",
        "edit.property.dont_waste_slots",
        "edit.squad_size_max",
        "edit.dont_waste_max_size",
        "edit.dont_waste_no_unused",
        "edit.dont_waste_single_unused",
        "squad.size_unavailable",
    )

    def test_keys_exist_in_both_languages(self):
        for key in self.KEYS:
            self.assertIn(key, _STRINGS, key)
            for lang in ("de", "en"):
                self.assertIn(lang, _STRINGS[key], f"{key}:{lang}")


if __name__ == "__main__":
    unittest.main()
