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
    # max_player_slots 96, vehicle 6*2=12, heli 2*1=2 → 82 infantry seats:
    # 13 base squads of 6 + 4 unused (U=4).
    ev = {
        "mode": "rep",
        "dont_waste_slots": True,
        "max_player_slots": 96,
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
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=97)), 5)
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=92)), 0)
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=93)), 1)

    def test_degenerate_config_clamps(self):
        self.assertEqual(utils.infantry_unused_pool(_event(max_player_slots=0)), 0)
        self.assertEqual(utils.infantry_unused_pool(_event(infantry_squad_size=0)), 0)


class TestSizeOptions(unittest.TestCase):
    def test_mode_off_base_only(self):
        opts = utils.infantry_size_options(_event(dont_waste_slots=False))
        self.assertEqual(opts, [(6, 13)])

    def test_player_mode_base_only(self):
        opts = utils.infantry_size_options(_event(mode="player"))
        self.assertEqual(opts, [(6, 13)])

    def test_no_pool_base_only(self):
        self.assertEqual(utils.infantry_size_options(_event(max_player_slots=92)),
                         [(6, 13)])  # U=0
        self.assertEqual(utils.infantry_size_options(_event(max_player_slots=93)),
                         [(6, 13)])  # U=1 → strict pairs impossible

    def test_initial_options_u4(self):
        # U=4: either 4x 7 (2 pairs of +1) or 2x 8 (1 pair of +2); nothing above S+U//2.
        opts = utils.infantry_size_options(_event())
        self.assertEqual(opts, [(6, 13), (7, 4), (8, 2)])

    def test_first_pick_locks_size(self):
        ev = _event(squads=_squads(7))
        # one 7 registered: 8 gone, 7 continues (mirror + one more pair),
        # base loses one slot to the reserved mirror.
        self.assertEqual(utils.infantry_size_options(ev), [(6, 11), (7, 3)])

    def test_pair_completion_and_exhaustion(self):
        self.assertEqual(utils.infantry_size_options(_event(squads=_squads(7, 7))),
                         [(6, 11), (7, 2)])
        self.assertEqual(utils.infantry_size_options(_event(squads=_squads(7, 7, 7, 7))),
                         [(6, 9)])

    def test_unregister_reoffers_and_resets(self):
        # three 7s left after an unregister → mirror re-offered
        self.assertEqual(utils.infantry_size_options(_event(squads=_squads(7, 7, 7))),
                         [(6, 9), (7, 1)])
        # all oversized gone → full choice again
        self.assertEqual(utils.infantry_size_options(_event(squads=_squads(6, 6))),
                         [(6, 11), (7, 4), (8, 2)])

    def test_odd_leftover_stays_unused(self):
        # U=5: 8-pair consumes 4, the 5th seat can never be paired.
        ev = _event(max_player_slots=97)
        self.assertEqual(utils.infantry_size_options(ev), [(6, 13), (7, 4), (8, 2)])
        ev = _event(max_player_slots=97, squads=_squads(8, 8))
        self.assertEqual(utils.infantry_size_options(ev), [(6, 11)])

    def test_mirror_slot_reservation(self):
        # 11 base squads + one unpaired 7 → 12 of 13 slots used; the last
        # squad slot is reserved for the mirror: base drops to 0, 7 stays.
        ev = _event(squads=_squads(7, *([6] * 11)))
        self.assertEqual(utils.infantry_size_options(ev), [(6, 0), (7, 1)])

    def test_fresh_pair_needs_two_squad_slots(self):
        # 12 base squads → only one squad slot free: no room for a new pair.
        ev = _event(squads=_squads(*([6] * 12)))
        self.assertEqual(utils.infantry_size_options(ev), [(6, 1)])

    def test_config_shrink_clamps(self):
        # U shrank to 0 after an 8-pair registered → no oversized offered, no crash.
        ev = _event(max_player_slots=92, squads=_squads(8, 8))
        self.assertEqual(utils.infantry_size_options(ev), [(6, 11)])
        # ...but an incomplete pair is still offered so it can be equalized.
        ev = _event(max_player_slots=92, squads=_squads(8))
        self.assertEqual(utils.infantry_size_options(ev), [(6, 11), (8, 1)])

    def test_legacy_squads_without_size(self):
        ev = _event(squads={"s0": {"name": "x", "type": "infantry"}})
        self.assertEqual(utils.infantry_size_options(ev), [(6, 12), (7, 4), (8, 2)])

    def test_vehicle_heli_ignored(self):
        ev = _event(squads={"v": {"type": "vehicle", "size": 2},
                            "h": {"type": "heli", "size": 1}})
        self.assertEqual(utils.infantry_size_options(ev), [(6, 13), (7, 4), (8, 2)])

    def test_locked_size_needs_two_slots_for_new_pair(self):
        # 2x7 complete + 10 base squads → one squad slot free: a third 7 would
        # start a pair whose mirror could never register, so it isn't offered.
        ev = _event(squads=_squads(7, 7, *([6] * 10)))
        self.assertEqual(utils.infantry_size_options(ev), [(6, 1)])

    def test_multiple_pending_mirrors_all_reserved(self):
        # Degenerate post-config-edit state: two different oversized sizes,
        # each unpaired. Both mirrors keep a reserved slot; base gets none.
        ev = _event(squads=_squads(7, 8, *([6] * 9)))
        self.assertEqual(utils.infantry_size_options(ev), [(6, 0), (7, 1), (8, 1)])

    def test_active_gate(self):
        self.assertTrue(utils.dont_waste_slots_active(_event()))
        self.assertFalse(utils.dont_waste_slots_active(_event(mode="player")))
        self.assertFalse(utils.dont_waste_slots_active(_event(dont_waste_slots=False)))
        self.assertFalse(utils.dont_waste_slots_active(_event(max_player_slots=93)))  # U=1


