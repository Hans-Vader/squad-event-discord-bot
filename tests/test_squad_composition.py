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
from datetime import datetime

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


class _FakeResponse:
    def __init__(self):
        self.edits = []
        self.modals = []
        self.messages = []

    async def edit_message(self, **kw):
        self.edits.append(kw)

    async def send_message(self, *a, **kw):
        self.messages.append((a, kw))
        self.edits.append(kw)

    async def send_modal(self, modal):
        self.modals.append(modal)

    async def defer(self):
        pass


class _FakeInteraction:
    def __init__(self, value=None):
        self.response = _FakeResponse()
        self.data = {"values": [str(value)]} if value is not None else {}
        self.user = types.SimpleNamespace(id=7, name="organizer", display_name="Organizer")
        self.message = None      # BaseView.check_response stores it


class _WizardTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = dict(database.DEFAULT_GUILD_SETTINGS)
        self.event = database.build_default_event(
            self.settings, "Cup", "01.01.2030", "20:00", mode="rep")
        for name, repl in (("get_guild_settings", lambda _gid: dict(self.settings)),
                           ("get_guild_language", lambda _gid: "de")):
            self.addCleanup(setattr, botmod, name, getattr(botmod, name))
            setattr(botmod, name, repl)
        botmod._wizard_history.clear()
        self.addCleanup(botmod._wizard_history.clear)

    def cap(self, **kw):
        return botmod.WizardCapacityView(1, 2, self.event, {}, self.settings, USER, **kw)


class _User:
    id = 7
    name = "organizer"
    display_name = "Organizer"


USER = _User()


