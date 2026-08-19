#!/usr/bin/env python3
"""Unit tests for capacity changes on a running player-mode event.

A squad's `size` is frozen when the squad is created, so editing an event's
squad size / seat budget afterwards used to leave the roster untouched.
`_resize_player_squads` re-fits existing squads to the current capacity, sheds
the last-joined members onto the FRONT of the waitlist when capacity shrinks,
and re-runs the waitlist when it grows.
"""

import copy
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


def _event(**over):
    """The reported setup: 2 infantry squads of 6 plus 1 vehicle squad of 2."""
    ev = {
        "name": "Test Event",
        "mode": "player",
        "max_caster_slots": 2,
        "infantry_squads": [[6, 2]],
        "vehicle_squad_size": 2,
        "heli_squad_size": 1,
        "max_vehicle_squads": 1,
        "max_heli_squads": 0,
        "squads": {},
        "player_slots_used": 0,
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
        "declined": [],
    }
    ev.update(over)
    return ev


def _seed(ev, ua, n_inf=16, n_veh=3):
    """Register players through the real registration path so squads, seats and
    waitlists end up exactly as they would in production."""
    for i in range(n_inf):
        utils._player_register(ev, ua, f"i{i}", f"Inf{i}", "infantry")
    for i in range(n_veh):
        utils._player_register(ev, ua, f"v{i}", f"Veh{i}", "vehicle")
    return ev, ua


def _names(squad):
    return [m["name"] for m in squad["members"]]


def _wl_names(ev, st="infantry"):
    return [e[5] for e in ev[f"{st}_waitlist"]]


