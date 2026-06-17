#!/usr/bin/env python3
"""Unit tests for player-mode "tentative" (Vorläufig) sign-ups.

A tentative player signals "maybe" — they pick a squad type (and optional role)
but do NOT occupy a real squad seat. They are stored in `event["tentative"]`,
are mutually exclusive with a firm seat / waitlist spot, and render in the embed
as one field per squad type at the very bottom.

Also covers the removal of the "(Egal)" parenthetical for role-less players.
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


def _make_event(seats=17, inf=6, veh=2, heli=1, max_veh=2, max_heli=1):
    return {
        "name": "Test Event",
        "date": "01.01.2099",
        "time": "20:00",
        "mode": "player",
        "max_player_slots": seats,
        "infantry_squad_size": inf,
        "vehicle_squad_size": veh,
        "heli_squad_size": heli,
        "max_vehicle_squads": max_veh,
        "max_heli_squads": max_heli,
        "squads": {},
        "casters": {},
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
        "caster_waitlist": [],
        "tentative": [],
    }


class AddTentativeTest(unittest.TestCase):
    def test_add_tentative_adds_entry(self):
        event = _make_event()
        status = utils._add_tentative(event, "u1", "Alice", "infantry", ["Squad Leader"])
        self.assertEqual(status, "tentative")
        self.assertEqual(len(event["tentative"]), 1)
        entry = event["tentative"][0]
        self.assertEqual(entry["user_id"], "u1")
        self.assertEqual(entry["name"], "Alice")
        self.assertEqual(entry["type"], "infantry")
        self.assertEqual(entry["roles"], ["Squad Leader"])

    def test_add_tentative_without_roles_stores_empty_list(self):
        event = _make_event()
        utils._add_tentative(event, "u1", "Alice", "vehicle")
        self.assertEqual(event["tentative"][0]["roles"], [])

    def test_add_tentative_replaces_existing_entry_one_per_user(self):
        event = _make_event()
        utils._add_tentative(event, "u1", "Alice", "infantry", ["Medic"])
        utils._add_tentative(event, "u1", "Alice", "heli", ["Pilot"])
        self.assertEqual(len(event["tentative"]), 1)
        self.assertEqual(event["tentative"][0]["type"], "heli")
        self.assertEqual(event["tentative"][0]["roles"], ["Pilot"])

    def test_add_tentative_rejects_invalid_type(self):
        event = _make_event()
        status = utils._add_tentative(event, "u1", "Alice", "bogus")
        self.assertEqual(status, "invalid_type")
        self.assertEqual(event["tentative"], [])

    def test_add_tentative_does_not_touch_squads_or_slots(self):
        event = _make_event()
        event["player_slots_used"] = 0
        utils._add_tentative(event, "u1", "Alice", "infantry", ["Squad Leader"])
        self.assertEqual(event["squads"], {})
        self.assertEqual(event.get("player_slots_used", 0), 0)


class RemoveAndLookupTentativeTest(unittest.TestCase):
    def test_remove_tentative_returns_entry(self):
        event = _make_event()
        utils._add_tentative(event, "u1", "Alice", "infantry")
        removed = utils._remove_tentative(event, "u1")
        self.assertIsNotNone(removed)
        self.assertEqual(removed["user_id"], "u1")
        self.assertEqual(event["tentative"], [])

    def test_remove_tentative_missing_returns_none(self):
        event = _make_event()
        self.assertIsNone(utils._remove_tentative(event, "ghost"))

    def test_tentative_type_and_entry_lookup_non_destructive(self):
        event = _make_event()
        utils._add_tentative(event, "u1", "Alice", "vehicle", ["Driver"])
        self.assertEqual(utils._player_tentative_type(event, "u1"), "vehicle")
        entry = utils._player_tentative_entry(event, "u1")
        self.assertEqual(entry["roles"], ["Driver"])
        # Lookups must not remove the entry.
        self.assertEqual(len(event["tentative"]), 1)
        self.assertIsNone(utils._player_tentative_type(event, "ghost"))
        self.assertIsNone(utils._player_tentative_entry(event, "ghost"))


class SelfUnregisterTentativeTest(unittest.TestCase):
    def test_self_unregister_removes_tentative_only_user(self):
        event = _make_event()
        ua = {}
        utils._add_tentative(event, "u1", "Alice", "infantry", ["Medic"])
        status, name_or_type, promoted = utils._player_self_unregister(event, ua, "u1")
        self.assertEqual(status, "tentative")
        self.assertEqual(name_or_type, "infantry")
        self.assertEqual(promoted, [])
        self.assertEqual(event["tentative"], [])

    def test_self_unregister_seated_user_ignores_tentative_path(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry")
        status, name, _ = utils._player_self_unregister(event, ua, "u1")
        self.assertEqual(status, "squad")


class CurrentAssignmentTest(unittest.TestCase):
    def test_seated_player_type_and_roles(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry", ["Squad Leader"])
        st, roles = utils._player_current_assignment(event, ua, "u1")
        self.assertEqual(st, "infantry")
        self.assertEqual(roles, ["Squad Leader"])

    def test_seated_player_without_role(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "vehicle")
        st, roles = utils._player_current_assignment(event, ua, "u1")
        self.assertEqual(st, "vehicle")
        self.assertEqual(roles, [])

    def test_waitlisted_player_type_and_roles(self):
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 seated, u12 waitlisted on infantry
            utils._player_register(event, ua, f"u{i}", f"P{i}", "infantry", ["Medic"])
        st, roles = utils._player_current_assignment(event, ua, "u12")
        self.assertEqual(st, "infantry")
        self.assertEqual(roles, ["Medic"])

    def test_unknown_user_returns_none(self):
        event = _make_event()
        st, roles = utils._player_current_assignment(event, {}, "ghost")
        self.assertIsNone(st)
        self.assertEqual(roles, [])


class SwitchToTentativeCompositionTest(unittest.TestCase):
    """The pieces player_switch_to_tentative orchestrates: capture the current
    type+roles, free the seat (promoting any waitlister), re-add as tentative."""

    def test_seated_to_tentative_carries_over_and_promotes(self):
        event = _make_event()
        ua = {}
        for i in range(13):  # 12 seated, u12 waitlisted on infantry
            utils._player_register(event, ua, f"u{i}", f"P{i}", "infantry",
                                   ["Medic"] if i == 0 else None)

        # Switch u0 (seated, Medic) to tentative.
        st, roles = utils._player_current_assignment(event, ua, "u0")
        status, _name, promoted = utils._player_self_unregister(event, ua, "u0")
        utils._add_tentative(event, "u0", "P0", st, roles)

        self.assertEqual(status, "squad")
        self.assertEqual(st, "infantry")
        self.assertEqual(roles, ["Medic"])
        self.assertNotIn("u0", ua)                       # seat freed
        self.assertEqual([p[0] for p in promoted], ["u12"])  # waitlister promoted
        tent = utils._player_tentative_entry(event, "u0")
        self.assertEqual(tent["type"], "infantry")
        self.assertEqual(tent["roles"], ["Medic"])


class FormatRoleSuffixTest(unittest.TestCase):
    def test_role_suffix_with_roles_has_parens(self):
        self.assertEqual(utils._format_role_suffix(["Squad Leader"], "de"), " (Squad Leader)")

    def test_role_suffix_empty_is_blank(self):
        self.assertEqual(utils._format_role_suffix([], "de"), "")
        self.assertEqual(utils._format_role_suffix(None, "de"), "")


class EmbedRenderingTest(unittest.TestCase):
    def _find_field(self, embed, needle):
        for f in embed.fields:
            if needle in f.name:
                return f
        return None

    def test_member_without_role_has_no_egal(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry")  # no role
        embed = utils.format_event_details(event, "de")
        squad_field = self._find_field(embed, t("embed.type_infantry", "de"))
        self.assertIsNotNone(squad_field)
        self.assertIn("Alice", squad_field.value)
        self.assertNotIn("Egal", squad_field.value)
        self.assertNotIn("**Alice** ()", squad_field.value)

    def test_member_with_role_shows_role(self):
        event = _make_event()
        ua = {}
        utils._player_register(event, ua, "u1", "Alice", "infantry", ["Squad Leader"])
        embed = utils.format_event_details(event, "de")
        squad_field = self._find_field(embed, t("embed.type_infantry", "de"))
        self.assertIn("**Alice** (Squad Leader)", squad_field.value)

    def test_tentative_field_per_type(self):
        event = _make_event()
        utils._add_tentative(event, "u1", "Alice", "infantry", ["Medic"])
        utils._add_tentative(event, "u2", "Bob", "infantry")
        utils._add_tentative(event, "u3", "Carol", "vehicle", ["Driver"])
        embed = utils.format_event_details(event, "de")

        inf_label = t("embed.tentative_label", "de",
                      type=t("embed.type_infantry", "de"), count=2)
        veh_label = t("embed.tentative_label", "de",
                      type=t("embed.type_vehicle", "de"), count=1)
        inf_field = self._find_field(embed, inf_label)
        veh_field = self._find_field(embed, veh_label)
        self.assertIsNotNone(inf_field, "expected an infantry tentative field")
        self.assertIsNotNone(veh_field, "expected a vehicle tentative field")
        self.assertIn("**Alice** (Medic)", inf_field.value)
        self.assertIn("**Bob**", inf_field.value)
        self.assertNotIn("Egal", inf_field.value)
        self.assertIn("**Carol** (Driver)", veh_field.value)

    def test_no_tentative_field_when_empty(self):
        event = _make_event()
        embed = utils.format_event_details(event, "de")
        for f in embed.fields:
            self.assertNotIn("Vorläufig", f.name)


class I18nKeysTest(unittest.TestCase):
    def test_new_keys_present(self):
        for key in ("button.tentative", "embed.tentative_label",
                    "player.tentative_registered", "player.tentative_switched",
                    "player.tentative_removed", "player.tentative_unregister_confirm",
                    "button.notify_tentative", "tentative.none",
                    "tentative.dm_text", "tentative.thread_text"):
            for lang in ("de", "en"):
                self.assertNotIn("missing", t(key, lang), f"{key}/{lang} missing")

    def test_role_placeholder_marks_optional(self):
        self.assertIn("optional", t("player.role_select_placeholder", "de").lower())
        self.assertIn("optional", t("player.role_select_placeholder", "en").lower())


if __name__ == "__main__":
    unittest.main()