class CapacityStepTest(_WizardTestBase):
    """One step configures the whole capacity: group -> size -> count.

    Vehicle and heli squads are the same shape as an infantry entry, so they get
    the same three controls; the old four separate fields were an artifact of the
    5-input modal this replaced.
    """

    def _select(self, view, row):
        return next(c for c in view.children if getattr(c, "row", None) == row and hasattr(c, "options"))

    def test_fits_discords_action_row_and_option_budget(self):
        for group in ("infantry", "vehicle", "heli", "caster"):
            view = self.cap(group=group)
            self.assertLessEqual(max(c.row for c in view.children), 4, group)
            for child in view.children:
                if hasattr(child, "options"):
                    self.assertLessEqual(len(child.options), 25, group)

    def test_still_fits_with_a_composition_of_many_sizes(self):
        self.event["infantry_squads"] = [[s, 2] for s in range(1, 10)]
        view = self.cap()
        self.assertLessEqual(max(c.row for c in view.children), 4)
        for child in view.children:
            if hasattr(child, "options"):
                self.assertLessEqual(len(child.options), 25)

    def test_no_option_is_a_bare_number(self):
        """The regression this step exists to fix: a chosen option's label
        replaces the placeholder, so '4' on its own tells the user nothing."""
        for group in ("infantry", "vehicle", "heli", "caster"):
            for child in self.cap(group=group).children:
                for opt in getattr(child, "options", []):
                    self.assertFalse(opt.label.strip().isdigit(),
                                     f"{group}: bare numeric option {opt.label!r}")

    def test_capacity_table_and_total_are_shown(self):
        _content, embed = self.cap().step_body()
        self.assertIn("Gesamt", embed.description)
        self.assertIn("100", embed.description)

    async def test_every_pick_updates_the_shown_total(self):
        view = self.cap(group="vehicle")
        i = _FakeInteraction(10)
        await view._on_count(i)
        embed = i.response.edits[0]["embed"]
        self.assertEqual(self.event["max_vehicle_squads"], 10)
        # 84 infantry + 10x2 vehicles + 2 helis + 2 casters
        self.assertIn("108", embed.description)

    def test_casters_are_rep_mode_only(self):
        self.assertIn("caster", [o.value for o in self.cap().children[0].options])
        self.event["mode"] = "player"
        self.assertNotIn("caster", [o.value for o in self.cap().children[0].options])

    def test_casters_have_no_size_select(self):
        size_select = self._select(self.cap(group="caster"), 1)
        self.assertTrue(size_select.disabled)

    # ── each group writes to its own keys ─────────────────────────────────
    async def test_infantry_count_edits_the_composition(self):
        view = self.cap(group="infantry", size=8)
        await view._on_count(_FakeInteraction(4))
        self.assertEqual(self.event["infantry_squads"], [[6, 14], [8, 4]])

    async def test_infantry_count_zero_removes_the_size(self):
        view = self.cap(group="infantry", size=6)
        await view._on_count(_FakeInteraction(0))
        self.assertEqual(self.event["infantry_squads"], [])

    async def test_vehicle_size_and_count_write_their_own_keys(self):
        view = self.cap(group="vehicle")
        await view._on_size(_FakeInteraction(3))
        self.assertEqual(self.event["vehicle_squad_size"], 3)
        view = self.cap(group="vehicle")
        await view._on_count(_FakeInteraction(8))
        self.assertEqual(self.event["max_vehicle_squads"], 8)

    async def test_heli_writes_its_own_keys(self):
        view = self.cap(group="heli")
        await view._on_size(_FakeInteraction(2))
        await self.cap(group="heli")._on_count(_FakeInteraction(4))
        self.assertEqual((self.event["heli_squad_size"], self.event["max_heli_squads"]), (2, 4))

    async def test_caster_count_writes_caster_slots(self):
        await self.cap(group="caster")._on_count(_FakeInteraction(5))
        self.assertEqual(self.event["max_caster_slots"], 5)

    async def test_infantry_size_pick_only_selects_which_entry_to_edit(self):
        """Infantry holds several sizes, so picking one must not change anything."""
        before = list(self.event["infantry_squads"])
        i = _FakeInteraction(9)
        await self.cap(group="infantry")._on_size(i)
        self.assertEqual(self.event["infantry_squads"], before)
        self.assertEqual(i.response.edits[0]["view"].size, 9)

    def test_the_warning_is_visible_while_configuring(self):
        self.event["infantry_squads"] = [[9, 20]]
        _content, embed = self.cap().step_body()
        self.assertTrue(embed.fields, "capacity warning should be shown on the step")

    def test_no_separate_vehicle_step_remains(self):
        for gone in ("WizardInfantryView", "WizardVehicleHeliView"):
            self.assertFalse(hasattr(botmod, gone), gone)


