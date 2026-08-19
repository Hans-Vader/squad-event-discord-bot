#!/usr/bin/env python3
"""The squad composition IS the capacity.

Replaces the old "don't waste slots" suite. That feature existed because the
infantry squad count was DERIVED from a server-wide seat total, leaving a
remainder that had to be absorbed by oversized squad pairs. Now the organizer
states the composition outright — `[[size, count], ...]` — so there is no
remainder, no pair planner, and each size carries its own independent quota.
"""

import json
import os
import sys
import tempfile
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

import database  # noqa: E402
import utils  # noqa: E402
import bot as botmod  # noqa: E402
from i18n import t, _STRINGS  # noqa: E402


def _event(composition=None, **over):
    ev = {
        "name": "Test", "mode": "rep",
        "infantry_squads": composition if composition is not None else [[6, 4]],
        "vehicle_squad_size": 2, "heli_squad_size": 1,
        "max_vehicle_squads": 2, "max_heli_squads": 1,
        "max_caster_slots": 2, "max_squads_per_user": 1,
        "squads": {}, "player_slots_used": 0,
        "infantry_waitlist": [], "vehicle_waitlist": [], "heli_waitlist": [],
    }
    ev.update(over)
    return ev


def _squad(size, type_="infantry"):
    return {"name": f"S{size}", "type": type_, "size": size}


# ---------------------------------------------------------------------------
# Storage shape
# ---------------------------------------------------------------------------

class CompositionStorageTest(unittest.TestCase):

    def test_accessor_returns_int_pairs(self):
        self.assertEqual(utils.infantry_composition(_event([[6, 10], [8, 4]])),
                         [(6, 10), (8, 4)])

    def test_missing_or_empty_is_an_empty_composition(self):
        self.assertEqual(utils.infantry_composition({}), [])
        self.assertEqual(utils.infantry_composition({"infantry_squads": None}), [])

    def test_survives_the_json_round_trip_as_ints(self):
        """The reason the stored shape is a pair list and not {size: count}:
        JSON turns dict keys into strings, which would only break after a
        restart — never in an in-process test."""
        ev = _event([[6, 10], [8, 4]])
        restored = database._loads(database._dumps(ev))
        self.assertEqual(utils.infantry_composition(restored), [(6, 10), (8, 4)])
        for size, count in utils.infantry_composition(restored):
            self.assertIsInstance(size, int)
            self.assertIsInstance(count, int)

    def test_capacities_expand_in_configuration_order(self):
        self.assertEqual(utils.infantry_capacities(_event([[6, 3], [8, 2]])),
                         [6, 6, 6, 8, 8])

    def test_player_capacity_sums_every_squad(self):
        ev = _event([[6, 10], [8, 4]])          # 60 + 32
        self.assertEqual(utils.player_capacity(ev), 60 + 32 + 2 * 2 + 1 * 1)

    def test_max_squads_for_type_counts_the_composition(self):
        self.assertEqual(utils._max_squads_for_type(_event([[6, 10], [8, 4]]), "infantry"), 14)

    def test_default_size_is_the_first_entry(self):
        self.assertEqual(utils._squad_size_for_type(_event([[7, 2], [9, 2]]), "infantry"), 7)
        self.assertEqual(utils._squad_size_for_type(_event([]), "infantry"), 6)


class DefaultCompositionTest(unittest.TestCase):

    def test_guild_default_still_adds_up_to_a_full_server(self):
        """The shipped default must reproduce the pre-refactor 100-slot event."""
        ev = database.build_default_event(
            database.DEFAULT_GUILD_SETTINGS, "E", "01.01.2030", "20:00")
        self.assertEqual(utils.player_capacity(ev) + ev["max_caster_slots"], 100)
        self.assertEqual(utils._max_squads_for_type(ev, "infantry"), 14)


# ---------------------------------------------------------------------------
# Per-size quotas (rep mode)
# ---------------------------------------------------------------------------