class ResizeTest(unittest.TestCase):

    def setUp(self):
        self.ev, self.ua = _seed(_event(), {})

    def test_fixture_matches_reported_setup(self):
        ev = self.ev
        self.assertEqual(sorted(ev["squads"]), ["Infantry 1", "Infantry 2", "Vehicle 1"])
        self.assertEqual(ev["squads"]["Infantry 1"]["size"], 6)
        self.assertEqual(len(ev["squads"]["Infantry 1"]["members"]), 6)
        self.assertEqual(len(ev["squads"]["Vehicle 1"]["members"]), 2)
        self.assertEqual(_wl_names(self.ev), ["Inf12", "Inf13", "Inf14", "Inf15"])
        self.assertEqual(_wl_names(self.ev, "vehicle"), ["Veh2"])
        self.assertEqual(self.ev["player_slots_used"], 14)

    # ── growing ────────────────────────────────────────────────────────────
    def test_grow_pulls_the_whole_waitlist_in(self):
        self.ev["infantry_squads"] = [[8, 2]]
        promoted, displaced = utils._resize_player_squads(self.ev, self.ua, "infantry")

        self.assertEqual(displaced, [])
        self.assertEqual([p[1] for p in promoted], ["Inf12", "Inf13", "Inf14", "Inf15"])
        self.assertEqual(self.ev["infantry_waitlist"], [])
        self.assertEqual(self.ev["squads"]["Infantry 1"]["size"], 8)
        self.assertEqual(self.ev["squads"]["Infantry 2"]["size"], 8)
        self.assertEqual(len(self.ev["squads"]["Infantry 2"]["members"]), 8)
        self.assertEqual(self.ev["player_slots_used"], 18)
        for uid, name, squad in promoted:
            self.assertEqual(self.ua[uid], [squad])

    def test_grow_other_type_runs_that_types_waitlist(self):
        self.ev["max_vehicle_squads"] = 2
        promoted, displaced = utils._resize_player_squads(self.ev, self.ua, "vehicle")

        self.assertEqual(displaced, [])
        self.assertEqual([p[1] for p in promoted], ["Veh2"])
        self.assertEqual(self.ev["vehicle_waitlist"], [])
        self.assertEqual(self.ua["v2"], ["Vehicle 2"])

    # ── shrinking ──────────────────────────────────────────────────────────
    def test_shrink_sheds_last_joined_to_the_front_of_the_waitlist(self):
        self.ev["infantry_squads"] = [[8, 2]]
        utils._resize_player_squads(self.ev, self.ua, "infantry")
        # Fresh arrivals queue up behind the now-seated players.
        utils._player_register(self.ev, self.ua, "late", "Late", "infantry")

        self.ev["infantry_squads"] = [[6, 2]]
        promoted, displaced = utils._resize_player_squads(self.ev, self.ua, "infantry")

        self.assertEqual(promoted, [])
        shed = [d[1] for d in displaced]
        self.assertEqual(len(shed), 4)
        # Within each squad the two last-joined members go, in join order.
        self.assertEqual(shed, ["Inf12", "Inf13", "Inf14", "Inf15"])
        # ...and they land ahead of the player who queued up later.
        self.assertEqual(_wl_names(self.ev), shed + ["Late"])
        for uid, _name, _squad in displaced:
            self.assertNotIn(uid, self.ua)
        self.assertEqual(self.ev["squads"]["Infantry 1"]["size"], 6)
        self.assertEqual(self.ev["player_slots_used"], 14)

    def test_shrinking_the_squad_cap_dissolves_surplus_squads(self):
        # 16 infantry seats: at size 4 the cap is 4 squads, at size 8 it is 2.
        ev, ua = _seed(_event(infantry_squads=[[4, 4]]), {})
        self.assertEqual(len([s for s in ev["squads"].values()
                              if s["type"] == "infantry"]), 4)
        ev["infantry_squads"] = [[8, 2]]
        promoted, displaced = utils._resize_player_squads(ev, ua, "infantry")

        inf = [n for n, s in ev["squads"].items() if s["type"] == "infantry"]
        self.assertEqual(sorted(inf), ["Infantry 1", "Infantry 2"])
        self.assertEqual(len(ev["squads"]["Infantry 1"]["members"]), 8)
        self.assertEqual(len(ev["squads"]["Infantry 2"]["members"]), 8)
        # Same 16 seats, so everyone keeps a spot — just in fewer, bigger squads.
        self.assertEqual(ev["infantry_waitlist"], [])
        self.assertEqual(ev["player_slots_used"], 18)
        self.assertEqual({d[0] for d in displaced} - {p[0] for p in promoted}, set())

    # ── invariants ─────────────────────────────────────────────────────────
    def test_round_trip_restores_the_exact_starting_state(self):
        before = (
            {n: (s["size"], _names(s)) for n, s in self.ev["squads"].items()},
            dict(self.ua),
            list(self.ev["infantry_waitlist"]),
            self.ev["player_slots_used"],
        )
        for size in (8, 6):
            self.ev["infantry_squad_size"] = size
            utils._resize_player_squads(self.ev, self.ua, "infantry")
        after = (
            {n: (s["size"], _names(s)) for n, s in self.ev["squads"].items()},
            dict(self.ua),
            list(self.ev["infantry_waitlist"]),
            self.ev["player_slots_used"],
        )
        self.assertEqual(after, before)

    def test_no_capacity_change_is_a_no_op(self):
        for _ in range(2):
            promoted, displaced = utils._resize_player_squads(self.ev, self.ua, "infantry")
            self.assertEqual((promoted, displaced), ([], []))
        self.assertEqual(_wl_names(self.ev), ["Inf12", "Inf13", "Inf14", "Inf15"])
        self.assertEqual(self.ev["player_slots_used"], 14)


class ResizeMixedCompositionTest(unittest.TestCase):
    """A composition can hold several sizes; squads are created and resized in
    configuration order, so the layout follows the table the organizer set."""

    def test_capacities_follow_the_configured_order(self):
        ev, ua = _seed(_event(infantry_squads=[[6, 2]], max_vehicle_squads=0), {},
                       n_inf=30, n_veh=0)
        ev["infantry_squads"] = [[6, 2], [8, 2]]
        utils._resize_player_squads(ev, ua, "infantry")
        inf = sorted((n for n, s in ev["squads"].items() if s["type"] == "infantry"),
                     key=utils._squad_number_key)
        self.assertEqual([ev["squads"][n]["size"] for n in inf], [6, 6, 8, 8])
        self.assertEqual(utils.player_capacity(ev), 28)

    def test_dropping_a_size_sheds_only_that_size(self):
        ev, ua = _seed(_event(infantry_squads=[[6, 2], [8, 2]], max_vehicle_squads=0), {},
                       n_inf=28, n_veh=0)
        ev["infantry_squads"] = [[6, 2]]
        _promoted, displaced = utils._resize_player_squads(ev, ua, "infantry")
        self.assertEqual(len(displaced), 16)
        self.assertEqual(utils.player_capacity(ev), 12)