class WizardNavigationTest(_WizardTestBase):
    """Back must correct, not restart — and it works across every step."""

    async def test_back_from_capacity_reopens_the_basics_prefilled(self):
        botmod._wizard_push_step(USER, botmod._reopen_basics(
            1, 2, "rep", self.event, {}))
        i = _FakeInteraction()
        await self.cap().go_back(i)
        modal = i.response.modals[0]
        self.assertEqual(modal.event_name.default, "Cup")
        self.assertEqual(modal.event_time.default, "20:00")

    async def test_back_walks_the_whole_chain(self):
        cap = self.cap()
        i = _FakeInteraction()
        await cap._continue(i)                       # -> squad roles
        roles = i.response.edits[0]["view"]
        self.assertIsInstance(roles, botmod.WizardSquadRolesView)

        i = _FakeInteraction()
        await roles._skip(i)                         # -> caster roles (rep, no gate)
        caster = i.response.edits[0]["view"]
        self.assertIsInstance(caster, botmod.WizardCasterRolesView)

        i = _FakeInteraction()
        await caster.go_back(i)                      # back to squad roles
        self.assertIsInstance(i.response.edits[0]["view"], botmod.WizardSquadRolesView)

        back2 = _FakeInteraction()
        await roles.go_back(back2)                   # back to capacity
        self.assertIsInstance(back2.response.edits[0]["view"], botmod.WizardCapacityView)

    async def test_going_back_shows_current_values_not_a_stale_form(self):
        cap = self.cap()
        i = _FakeInteraction()
        await cap._continue(i)
        roles = i.response.edits[0]["view"]
        self.event["infantry_squads"] = [[8, 4]]     # changed behind the old view
        back = _FakeInteraction()
        await roles.go_back(back)
        self.assertIn("4 × 8", back.response.edits[0]["embed"].description)

    async def test_back_at_the_very_start_does_not_crash(self):
        i = _FakeInteraction()
        await self.cap().go_back(i)
        self.assertEqual(i.response.edits, [])

    async def test_a_fresh_submit_still_starts_a_new_event(self):
        modal = botmod.EventCreationModal(1, 2, "rep")
        modal.event_name._value = "Fresh"
        modal.event_date._value = "03.03.2030"
        modal.event_time._value = "19:00"
        modal.event_desc._value = ""
        modal.reg_start._value = "sofort"
        i = _FakeInteraction()
        await modal.on_submit(i)
        self.assertIsInstance(i.response.edits[0]["view"], botmod.WizardCapacityView)

    async def test_resubmitting_the_basics_returns_to_the_capacity_step(self):
        modal = botmod.EventCreationModal(1, 2, "rep", event=self.event, user_assignments={})
        modal.event_name._value = "Renamed"
        modal.event_date._value = "02.02.2030"
        modal.event_time._value = "21:30"
        modal.event_desc._value = ""
        modal.reg_start._value = "sofort"
        i = _FakeInteraction()
        await modal.on_submit(i)
        self.assertEqual(self.event["name"], "Renamed")
        self.assertEqual(self.event["infantry_squads"], [[6, 14]])
        self.assertIsInstance(i.response.edits[0]["view"], botmod.WizardCapacityView)

    def test_registration_start_round_trips_through_the_modal(self):
        from datetime import datetime as _dt
        self.assertEqual(
            botmod._reg_start_text({"registration_start_time": _dt(2030, 2, 1, 19, 5)}),
            "01.02.2030 19:05")
        self.assertEqual(botmod._reg_start_text({"registration_open": True}), "sofort")
        self.assertEqual(botmod._reg_start_text({}), "")
        self.assertIsNotNone(utils.parse_registration_start("01.02.2030 19:05"))


class WizardStepConsistencyTest(_WizardTestBase):
    """House rules every step has to follow."""

    STEPS = ("WizardCapacityView", "WizardSquadRolesView", "WizardSlotLimitsView",
             "WizardCasterRolesView", "WizardTimingView", "WizardSquadLimitView",
             "WizardPlayerRolesView", "WizardConfirmationView")

    def _views(self):
        for name in self.STEPS:
            yield name, getattr(botmod, name)(1, 2, self.event, {}, self.settings, USER)

    def test_every_step_shares_the_wizard_base(self):
        for name, view in self._views():
            self.assertIsInstance(view, botmod.WizardStepView, name)

    def test_every_step_renders_something(self):
        for name, view in self._views():
            content, embed = view.step_body()
            self.assertTrue(content or embed, name)

    def test_every_step_can_go_back(self):
        for name, view in self._views():
            labels = [c.label for c in view.children if hasattr(c, "label") and c.label]
            self.assertIn(t("general.back", "de"), labels, name)

    def test_skip_never_duplicates_continue(self):
        """Two buttons doing the same thing is worse than one — the vehicle step
        used to wire Skip and Continue to the identical callback."""
        for name, view in self._views():
            buttons = {c.label: c.callback for c in view.children if hasattr(c, "callback") and getattr(c, "label", None)}
            skip = buttons.get(t("general.skip", "de"))
            cont = buttons.get(t("wizard.continue", "de"))
            if skip is not None and cont is not None:
                self.assertNotEqual(getattr(skip, "__func__", skip),
                                    getattr(cont, "__func__", cont), name)

    def test_every_step_uses_the_long_timeout(self):
        """Nothing is persisted before the confirmation, so a short timeout
        silently throws the whole configuration away."""
        for name, view in self._views():
            self.assertEqual(view.timeout, botmod._WIZARD_TIMEOUT, name)