class SizeQuotaTest(unittest.TestCase):

    def test_remaining_is_quota_minus_registered_per_size(self):
        ev = _event([[6, 4], [8, 2]], squads={"a": _squad(6), "b": _squad(8)})
        self.assertEqual(utils.infantry_size_options(ev), [(6, 3), (8, 1)])

    def test_sizes_are_independent(self):
        """The whole point of the inversion: filling one size must not consume
        another's capacity, which is what the old shared pool did."""
        ev = _event([[6, 2], [8, 2]], squads={"a": _squad(6), "b": _squad(6)})
        self.assertEqual(dict(utils.infantry_size_options(ev))[8], 2)

    def test_exhausted_extra_sizes_drop_out_but_the_default_stays(self):
        ev = _event([[6, 1], [8, 1]], squads={"a": _squad(6), "b": _squad(8)})
        options = utils.infantry_size_options(ev)
        self.assertEqual(options, [(6, 0)])

    def test_a_size_with_no_quota_never_becomes_a_phantom_option(self):
        """/admin_edit_squad can set a size the composition does not contain;
        it must not surface as an option or push a count negative."""
        ev = _event([[6, 2]], squads={"a": _squad(9), "b": _squad(9), "c": _squad(9)})
        self.assertEqual(utils.infantry_size_options(ev), [(6, 2)])

    def test_quota_below_registered_clamps_at_zero(self):
        ev = _event([[6, 1]], squads={"a": _squad(6), "b": _squad(6)})
        self.assertEqual(utils.infantry_size_options(ev), [(6, 0)])


class SquadTypeFullTest(unittest.TestCase):

    def test_infantry_is_full_per_size(self):
        ev = _event([[6, 1], [8, 2]], squads={"a": _squad(6)})
        self.assertTrue(botmod._is_squad_type_full(ev, "infantry", 6))
        self.assertFalse(botmod._is_squad_type_full(ev, "infantry", 8))

    def test_without_a_size_the_type_is_full_only_when_nothing_is_left(self):
        ev = _event([[6, 1], [8, 1]], squads={"a": _squad(6)})
        self.assertFalse(botmod._is_squad_type_full(ev, "infantry"))
        ev["squads"]["b"] = _squad(8)
        self.assertTrue(botmod._is_squad_type_full(ev, "infantry"))

    def test_vehicle_and_heli_stay_a_plain_count(self):
        ev = _event(max_vehicle_squads=1, squads={"v": _squad(2, "vehicle")})
        self.assertTrue(botmod._is_squad_type_full(ev, "vehicle"))
        self.assertFalse(botmod._is_squad_type_full(ev, "heli"))

    def test_configured_check_separates_exhausted_from_absent(self):
        ev = _event([[6, 0], [8, 2]])
        self.assertTrue(botmod._infantry_size_configured(ev, 6))
        self.assertFalse(botmod._infantry_size_configured(ev, 7))


class SelectPlumbingTest(unittest.TestCase):

    def test_one_option_per_extra_size(self):
        ev = _event([[6, 4], [8, 2]])
        values = [o.value for o in botmod._squad_type_options(ev, "en")]
        self.assertIn("infantry", values)
        self.assertIn("infantry:8", values)

    def test_value_round_trips(self):
        self.assertEqual(botmod._parse_squad_type_value("infantry:8"), ("infantry", 8))
        self.assertEqual(botmod._parse_squad_type_value("vehicle"), ("vehicle", None))


# ---------------------------------------------------------------------------
# Waitlist promotion under quotas
# ---------------------------------------------------------------------------

