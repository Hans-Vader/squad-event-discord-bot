#!/usr/bin/env python3
"""The early-access announcement must be deleted when registration opens.

When an event is created with early access, the bot pings community reps with
"You have early access to register for …". Once general registration opens that
call-out is stale, so it should be removed. The message ID lives in its own
``early_access_message_id`` field (mirroring ``countdown_message_id``) so it can
be deleted unambiguously without touching the freshly-sent "registration open"
ping that shares ``ping_message_ids``.

These cover the field default and the shared ``_cleanup_early_access_message``
helper that both the auto-open loop and the manual Open-Registration button call.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bot  # noqa: E402
from database import build_default_event  # noqa: E402


_SETTINGS = {
    "server_max_players": 100, "max_caster_slots": 2,
    "infantry_squad_size": 6, "vehicle_squad_size": 2, "heli_squad_size": 1,
    "max_vehicle_squads": 2, "max_heli_squads": 1, "max_squads_per_user": 1,
}


class _FakeMessage:
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class _FakeChannel:
    """Records fetches; returns a deletable message, or raises a configured error."""

    def __init__(self, raise_exc=None):
        self.raise_exc = raise_exc
        self.fetched_ids = []
        self.message = _FakeMessage()

    async def fetch_message(self, msg_id):
        self.fetched_ids.append(msg_id)
        if self.raise_exc:
            raise self.raise_exc
        return self.message


class FieldDefaultTest(unittest.TestCase):
    def test_default_event_has_early_access_message_id_none(self):
        event = build_default_event(_SETTINGS, "Cup Night", "31.12.2099", "20:00")
        self.assertIn("early_access_message_id", event)
        self.assertIsNone(event["early_access_message_id"])


class CleanupHelperTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_save = bot.save_event
        self.save_calls = []
        bot.save_event = lambda *a, **k: self.save_calls.append((a, k))

    def tearDown(self):
        bot.save_event = self._orig_save

    async def test_deletes_message_and_clears_field(self):
        event = {"early_access_message_id": 12345}
        ch = _FakeChannel()

        await bot._cleanup_early_access_message(ch, event, db_id=7, user_assignments={})

        self.assertEqual(ch.fetched_ids, [12345])
        self.assertTrue(ch.message.deleted)
        # ID is consumed (popped, like countdown_message_id) so it isn't deleted twice.
        self.assertNotIn("early_access_message_id", event)
        # Cleared state is persisted exactly once.
        self.assertEqual(len(self.save_calls), 1)

    async def test_noop_when_no_message_recorded(self):
        event = {"early_access_message_id": None}
        ch = _FakeChannel()

        await bot._cleanup_early_access_message(ch, event, db_id=7, user_assignments={})

        self.assertEqual(ch.fetched_ids, [])
        self.assertEqual(self.save_calls, [])

    async def test_swallows_delete_errors_but_still_clears_field(self):
        event = {"early_access_message_id": 999}
        # Stand-in for discord.NotFound / Forbidden — the helper must swallow any error.
        ch = _FakeChannel(raise_exc=RuntimeError("message gone"))

        # Must not propagate even though fetch_message raises.
        await bot._cleanup_early_access_message(ch, event, db_id=7, user_assignments={})

        self.assertEqual(ch.fetched_ids, [999])
        self.assertNotIn("early_access_message_id", event)
        self.assertEqual(len(self.save_calls), 1)


if __name__ == "__main__":
    unittest.main()
