#!/usr/bin/env python3
"""The bot keeps a single 'current announcement' below the event embed.

`_set_channel_announcement` posts the new announcement, records it in
`event["announcement_message_id"]`, then deletes whatever was there before — including
the legacy trackers (`ping_message_ids` / `early_access_message_id` /
`countdown_message_id`) so events created before this scheme self-heal on their next
announcement. `content=None` just clears the current announcement.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import discord  # noqa: E402
import bot  # noqa: E402


class _FakeMessage:
    def __init__(self, mid):
        self.id = mid
        self.deleted = False

    async def delete(self):
        self.deleted = True


class _FakeChannel:
    """Records sends and fetch+delete. `send_error` may be a single exception (always
    raised) or a per-attempt list (None = success that attempt)."""

    def __init__(self, send_id=999, send_error=None):
        self.send_id = send_id
        self.send_error = send_error
        self.sent = []
        self.send_calls = 0
        self.fetched = {}

    async def send(self, content=None, allowed_mentions=None):
        self.send_calls += 1
        if self.send_error is not None:
            if isinstance(self.send_error, list):
                exc = self.send_error[self.send_calls - 1] if self.send_calls - 1 < len(self.send_error) else None
                if exc is not None:
                    raise exc
            else:
                raise self.send_error
        self.sent.append(content)
        return _FakeMessage(self.send_id)

    async def fetch_message(self, mid):
        msg = _FakeMessage(mid)
        self.fetched[mid] = msg
        return msg


class SetChannelAnnouncementTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_save = bot.save_event
        self.save_calls = []
        bot.save_event = lambda *a, **k: self.save_calls.append((a, k))

    def tearDown(self):
        bot.save_event = self._orig_save

    async def test_posts_new_and_deletes_previous(self):
        event = {"name": "X", "announcement_message_id": 111, "ping_message_ids": []}
        ch = _FakeChannel(send_id=222)
        await bot._set_channel_announcement(ch, event, 7, {}, content="hello")
        self.assertEqual(event["announcement_message_id"], 222)
        self.assertEqual(ch.sent, ["hello"])
        self.assertTrue(ch.fetched[111].deleted, "previous announcement should be deleted")
        self.assertTrue(self.save_calls)

    async def test_clear_only_deletes_no_send(self):
        event = {"name": "X", "announcement_message_id": 111, "ping_message_ids": []}
        ch = _FakeChannel()
        await bot._set_channel_announcement(ch, event, 7, {}, content=None)
        self.assertIsNone(event["announcement_message_id"])
        self.assertEqual(ch.send_calls, 0)
        self.assertTrue(ch.fetched[111].deleted)

    async def test_legacy_trackers_swept(self):
        event = {"name": "X", "announcement_message_id": None,
                 "ping_message_ids": [10, 11],
                 "early_access_message_id": 12, "countdown_message_id": 13}
        ch = _FakeChannel(send_id=999)
        await bot._set_channel_announcement(ch, event, 7, {}, content="new")
        self.assertEqual(event["announcement_message_id"], 999)
        self.assertEqual(event["ping_message_ids"], [])
        self.assertIsNone(event["early_access_message_id"])
        self.assertIsNone(event["countdown_message_id"])
        for mid in (10, 11, 12, 13):
            self.assertTrue(ch.fetched[mid].deleted, f"legacy message {mid} should be deleted")

    async def test_ch_none_resets_trackers_and_saves(self):
        event = {"name": "X", "announcement_message_id": 111,
                 "ping_message_ids": [1], "early_access_message_id": 2,
                 "countdown_message_id": 3}
        await bot._set_channel_announcement(None, event, 7, {}, content="hello")
        self.assertIsNone(event["announcement_message_id"])
        self.assertEqual(event["ping_message_ids"], [])
        self.assertIsNone(event["early_access_message_id"])
        self.assertIsNone(event["countdown_message_id"])
        self.assertTrue(self.save_calls)

    async def test_retries_then_succeeds(self):
        event = {"name": "X", "announcement_message_id": None, "ping_message_ids": []}
        ch = _FakeChannel(send_id=555, send_error=[RuntimeError("flaky"), None])
        with patch.object(bot.asyncio, "sleep", new=AsyncMock()):
            await bot._set_channel_announcement(ch, event, 7, {}, content="hi", attempts=2)
        self.assertEqual(ch.send_calls, 2)
        self.assertEqual(event["announcement_message_id"], 555)

    async def test_forbidden_send_does_not_crash(self):
        event = {"name": "X", "announcement_message_id": None, "ping_message_ids": []}
        # discord.Forbidden needs a response to construct normally; build a bare instance.
        forbidden = discord.Forbidden.__new__(discord.Forbidden)
        ch = _FakeChannel(send_error=forbidden)
        await bot._set_channel_announcement(ch, event, 7, {}, content="hi", attempts=2)
        self.assertEqual(ch.send_calls, 1, "Forbidden should not be retried")
        self.assertIsNone(event["announcement_message_id"])
        self.assertTrue(self.save_calls)


if __name__ == "__main__":
    unittest.main()