class WaitlistQuotaTest(unittest.IsolatedAsyncioTestCase):
    """Promotion follows the freed size's own quota, not a shared seat budget."""

    def setUp(self):
        self.saved = []
        self._orig = botmod.save_event
        botmod.save_event = lambda db, ev, ua: self.saved.append(ev)
        self.addCleanup(setattr, botmod, "save_event", self._orig)
        self._orig_dm = botmod._send_squad_dm
        self._orig_log = botmod.send_to_log_channel

        async def _noop(*a, **kw):
            return None

        botmod._send_squad_dm = _noop
        botmod.send_to_log_channel = _noop
        self.addCleanup(setattr, botmod, "_send_squad_dm", self._orig_dm)
        self.addCleanup(setattr, botmod, "send_to_log_channel", self._orig_log)

    async def test_a_freed_small_squad_does_not_block_a_waiting_bigger_one(self):
        """The old promoter compared the waiting squad's size against the freed
        SEATS, so a size-6 unregistration stranded a waiting size-8 squad even
        though the size-8 quota was untouched."""
        ev = _event([[6, 1], [8, 1]], squads={"a": _squad(6)})
        ev["infantry_waitlist"] = [("Big", "infantry", None, 8, "big", "Rep")]
        await botmod._process_squad_waitlist(ev, {}, 1, 1, 2, free_slots=6, freed_type="infantry")
        self.assertIn("big", ev["squads"])
        self.assertEqual(ev["infantry_waitlist"], [])

    async def test_promotion_stops_at_the_size_quota(self):
        ev = _event([[6, 1]], squads={})
        ev["infantry_waitlist"] = [("A", "infantry", None, 6, "a", "R"),
                                   ("B", "infantry", None, 6, "b", "R")]
        await botmod._process_squad_waitlist(ev, {}, 1, 1, 2, free_slots=6, freed_type="infantry")
        self.assertEqual(len(ev["squads"]), 1)
        self.assertEqual(len(ev["infantry_waitlist"]), 1)

    async def test_an_unconfigured_size_is_left_waiting(self):
        ev = _event([[6, 4]], squads={})
        ev["infantry_waitlist"] = [("Odd", "infantry", None, 9, "odd", "R")]
        await botmod._process_squad_waitlist(ev, {}, 1, 1, 2, free_slots=9, freed_type="infantry")
        self.assertEqual(ev["squads"], {})
        self.assertEqual(len(ev["infantry_waitlist"]), 1)


# ---------------------------------------------------------------------------
# Editor guards and the advisory capacity warning
# ---------------------------------------------------------------------------

class CompositionEditGuardTest(unittest.TestCase):

    def test_rejects_a_size_above_the_game_limit(self):
        ok, err = botmod._apply_property_change(
            _event(), "infantry_squads", "composition", None, [[10, 2]], "en")
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_rep_mode_refuses_to_strand_registered_squads(self):
        ev = _event([[6, 2]], squads={"a": _squad(6), "b": _squad(6)})
        ok, err = botmod._apply_property_change(
            ev, "infantry_squads", "composition", None, [[8, 2]], "en")
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_rep_mode_refuses_to_strand_waitlisted_squads(self):
        ev = _event([[6, 1], [8, 2]])
        ev["infantry_waitlist"] = [("W", "infantry", None, 8, "w", "R")]
        ok, _err = botmod._apply_property_change(
            ev, "infantry_squads", "composition", None, [[6, 1]], "en")
        self.assertFalse(ok)

    def test_growing_a_quota_is_fine(self):
        ev = _event([[6, 2]], squads={"a": _squad(6)})
        ok, err = botmod._apply_property_change(
            ev, "infantry_squads", "composition", None, [[6, 4], [8, 2]], "en")
        self.assertTrue(ok, err)


class CapacityWarningTest(unittest.TestCase):
    """Advisory only — it must never be able to block a save."""

    def test_warns_above_the_guild_limit(self):
        ev = _event([[9, 12]])   # 108 + 4 + 1 + 2 casters
        warning = botmod.capacity_warning(ev, {"capacity_warning_limit": 100}, "en")
        self.assertIsNotNone(warning)
        self.assertIn("100", warning)

    def test_silent_at_or_below_the_limit(self):
        ev = _event([[6, 4]])
        self.assertIsNone(botmod.capacity_warning(ev, {"capacity_warning_limit": 100}, "en"))

    def test_zero_disables_the_check(self):
        ev = _event([[9, 20]])
        self.assertIsNone(botmod.capacity_warning(ev, {"capacity_warning_limit": 0}, "en"))

    def test_an_over_limit_composition_still_saves(self):
        ev = _event([[6, 4]])
        ok, err = botmod._apply_property_change(
            ev, "infantry_squads", "composition", None, [[9, 20]], "en")
        self.assertTrue(ok, err)