class _StubInteraction:
    """_apply_edit only ever touches interaction.user.name on the persist path."""
    user = types.SimpleNamespace(name="organizer")


class _StubTarget:
    kind = "event"

    def __init__(self):
        self.calls = []

    async def persist(self, *a, **kw):
        self.calls.append((a, kw))
        return "ok", None


class ShrinkConfirmTest(unittest.IsolatedAsyncioTestCase):
    """A capacity edit that evicts seated players must ask first — the rest of the
    editor applies immediately, and there is no undo for an eviction.

    The gate lives inside `_persist_event_edit`'s guild lock so the list shown to
    the organizer is the one that gets applied, and so every caller of persist is
    covered rather than just the button path.
    """

    def setUp(self):
        import bot as botmod
        self.bot = botmod
        self.ev, self.ua = _seed(_event(), {})
        self.saved = []

        async def _noop(*a, **kw):
            pass

        def _fire(coro):
            coro.close()

        # _get_event_by_dbid re-reads and re-parses the row on every call, so each
        # load is a private copy. The whole "an unconfirmed shrink discards its dry
        # run by simply not saving" contract rests on that — model it, don't hand
        # back the same object twice or the tests would pass on a broken gate.
        def _load(_gid, db):
            return copy.deepcopy(self.ev), copy.deepcopy(self.ua), db

        def _save(db, ev, ua):
            self.saved.append((db, copy.deepcopy(ev), copy.deepcopy(ua)))
            self.ev, self.ua = ev, ua

        patches = {
            "_get_event_by_dbid": _load,
            "save_event": _save,
            "update_event_displays": _noop,
            "_fire_and_forget": _fire,
            # _persist_event_edit reads guild settings for the capacity warning;
            # this class stubs the DB layer, so stub that accessor too rather
            # than depending on whatever DB_FILE happens to point at.
            "get_guild_settings": lambda _gid: dict(self.bot.DEFAULT_GUILD_SETTINGS),
        }
        for name, repl in patches.items():
            self.addCleanup(setattr, botmod, name, getattr(botmod, name))
            setattr(botmod, name, repl)

    def _prop(self, key):
        return self.bot._find_prop_in(self.bot._EDIT_PROPERTIES, key)

    async def _persist(self, key, value, confirmed=False):
        return await self.bot._persist_event_edit(
            1, 2, 1, self._prop(key), value, "en", "organizer", confirmed=confirmed)

    async def _grow_to_eight(self):
        await self._persist("infantry_squads", [[8, 2]])
        self.saved.clear()

    # ── when to ask ────────────────────────────────────────────────────────
    async def test_shrink_asks_and_names_exactly_who_loses_a_seat(self):
        await self._grow_to_eight()
        status, shed = await self._persist("infantry_squads", [[6, 2]])
        self.assertEqual(status, "confirm")
        self.assertEqual([s[1] for s in shed], ["Inf12", "Inf13", "Inf14", "Inf15"])

    async def test_growing_asks_nothing(self):
        status, _ = await self._persist("infantry_squads", [[8, 2]])
        self.assertEqual(status, "ok")

    async def test_no_prompt_when_everyone_is_re_seated(self):
        # 16 infantry seats: 4 squads of 4 -> 2 squads of 8, nobody actually loses out.
        self.ev, self.ua = _seed(_event(infantry_squads=[[4, 4]]), {})
        status, _ = await self._persist("infantry_squads", [[8, 2]])
        self.assertEqual(status, "ok")

    async def test_rep_mode_is_never_prompted(self):
        """Rep mode has no re-fit: a composition that still covers the registered
        squads applies straight away, and one that does not is an error rather
        than a prompt — there is nothing to confirm, nobody can be re-seated."""
        # A real rep event: whole squads with the size their rep signed up with.
        self.ev = _event(mode="rep", squads={
            "s1": {"name": "A", "type": "infantry", "size": 6},
            "s2": {"name": "B", "type": "infantry", "size": 6},
        })
        self.ua = {}

        status, _ = await self._persist("infantry_squads", [[6, 4]])
        self.assertEqual(status, "ok")

        status, text = await self._persist("infantry_squads", [[2, 2]])
        self.assertEqual(status, "error")
        self.assertTrue(text)

    async def test_non_capacity_property_is_never_prompted(self):
        status, _ = await self._persist("name", "Renamed")
        self.assertEqual(status, "ok")

    async def test_an_edit_that_will_be_rejected_is_an_error_not_a_prompt(self):
        status, text = await self._persist("infantry_squads", [])
        self.assertEqual(status, "error")
        self.assertTrue(text)

    # ── asking must not apply anything ─────────────────────────────────────
    async def test_an_unconfirmed_shrink_saves_nothing(self):
        await self._grow_to_eight()
        before = copy.deepcopy(self.ev), copy.deepcopy(self.ua)
        status, _ = await self._persist("infantry_squads", [[6, 2]])
        self.assertEqual(status, "confirm")
        self.assertEqual(self.saved, [])
        # The dry run mutated its own copy; the stored state must be untouched.
        self.assertEqual((self.ev, self.ua), before)
        self.assertEqual(self.ev["infantry_squads"], [[8, 2]])
        self.assertEqual(self.ev["infantry_waitlist"], [])

    async def test_confirming_applies_and_saves(self):
        await self._grow_to_eight()
        status, _ = await self._persist("infantry_squads", [[6, 2]], confirmed=True)
        self.assertEqual(status, "ok")
        self.assertEqual(len(self.saved), 1)
        _db, ev, ua = self.saved[0]
        self.assertEqual(ev["infantry_squads"], [[6, 2]])
        self.assertEqual(_wl_names(ev), ["Inf12", "Inf13", "Inf14", "Inf15"])
        for name in ("Inf12", "Inf13", "Inf14", "Inf15"):
            self.assertNotIn(name, [m["name"] for s in ev["squads"].values()
                                    for m in s.get("members", [])])

    async def test_confirm_applies_the_current_roster_not_the_previewed_one(self):
        """The prompt is advisory; the apply re-derives under the lock. If people
        register in between, the confirmed edit sheds what is actually there."""
        await self._grow_to_eight()
        status, shed = await self._persist("infantry_squads", [[6, 2]])
        self.assertEqual(len(shed), 4)

        # Two of the four leave while the organizer is still looking at the dialog.
        for uid in ("i12", "i13"):
            utils._player_unregister(self.ev, self.ua, uid)

        status, _ = await self._persist("infantry_squads", [[6, 2]], confirmed=True)
        self.assertEqual(status, "ok")
        _db, ev, _ua = self.saved[-1]
        # Only two seats over now, and it is the players still present who lose
        # them — not the four the dialog had named. (Order follows the compaction
        # _player_unregister already does, which this change leaves alone.)
        self.assertEqual(sorted(_wl_names(ev)), ["Inf14", "Inf15"])

    # ── the UI gate ────────────────────────────────────────────────────────
    async def test_apply_edit_renders_the_confirm_view_on_a_confirm_status(self):
        shown = []

        async def _render(interaction, user_id, embed, view, via_modal=False):
            shown.append((embed, view, via_modal))

        for name, repl in (("_render_session_dialog", _render),
                           ("_refresh_main_view", lambda *a, **kw: _noop_coro())):
            self.addCleanup(setattr, self.bot, name, getattr(self.bot, name))
            setattr(self.bot, name, repl)

        await self._grow_to_eight()
        await self.bot._apply_edit(_StubInteraction(), 7, 1, 2, 1, "en",
                                   self._prop("infantry_squads"), [[6, 2]], via_modal=True)
        self.assertEqual(self.saved, [])
        self.assertEqual(len(shown), 1)
        embed, view, via_modal = shown[0]
        self.assertIsInstance(view, self.bot._ConfirmShrinkView)
        self.assertIn("4", embed.description)
        self.assertTrue(via_modal, "must render on the same path the edit arrived on")
        self.assertEqual(len(view.children), 2)  # Confirm + Cancel, nothing else