def _embed_event(**over):
    ev = _event(name="Test Event", date="01.01.2099", time="20:00",
                server_max_players=98, max_caster_slots=2,
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

    def test_oversized_sizes_shown_in_header(self):
        ev = _embed_event(squads=_squads(7, 7, 8, 6))
        field = self._infantry_field(utils.format_event_details(ev, "de"))
        self.assertIn("[Größe: 6 | 2× 7er, 1× 8er]", field.name)
        field = self._infantry_field(utils.format_event_details(ev, "en"))
        self.assertIn("[Size: 6 | 2× 7, 1× 8]", field.name)

    def test_header_unchanged_without_oversized(self):
        ev = _embed_event(squads=_squads(6, 6))
        field = self._infantry_field(utils.format_event_details(ev, "de"))
        self.assertIn("[Größe: 6]", field.name)

    def _all_values(self, embed):
        return "\n".join(str(f.value) for f in embed.fields)

    def test_unused_line_hidden_only_when_active(self):
        embed = utils.format_event_details(_embed_event(), "de")
        self.assertNotIn("Ungenutzt", self._all_values(embed))
        embed = utils.format_event_details(_embed_event(dont_waste_slots=False), "de")
        self.assertIn("Ungenutzt", self._all_values(embed))


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
                         ["infantry", "infantry:7", "infantry:8", "vehicle", "heli"])
        # oversized labels carry the remaining count
        by_value = {o.value: o.label for o in opts}
        self.assertIn("4x", by_value["infantry:7"])
        self.assertIn("2x", by_value["infantry:8"])

    def test_squad_type_options_locked_size(self):
        opts = bot._squad_type_options(_event(squads=_squads(7)), "en")
        self.assertEqual([o.value for o in opts],
                         ["infantry", "infantry:7", "vehicle", "heli"])

    def test_squad_type_options_respect_discord_cap(self):
        # Absurd config: base size 47 with a 46-seat remainder → 23 candidate
        # oversized sizes; the select must stay within Discord's 25-option cap.
        ev = _event(infantry_squad_size=47, max_player_slots=248)
        self.assertEqual(len([s for s, _ in utils.infantry_size_options(ev)
                              if s != 47]), 23)
        opts = bot._squad_type_options(ev, "en")
        self.assertLessEqual(len(opts), 25)

    def test_slot_reserved_helper(self):
        # Base-size registration blocked while a mirror is pending...
        ev = _event(squads=_squads(7, *([6] * 11)))
        self.assertTrue(bot._squad_slot_reserved(ev, "infantry", 6))
        # ...but stale sizes (e.g. waitlist entries from before a squad-size
        # edit) and other types are never blocked by the reservation.
        ev_edited = _event(infantry_squad_size=8, squads=_squads(*([8] * 9)))
        self.assertFalse(bot._squad_slot_reserved(ev_edited, "infantry", 6))
        self.assertFalse(bot._squad_slot_reserved(ev, "vehicle", 2))
        self.assertFalse(bot._squad_slot_reserved(_event(dont_waste_slots=False), "infantry", 6))


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
        "squad.type_infantry_sized",
        "squad.waitlisted_mirror",
        "embed.server_overview_value_no_unused",
        "edit.property.dont_waste_slots",
        "squad.size_unavailable",
    )

    def test_keys_exist_in_both_languages(self):
        for key in self.KEYS:
            self.assertIn(key, _STRINGS, key)
            for lang in ("de", "en"):
                self.assertIn(lang, _STRINGS[key], f"{key}:{lang}")


if __name__ == "__main__":
    unittest.main()