# ---------------------------------------------------------------------------
# Migration from the derived model
# ---------------------------------------------------------------------------

class PreCompositionEventTest(unittest.TestCase):
    """There is no migration from the derived model — the capacity concept was
    inverted and old events are meant to be recreated. An event that still lacks
    a composition must therefore fail obviously, not silently mis-size."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.addCleanup(lambda: [os.unlink(tmp.name + s)
                                 for s in ("", "-wal", "-shm") if os.path.exists(tmp.name + s)])
        self.addCleanup(setattr, database, "DB_FILE", database.DB_FILE)
        database.DB_FILE = tmp.name
        database.init_db()

    def _write(self, event, status="active"):
        import sqlite3
        conn = sqlite3.connect(database.DB_FILE)
        with conn:
            cur = conn.execute(
                "INSERT INTO events (guild_id, channel_id, event_data, user_assignments, status)"
                " VALUES (1, 2, ?, '{}', ?)", (json.dumps(event), status))
            db_id = cur.lastrowid
        conn.close()
        return db_id

    def test_an_event_without_a_composition_has_no_capacity(self):
        ev = {"name": "Legacy", "mode": "rep", "server_max_players": 100,
              "infantry_squad_size": 6, "squads": {}}
        self.assertEqual(utils.infantry_composition(ev), [])
        self.assertEqual(utils._max_squads_for_type(ev, "infantry"), 0)
        self.assertEqual(utils.player_capacity(ev), 0)

    def test_boot_warns_about_stored_pre_composition_events(self):
        self._write({"name": "Legacy", "server_max_players": 100})
        with self.assertLogs("event_bot.db", level="WARNING") as captured:
            database.init_db()
        self.assertTrue(any("predate the squad-composition model" in m for m in captured.output))

    def test_no_warning_once_every_event_has_one(self):
        self._write(_event([[6, 4]]))
        import logging
        with self.assertNoLogs("event_bot.db", level="WARNING"):
            database.init_db()

    def test_archived_events_are_not_flagged(self):
        """Only active events matter — deleted/expired ones are never served."""
        self._write({"name": "Old", "server_max_players": 100}, status="expired_1")
        with self.assertNoLogs("event_bot.db", level="WARNING"):
            database.init_db()


class I18nKeyTest(unittest.TestCase):

    def test_new_keys_exist_in_both_languages(self):
        for key in ("edit.property.infantry_squads", "edit.composition_hint",
                    "edit.composition_current", "edit.composition_pick_size",
                    "edit.composition_size_option", "edit.composition_pick_count",
                    "edit.composition_count_option", "edit.composition_below_registered",
                    "edit.capacity_over_limit", "config_defaults.prop.infantry_squads",
                    "config_defaults.prop.capacity_warning_limit",
                    "wizard.summary_total", "wizard.infantry_title", "wizard.infantry_desc",
                    "wizard.vehicles_title", "wizard.vehicles_desc",
                    "wizard.pick_vehicle_count", "wizard.pick_vehicle_size",
                    "wizard.pick_heli_count", "wizard.pick_heli_size",
                    "wizard.pick_caster_slots"):
            self.assertEqual(set(_STRINGS[key]), {"de", "en"}, key)

    def test_removed_keys_are_gone(self):
        """The don't-waste subsystem left 21 strings behind; none may linger."""
        self.assertFalse([k for k in _STRINGS if "dont_waste" in k])
        for key in ("settings.server_max_players", "squad.waitlisted_mirror",
                    "edit.recalculated", "embed.server_overview_value"):
            self.assertNotIn(key, _STRINGS)

    def test_composition_renders(self):
        for lang in ("de", "en"):
            self.assertEqual(botmod._format_composition([[6, 10], [8, 4]], lang),
                             "10 × 6, 4 × 8")


if __name__ == "__main__":
    unittest.main()