async def _noop_coro():
    pass


class ShrinkConfirmAgainstRealDBTest(unittest.IsolatedAsyncioTestCase):
    """Same gate, but against the real sqlite layer instead of a stubbed loader.

    The whole design rests on `_get_event_by_dbid` handing back a private copy per
    read, so an unconfirmed shrink can throw its dry run away by simply not saving.
    That is a property of `database.get_event_by_id`, so pin it here rather than
    trust the stub.
    """

    def setUp(self):
        import tempfile
        import database
        import bot as botmod
        self.bot, self.database = botmod, database

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        self.addCleanup(setattr, database, "DB_FILE", database.DB_FILE)
        database.DB_FILE = tmp.name
        database.init_db()

        ev, ua = _seed(_event(), {})
        self.db_id = database.create_event(1, 2, ev)
        database.save_event(self.db_id, ev, ua)

        async def _noop(*a, **kw):
            pass

        for name, repl in (("update_event_displays", _noop),
                           ("_fire_and_forget", lambda coro: coro.close())):
            self.addCleanup(setattr, botmod, name, getattr(botmod, name))
            setattr(botmod, name, repl)

    def _stored(self):
        return self.database.get_event_by_id(1, self.db_id)["event"]

    async def _persist(self, value, confirmed=False):
        prop = self.bot._find_prop_in(self.bot._EDIT_PROPERTIES, "infantry_squads")
        return await self.bot._persist_event_edit(
            1, 2, self.db_id, prop, value, "en", "organizer", confirmed=confirmed)

    async def test_unconfirmed_shrink_leaves_the_stored_event_untouched(self):
        self.assertEqual((await self._persist([[8, 2]]))[0], "ok")
        self.assertEqual(self._stored()["infantry_waitlist"], [])

        status, shed = await self._persist([[6, 2]])
        self.assertEqual(status, "confirm")
        self.assertEqual(len(shed), 4)

        stored = self._stored()
        self.assertEqual(stored["infantry_squads"], [[8, 2]])
        self.assertEqual(stored["infantry_waitlist"], [])
        self.assertEqual(stored["player_slots_used"], 18)
        self.assertEqual(len(stored["squads"]["Infantry 1"]["members"]), 8)

    async def test_confirming_writes_it_through(self):
        await self._persist([[8, 2]])
        await self._persist([[6, 2]])                       # prompt only
        self.assertEqual((await self._persist([[6, 2]], confirmed=True))[0], "ok")

        stored = self._stored()
        self.assertEqual(stored["infantry_squads"], [[6, 2]])
        self.assertEqual([e[5] for e in stored["infantry_waitlist"]],
                         ["Inf12", "Inf13", "Inf14", "Inf15"])
        self.assertEqual(stored["player_slots_used"], 14)