class WizardAuditRegressionTest(_WizardTestBase):
    """Defects a UX audit of the whole wizard turned up — each one user-visible."""

    def test_property_numbers_agree_between_overview_and_dropdown(self):
        """The numbers used to be baked into the i18n labels, so removing a
        property left the list saying `9.` and the dropdown saying `10.`."""
        for table in (botmod._EDIT_PROPERTIES, botmod._GUILD_EDIT_PROPERTIES):
            for num, key, label_key, _vtype, _special in table:
                label = t(label_key, "de")
                self.assertFalse(label.split(".")[0].strip().isdigit(),
                                 f"{key}: number baked into the label {label!r}")

    def test_labels_with_an_abbreviation_survive(self):
        """Guard for the trap in the old _prop_short_label: it split on the first
        '. ', so once the numeric prefix went away it ate real content."""
        self.assertEqual(t("edit.property.max_casters", "de"), "Max. Caster-Plätze")

    def test_mention_lists_cannot_overflow_the_embed_field(self):
        """Four mention lists share one 1024-char field and each select takes 25
        picks — unclamped, the finished wizard died with an HTTP 400."""
        many = list(range(100000000000000000, 100000000000000025))
        for key in ("squad_rep_role_ids", "community_rep_role_ids",
                    "caster_role_ids", "caster_community_role_ids"):
            self.event[key] = list(many)
        embed = botmod._build_confirmation_embed(self.event, 1, self.settings)
        for field in embed.fields:
            self.assertLessEqual(len(field.value), 1024, field.name)
        self.assertLessEqual(len(embed), 6000)

    def test_a_clamped_mention_list_never_cuts_a_mention_in_half(self):
        """Clamp the list of mentions, not the joined string — a string cut lands
        mid-mention and Discord renders the raw `<@&123`."""
        import re as _re
        self.event["squad_rep_role_ids"] = list(range(100000000000000000, 100000000000000025))
        embed = botmod._build_confirmation_embed(self.event, 1, self.settings)
        joined = "\n".join(f.value for f in embed.fields)
        # every mention opener must be a complete, closed mention
        self.assertEqual(joined.count("<@"), len(_re.findall(r"<@&?\d+>", joined)))

    def test_the_ping_question_is_asked_exactly_once(self):
        """It used to be on two steps, and in rep mode the second silently
        overwrote the first depending on Skip vs Continue."""
        asking = []
        for name in ("WizardSquadRolesView", "WizardCasterRolesView"):
            view = getattr(botmod, name)(1, 2, self.event, {}, self.settings, USER)
            if any(getattr(c, "placeholder", None) == t("wizard.ping_select_title", "de")
                   for c in view.children):
                asking.append(name)
        self.assertEqual(asking, ["WizardSquadRolesView"])

    def test_the_ping_is_reachable_for_an_immediately_open_event(self):
        """The question used to be hidden when registration was already open —
        but that is exactly the case where _confirm pings on creation."""
        self.event["registration_open"] = True
        view = botmod.WizardSquadRolesView(1, 2, self.event, {}, self.settings, USER)
        self.assertIsNotNone(view.ping_select)

    def test_squad_limit_options_are_localized(self):
        view = botmod.WizardSquadLimitView(1, 2, self.event, {}, self.settings, USER)
        labels = [o.label for o in view.limit_select.options]
        self.assertEqual(labels[0], botmod._format_squads_per_user(1, "de"))
        self.assertNotIn("1 Squad", labels[1:])

    async def test_an_event_without_a_single_seat_cannot_be_created(self):
        self.event["infantry_squads"] = []
        self.event["max_vehicle_squads"] = 0
        self.event["max_heli_squads"] = 0
        self.event["max_caster_slots"] = 0
        view = botmod.WizardConfirmationView(1, 2, self.event, {}, self.settings, USER)
        i = _FakeInteraction()
        await view._confirm(i)
        self.assertTrue(i.response.messages, "creating a zero-capacity event must be refused")
        self.assertEqual(len(i.response.edits), 1)   # only the refusal, no teardown

    def test_confirmation_puts_the_forward_action_last(self):
        view = botmod.WizardConfirmationView(1, 2, self.event, {}, self.settings, USER)
        labels = [c.label for c in view.children if getattr(c, "label", None)]
        self.assertEqual(labels[-1], t("general.confirm", "de"))
        self.assertEqual(labels[0], t("general.back", "de"))


