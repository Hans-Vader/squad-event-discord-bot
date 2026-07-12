#!/usr/bin/env python3
"""Unit tests for `_registered_gather` — the recipient list of the
"Ask registered" notify flow.

It must collect squad members in player mode, squad representatives in rep
mode (their user ids live in user_assignments, not on the squad), and casters
(a dict keyed by user id) in both — deduplicated, waitlists excluded.
"""

import os
import sys
import types
import unittest
from unittest import mock

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

import bot  # noqa: E402


def _gather(event, user_assignments=None):
    with mock.patch.object(bot, "_get_event_by_dbid",
                           return_value=(event, user_assignments or {}, 1)), \
         mock.patch.object(bot, "get_guild_language", return_value="en"):
        return bot._registered_gather(1, 2, 1)


class PlayerModeGatherTest(unittest.TestCase):
    def test_members_and_casters_collected(self):
        event = {
            "mode": "player",
            "squads": {
                "s1": {"name": "Alpha", "type": "infantry", "members": [
                    {"user_id": "u1", "name": "Alice"},
                    {"user_id": "u2", "name": "Bob"},
                ]},
            },
            "casters": {"u3": {"name": "Carol", "id": "u3"}},
        }
        _, _, entries = _gather(event)
        self.assertEqual(
            {(e["user_id"], e["name"], e["type"]) for e in entries},
            {("u1", "Alice", "infantry"), ("u2", "Bob", "infantry"),
             ("u3", "Carol", "caster")})

    def test_duplicate_user_listed_once(self):
        event = {
            "mode": "player",
            "squads": {
                "s1": {"type": "infantry", "members": [{"user_id": "u1", "name": "Alice"}]},
            },
            "casters": {"u1": {"name": "Alice", "id": "u1"}},
        }
        _, _, entries = _gather(event)
        self.assertEqual(len(entries), 1)


class RepModeGatherTest(unittest.TestCase):
    def test_reps_come_from_user_assignments(self):
        event = {
            "mode": "squad",
            "squads": {
                "sq-1": {"name": "Alpha", "type": "infantry", "playstyle": "casual",
                         "size": 6, "rep_name": "Rita"},
                "sq-2": {"name": "Bravo", "type": "vehicle", "playstyle": "serious",
                         "size": 3, "rep_name": "Rob"},
            },
            "casters": {"u9": {"name": "Cass", "id": "u9"}},
        }
        assignments = {"r1": ["sq-1"], "r2": ["sq-2"], "u9": ["__caster__"]}
        _, _, entries = _gather(event, assignments)
        self.assertEqual(
            {(e["user_id"], e["name"], e["type"]) for e in entries},
            {("r1", "Rita", "infantry"), ("r2", "Rob", "vehicle"),
             ("u9", "Cass", "caster")})

    def test_no_event_returns_empty(self):
        with mock.patch.object(bot, "_get_event_by_dbid", return_value=(None, None, None)), \
             mock.patch.object(bot, "get_guild_language", return_value="en"):
            event, _, entries = bot._registered_gather(1, 2, 1)
        self.assertIsNone(event)
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
