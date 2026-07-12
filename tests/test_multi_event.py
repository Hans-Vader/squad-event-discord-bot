#!/usr/bin/env python3
"""Multiple-active-events-per-channel: DB layer, message-id routing, migration,
and the slash-command event picker resolver.

The one-event-per-channel limit was removed; a channel can now hold several
active events. Each event owns its embed message, and interactions resolve the
right event via that message id (`_dbid_from_message`). Slash commands that used
to assume a single event now disambiguate with `_resolve_command_event`.
"""

import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import database  # noqa: E402
import bot       # noqa: E402

bot.get_guild_language = lambda *_a, **_k: "en"


def _run(coro):
    return asyncio.run(coro)


def _event(name, msg_id):
    return {"name": name, "date": "01.01.2030", "time": "20:00",
            "event_message_id": msg_id}


# ---------------------------------------------------------------------------
# DB layer: multiple active events per channel
# ---------------------------------------------------------------------------

class MultiEventDBTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        database.DB_FILE = self._tmp.name
        database.init_db()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_two_active_events_in_one_channel(self):
        id1 = database.create_event(1, 2, _event("Alpha", None))
        id2 = database.create_event(1, 2, _event("Bravo", None))
        self.assertNotEqual(id1, id2)
        rows = database.get_events_by_channel(1, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["db_id"] for r in rows}, {id1, id2})

    def test_get_event_by_id_returns_channel(self):
        db_id = database.create_event(1, 2, _event("Alpha", None))
        row = database.get_event_by_id(1, db_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["channel_id"], 2)
        self.assertEqual(row["event"]["name"], "Alpha")
        # Wrong guild → None.
        self.assertIsNone(database.get_event_by_id(999, db_id))

    def test_soft_delete_leaves_the_other_event_active(self):
        id1 = database.create_event(1, 2, _event("Alpha", None))
        id2 = database.create_event(1, 2, _event("Bravo", None))
        database.delete_event(id1)
        rows = database.get_events_by_channel(1, 2)
        self.assertEqual([r["db_id"] for r in rows], [id2])


# ---------------------------------------------------------------------------
# Migration: old UNIQUE(guild_id, channel_id, status) table is rebuilt
# ---------------------------------------------------------------------------

class MigrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        database.DB_FILE = self._tmp.name

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _build_old_schema(self):
        conn = sqlite3.connect(self._tmp.name)
        conn.executescript("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                event_data TEXT NOT NULL,
                user_assignments TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(guild_id, channel_id, status)
            );
            INSERT INTO events (id, guild_id, channel_id, event_data)
                VALUES (5, 1, 2, '{"name": "Old"}');
        """)
        conn.commit()
        conn.close()

    def _schema(self):
        conn = sqlite3.connect(self._tmp.name)
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()[0]
        conn.close()
        return sql

    def test_migration_drops_constraint_preserves_ids_and_is_idempotent(self):
        self._build_old_schema()
        self.assertIn("UNIQUE(guild_id, channel_id, status)", self._schema())

        database.init_db()
        self.assertNotIn("UNIQUE(guild_id, channel_id, status)", self._schema())
        # The pre-existing row and its id survive.
        row = database.get_event_by_id(1, 5)
        self.assertIsNotNone(row)
        self.assertEqual(row["event"]["name"], "Old")

        # A second active event in the same channel now succeeds.
        id2 = database.create_event(1, 2, _event("New", None))
        self.assertEqual(len(database.get_events_by_channel(1, 2)), 2)

        # Second init_db is a no-op (no crash, constraint stays gone).
        database.init_db()
        self.assertNotIn("UNIQUE(guild_id, channel_id, status)", self._schema())
        self.assertEqual(len(database.get_events_by_channel(1, 2)), 2)


# ---------------------------------------------------------------------------
# Routing: interaction.message.id → the right event's db_id
# ---------------------------------------------------------------------------

class _FakeGuild:
    id = 1


class _FakeInteraction:
    def __init__(self, message_id):
        self.guild = _FakeGuild()
        self.channel_id = 2
        self.message = type("M", (), {"id": message_id})()


class MessageRoutingTest(unittest.TestCase):
    def _rows(self):
        return [
            {"db_id": 10, "event": _event("Alpha", 1001), "user_assignments": {}},
            {"db_id": 20, "event": _event("Bravo", 2002), "user_assignments": {}},
        ]

    def test_resolves_correct_dbid_per_message(self):
        with mock.patch.object(bot, "get_events_by_channel", return_value=self._rows()):
            self.assertEqual(bot._dbid_from_message(_FakeInteraction(1001)), 10)
            self.assertEqual(bot._dbid_from_message(_FakeInteraction(2002)), 20)

    def test_unknown_message_returns_none(self):
        with mock.patch.object(bot, "get_events_by_channel", return_value=self._rows()):
            self.assertIsNone(bot._dbid_from_message(_FakeInteraction(9999)))


# ---------------------------------------------------------------------------
# Picker resolver: 0 / 1 / >1 active events
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self):
        self.sent = None

    async def send_message(self, content=None, view=None, ephemeral=False, **k):
        self.sent = {"content": content, "view": view}


class _CmdInteraction:
    def __init__(self):
        self.guild = _FakeGuild()
        self.channel_id = 2
        self.response = _Resp()


class ResolveCommandEventTest(unittest.IsolatedAsyncioTestCase):
    def _row(self, db_id, name, msg_id):
        return {"db_id": db_id, "event": _event(name, msg_id), "user_assignments": {}}

    async def test_no_event_reports_and_skips_body(self):
        picked = []
        with mock.patch.object(bot, "get_events_by_channel", return_value=[]):
            inter = _CmdInteraction()
            await bot._resolve_command_event(inter, "en", lambda i, d: picked.append(d))
        self.assertEqual(picked, [])
        self.assertIsNotNone(inter.response.sent["content"])

    async def test_single_event_calls_body_directly(self):
        picked = []

        async def _do(i, db_id):
            picked.append(db_id)

        with mock.patch.object(bot, "get_events_by_channel",
                               return_value=[self._row(10, "Alpha", 1001)]):
            inter = _CmdInteraction()
            await bot._resolve_command_event(inter, "en", _do)
        self.assertEqual(picked, [10])
        self.assertIsNone(inter.response.sent, "no picker for a single event")

    async def test_multiple_events_shows_picker(self):
        rows = [self._row(10, "Alpha", 1001), self._row(20, "Bravo", 2002)]
        with mock.patch.object(bot, "get_events_by_channel", return_value=rows):
            inter = _CmdInteraction()
            await bot._resolve_command_event(inter, "en", lambda i, d: None)
        self.assertIsInstance(inter.response.sent["view"], bot.EventPickerView)


if __name__ == "__main__":
    unittest.main()