class ShrinkConfirmEmbedTest(unittest.TestCase):

    def test_long_lists_are_truncated_with_a_tail(self):
        import bot as botmod
        prop = botmod._find_prop_in(botmod._EDIT_PROPERTIES, "infantry_squads")
        shed = [(str(i), f"P{i}", "Infantry 1") for i in range(20)]
        embed = botmod._build_shrink_confirm_embed(prop, [[6, 1]], shed, "en")
        listed = embed.fields[0].value
        self.assertIn("**P0**", listed)
        self.assertIn("**P14**", listed)
        self.assertNotIn("**P15**", listed)
        self.assertIn("5", listed.rsplit("**", 1)[-1])

    def test_messages_exist_in_both_languages(self):
        from i18n import _STRINGS
        for key in ("edit.confirm_shrink_title", "edit.confirm_shrink_body",
                    "edit.confirm_shrink_affected", "edit.confirm_shrink_more"):
            self.assertEqual(set(_STRINGS[key]), {"de", "en"})


class CapacityKeyTableTest(unittest.TestCase):
    """The wiring in _persist_event_edit is keyed by property name — a typo there
    would silently skip the resize, so pin the table against the real editor."""

    def test_every_capacity_key_is_a_real_editable_property(self):
        import bot as botmod
        editable = {key for _n, key, _l, _v, _s in botmod._EDIT_PROPERTIES}
        self.assertLessEqual(set(botmod._CAPACITY_KEYS), editable)

    def test_every_mapped_type_is_a_real_squad_type(self):
        import bot as botmod
        for types_ in botmod._CAPACITY_KEYS.values():
            self.assertLessEqual(set(types_), set(utils._SQUAD_TYPES))

    def test_messages_exist_in_both_languages(self):
        from i18n import _STRINGS
        for key in ("player.moved_to_waitlist", "log.player_demoted"):
            self.assertEqual(set(_STRINGS[key]), {"de", "en"})


if __name__ == "__main__":
    unittest.main()