class CountdownDisplayTest(_WizardTestBase):
    """`countdown_seconds = None` means "inherit the guild default", but both the
    picker and the summary showed it as "no countdown" — the organizer was told
    the opposite of what would happen."""

    def setUp(self):
        super().setUp()
        self.event["registration_start_time"] = datetime(2030, 1, 1, 19, 0)

    def _timing(self):
        return botmod.WizardTimingView(1, 2, self.event, {}, self.settings, USER)

    def _picked(self, view):
        return [o.value for o in view.countdown_select.options if o.default]

    def test_unset_preselects_the_guild_default(self):
        self.event["countdown_seconds"] = None
        self.settings["registration_countdown_seconds"] = 300
        self.assertEqual(self._picked(self._timing()), ["300"])

    def test_an_explicit_zero_still_means_no_countdown(self):
        self.event["countdown_seconds"] = 0
        self.settings["registration_countdown_seconds"] = 300
        self.assertEqual(self._picked(self._timing()), ["0"])
        self.assertEqual(botmod._format_countdown(0, "de"), t("wizard.countdown_none", "de"))

    def test_the_summary_agrees_with_the_picker(self):
        self.event["countdown_seconds"] = None
        self.settings["registration_countdown_seconds"] = 900
        embed = botmod._build_confirmation_embed(self.event, 1, self.settings)
        value = next(f.value for f in embed.fields if f.name == t("wizard.summary_countdown", "de"))
        self.assertEqual(value, botmod._format_countdown(900, "de"))
        self.assertNotEqual(value, t("wizard.countdown_none", "de"))

    def test_every_offered_value_has_a_real_label(self):
        """The guild editor and the wizard used to offer different value sets, so
        a guild could store a countdown the wizard could not name."""
        for seconds in botmod._COUNTDOWN_PRESETS:
            for lang in ("de", "en"):
                self.assertNotIn("missing", botmod._format_countdown(seconds, lang))

    def test_a_value_without_its_own_label_falls_back_to_seconds(self):
        self.assertEqual(botmod._format_countdown(37, "de"), t("edit.seconds", "de", count=37))


class WizardTextQualityTest(unittest.TestCase):
    """Step copy a first-time organizer actually reads."""

    def test_slot_limits_description_is_grammatical_and_mode_agnostic(self):
        for lang in ("de", "en"):
            text = t("wizard.slot_limits_desc", lang)
            self.assertNotIn("•", text, "bullets named three dropdowns; player mode shows one")
            self.assertNotIn("Optional Anmeldegruppe Limitierung", text)
            self.assertNotIn("Optionally registration group cap", text)

    def test_no_step_docstring_claims_a_step_number(self):
        """Numbers drifted every time a step was added or merged, and the
        conditional steps make a fixed number wrong anyway."""
        import inspect
        for name in ("WizardCapacityView", "WizardSquadRolesView", "WizardSlotLimitsView",
                     "WizardCasterRolesView", "WizardTimingView", "WizardSquadLimitView",
                     "WizardPlayerRolesView", "WizardConfirmationView"):
            doc = inspect.getdoc(getattr(botmod, name)) or ""
            self.assertNotRegex(doc, r"^Step \d", name)


