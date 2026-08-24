#!/usr/bin/env python3
"""Unit tests for the squad meta resolver behind the unregister dropdown.

The unregister selector shows each registered squad's name plus its type and
size as a secondary description line. These cover the pure resolver that powers
that description for both active squads and waitlisted entries, and that the
description string itself localizes correctly.

They also cover that picking a squad from the dropdown shows a Confirm/Cancel
prompt before anything is removed, matching every other removal flow.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import discord  # noqa: E402
import bot  # noqa: E402
from i18n import t  # noqa: E402

# The confirm view resolves the guild language via the DB; force English so the
# tests don't need a database.
bot.get_guild_language = lambda *_a, **_k: "en"


def _event():
    return {
        "squads": {
            "sq-1": {"name": "Alpha", "type": "infantry", "size": 6},
            "sq-2": {"name": "Bravo", "type": "vehicle", "size": 2},
        },
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        # entry tuple: (name, type, size, squad_id, rep_name)
        "heli_waitlist": [("Charlie", "heli", 1, "sq-3", "rep")],
    }


class ResolveSquadMetaTest(unittest.TestCase):
    def test_active_squad_returns_name_type_size(self):
        name, stype, size = bot._resolve_squad_meta(_event(), "sq-1")
        self.assertEqual(name, "Alpha")
        self.assertEqual(stype, "infantry")
        self.assertEqual(size, 6)

    def test_waitlisted_squad_returns_name_type_size(self):
        name, stype, size = bot._resolve_squad_meta(_event(), "sq-3")
        self.assertEqual(name, "Charlie")
        self.assertEqual(stype, "heli")
        self.assertEqual(size, 1)

    def test_unknown_squad_falls_back_to_id_without_meta(self):
        name, stype, size = bot._resolve_squad_meta(_event(), "ghost")
        self.assertEqual(name, "ghost")
        self.assertIsNone(stype)
        self.assertIsNone(size)

    def test_description_string_localized(self):
        _, stype, size = bot._resolve_squad_meta(_event(), "sq-2")
        desc_en = t(f"squad.type_{stype}", "en", size=size)
        desc_de = t(f"squad.type_{stype}", "de", size=size)
        self.assertIn("Vehicle", desc_en)
        self.assertIn("2", desc_en)
        self.assertIn("Fahrzeug", desc_de)
        self.assertIn("2", desc_de)


class BuildSquadUnregisterConfirmTest(unittest.TestCase):
    def test_returns_embed_naming_squad_and_confirm_view(self):
        embed, view = bot._build_squad_unregister_confirm(_event(), 1, 2, 1, "sq-1", "en")
        # The resolved squad name is shown in the prompt the user must confirm.
        self.assertIn("Alpha", embed.description)
        # The shared confirm view carries the selected squad id.
        self.assertIsInstance(view, bot.SquadUnregisterConfirmView)
        self.assertEqual(view.squad_name, "sq-1")


class _FakeResponse:
    def __init__(self):
        self.edit_calls = 0
        self.last_edit_kwargs = None
        self.defer_calls = 0

    async def edit_message(self, **kwargs):
        self.edit_calls += 1
        self.last_edit_kwargs = kwargs

    async def defer(self, *a, **k):
        self.defer_calls += 1


class _FakeInteraction:
    def __init__(self, value):
        self.data = {"values": [value]}
        self.response = _FakeResponse()


class SelectorShowsConfirmationTest(unittest.IsolatedAsyncioTestCase):
    async def test_selecting_squad_shows_confirmation_without_unregistering(self):
        event = _event()
        unregister_calls = []

        async def _spy_unregister(*a, **k):
            unregister_calls.append((a, k))

        orig_get = bot._get_event_by_dbid
        orig_unreg = bot.unregister_squad
        bot._get_event_by_dbid = lambda *a, **k: (event, {}, 0)
        bot.unregister_squad = _spy_unregister
        try:
            view = bot.UserSquadUnregisterSelector(
                1, 2, 1, [discord.SelectOption(label="Alpha", value="sq-1")])
            interaction = _FakeInteraction("sq-1")
            await view._selected(interaction)
        finally:
            bot._get_event_by_dbid = orig_get
            bot.unregister_squad = orig_unreg

        # Selecting a squad must NOT remove it; that waits for confirmation.
        self.assertEqual(unregister_calls, [])
        # The dropdown is replaced in place by the confirmation prompt.
        self.assertEqual(interaction.response.edit_calls, 1)
        shown = interaction.response.last_edit_kwargs["view"]
        self.assertIsInstance(shown, bot.SquadUnregisterConfirmView)
        self.assertEqual(shown.squad_name, "sq-1")


if __name__ == "__main__":
    unittest.main()