class CapacityTableTest(unittest.TestCase):
    """The table is the capacity breakdown — a group missing from it reads as a
    missing figure, not as a zero."""

    def _event(self, **kw):
        return database.build_default_event(
            dict(database.DEFAULT_GUILD_SETTINGS), "C", "01.01.2030", "20:00", **kw)

    def _rows(self, event):
        return [l for l in botmod._capacity_table(event, "de").strip("`\n").splitlines()
                if l and not l.startswith("─")]

    def test_every_group_has_a_row_even_at_zero(self):
        """Hiding empty groups made a deliberate 'no casters' indistinguishable
        from a figure that was simply absent."""
        event = self._event(mode="rep", max_caster_slots=0,
                            max_vehicle_squads=0, max_heli_squads=0)
        rows = self._rows(event)
        for label in ("Infanterie", "Fahrzeug", "Heli", "Caster"):
            self.assertTrue(any(r.startswith(label) for r in rows), f"{label} missing\n" + "\n".join(rows))

    def test_the_caster_row_states_its_count(self):
        event = self._event(mode="rep", max_caster_slots=3)
        caster_row = next(r for r in self._rows(event) if r.startswith("Caster"))
        self.assertIn("3", caster_row)
        # count column and seats column, not one lonely number in the seats column
        self.assertEqual(caster_row.split(), ["Caster", "3", "3"])

    def test_zero_casters_shows_a_zero_rather_than_vanishing(self):
        caster_row = next(r for r in self._rows(self._event(mode="rep", max_caster_slots=0))
                          if r.startswith("Caster"))
        self.assertEqual(caster_row.split(), ["Caster", "0", "0"])

    def test_player_mode_has_no_caster_row_at_all(self):
        """There casters are not zero — they do not exist as a concept."""
        rows = self._rows(self._event(mode="player", max_caster_slots=0))
        self.assertFalse(any(r.startswith("Caster") for r in rows))

    def test_rows_do_not_appear_and_vanish_while_configuring(self):
        """Stable rows: setting a group to 0 in the wizard must not make the
        table jump under the organizer."""
        full = self._rows(self._event(mode="rep"))
        emptied = self._rows(self._event(mode="rep", max_vehicle_squads=0, max_heli_squads=0))
        self.assertEqual(len(full), len(emptied))

    def test_an_empty_infantry_composition_still_shows_the_group(self):
        event = self._event(mode="rep")
        event["infantry_squads"] = []
        self.assertTrue(any(r.startswith("Infanterie") for r in self._rows(event)))

    def test_the_total_matches_the_rows(self):
        for kw in ({"mode": "rep"}, {"mode": "rep", "max_caster_slots": 0},
                   {"mode": "player", "max_caster_slots": 0}):
            event = self._event(**kw)
            rows = self._rows(event)
            seats = sum(int(r.split()[-1]) for r in rows[:-1])
            self.assertEqual(int(rows[-1].split()[-1]), seats, kw)


class I18nKeyTest(unittest.TestCase):

    def test_new_keys_exist_in_both_languages(self):
        for key in ("edit.property.infantry_squads", "edit.composition_hint",
                    "edit.composition_current", "edit.composition_pick_size",
                    "edit.composition_size_option", "edit.composition_pick_count",
                    "edit.composition_count_option", "edit.composition_below_registered",
                    "edit.capacity_over_limit", "config_defaults.prop.infantry_squads",
                    "config_defaults.prop.capacity_warning_limit",
                    "wizard.summary_total", "wizard.capacity_title", "wizard.capacity_hint",
                    "wizard.capacity_pick_group", "wizard.capacity_pick_size",
                    "wizard.capacity_pick_count", "wizard.capacity_no_size",
                    "wizard.capacity_group_squads", "wizard.capacity_group_casters",
                    "wizard.capacity_size_slot", "wizard.capacity_size_fixed",
                    "wizard.capacity_count_many", "wizard.capacity_count_casters",
                    "wizard.timed_out"):
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
