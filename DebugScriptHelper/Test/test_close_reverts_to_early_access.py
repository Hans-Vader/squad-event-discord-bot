#!/usr/bin/env python3
"""The admin 'Close' button should revert a rep/caster event to early-access, not hard-lock it.

Closing used to set is_closed=True (greys out every button and blocks everyone, including
early-access roles). For rep/caster mode it should instead drop back to the not-yet-open state:
registration_open=False, is_closed untouched (False), and registration_start_time cleared so the
background loop doesn't immediately auto-reopen. Early-access roles keep registering with their caps.

Player mode has no early-access gate, so its Close keeps fully locking — but registered members must
still be able to unregister, so the Unregister button stays enabled even when closed.
"""

import os
import sys
import unittest
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import discord  # noqa: E402
import bot  # noqa: E402


class _FakeUser:
    name = "admin"


class _FakeInteraction:
    def __init__(self):
        self.user = _FakeUser()
        self.guild = None


class _FakeRole:
    def __init__(self, rid):
        self.id = rid


class _FakeMember:
    def __init__(self, uid, role_ids=()):
        self.id = uid
        self.roles = [_FakeRole(r) for r in role_ids]


def _btn(view, custom_id):
    for child in view.children:
        if getattr(child, "custom_id", None) == custom_id:
            return child
    return None


class CloseMutationTest(unittest.IsolatedAsyncioTestCase):
    async def _run_close(self, event):
        # Build the view without its __init__ (we only exercise _close, which uses
        # self.guild_id / self.channel_id).
        view = bot.AdminActionView.__new__(bot.AdminActionView)
        view.guild_id, view.channel_id = 1, 2
        save_spy = MagicMock()
        with ExitStack() as es:
            es.enter_context(patch.object(bot, "get_guild_language", return_value="en"))
            es.enter_context(patch.object(bot, "_get_channel_event", return_value=(event, {}, 7)))
            es.enter_context(patch.object(bot, "save_event", save_spy))
            es.enter_context(patch.object(bot, "send_feedback", AsyncMock()))
            es.enter_context(patch.object(bot, "send_to_log_channel", AsyncMock()))
            es.enter_context(patch.object(bot, "update_event_displays", AsyncMock()))
            es.enter_context(patch.object(bot.bot, "get_channel", return_value=None))
            await view._close(_FakeInteraction())
        save_spy.assert_called()
        return event

    async def test_rep_mode_reverts_to_early_access(self):
        event = {
            "name": "Cup Night", "mode": "rep",
            "registration_open": True, "is_closed": False,
            "registration_start_time": datetime(2020, 1, 1, 20, 0),
            "ping_message_ids": [],
        }
        await self._run_close(event)
        self.assertFalse(event["registration_open"])
        # Not hard-locked: buttons stay enabled, early-access roles + caps still apply.
        self.assertFalse(event["is_closed"])
        # Scheduled open cleared so the loop won't immediately auto-reopen.
        self.assertIsNone(event["registration_start_time"])

    async def test_player_mode_stays_fully_locked(self):
        event = {
            "name": "Pub Night", "mode": "player",
            "registration_open": True, "is_closed": False,
            "registration_start_time": datetime(2020, 1, 1, 20, 0),
            "ping_message_ids": [],
        }
        await self._run_close(event)
        self.assertTrue(event["is_closed"])
        self.assertFalse(event["registration_open"])


class PostCloseGatingTest(unittest.TestCase):
    def _closed_rep_event(self):
        # The state a rep event lands in after Close.
        return {
            "name": "Cup Night",
            "date": "31.12.2099", "time": "20:00",  # far future → not "already started"
            "registration_open": False, "is_closed": False,
            "registration_start_time": None,
            "community_rep_role_ids": [111], "community_rep_user_ids": [],
        }

    def test_early_access_role_can_still_register(self):
        event = self._closed_rep_event()
        member = _FakeMember(999, role_ids=[111])
        ok, msg = bot.check_registration_open(event, user=member, registration_type="squad")
        self.assertTrue(ok)
        self.assertIsNone(msg)

    def test_general_user_blocked_and_not_reopened(self):
        event = self._closed_rep_event()
        member = _FakeMember(222, role_ids=[])
        ok, msg = bot.check_registration_open(event, user=member, registration_type="squad")
        self.assertFalse(ok)
        self.assertEqual(msg, "reg.not_open_message")
        # The inline/loop auto-open must NOT fire (start time was cleared).
        self.assertFalse(event["registration_open"])


class ActionButtonDisableTest(unittest.TestCase):
    def _action_buttons(self, view, mode):
        ids = ["event_register_squad", "event_unregister"]
        if mode == "rep":
            ids.append("event_register_caster")
        return {cid: _btn(view, cid) for cid in ids}

    def test_unregister_enabled_while_register_disabled_when_closed(self):
        # Merely closed (not started): register locked, but members can still withdraw.
        for mode in ("player", "rep"):
            view = bot.EventActionView(mode=mode, is_closed=True)
            btns = self._action_buttons(view, mode)
            self.assertFalse(btns["event_unregister"].disabled,
                             f"unregister should stay enabled when closed ({mode})")
            self.assertTrue(btns["event_register_squad"].disabled,
                            f"register should be disabled when closed ({mode})")

    def test_all_action_buttons_disabled_once_event_started(self):
        # event_started disables all three — even with is_closed False (loop hasn't run yet).
        for mode in ("player", "rep"):
            view = bot.EventActionView(mode=mode, is_closed=False, event_started=True)
            for cid, btn in self._action_buttons(view, mode).items():
                self.assertIsNotNone(btn, f"{cid} missing in {mode} mode")
                self.assertTrue(btn.disabled, f"{cid} should be disabled once started ({mode})")

    def test_all_action_buttons_enabled_by_default(self):
        for mode in ("player", "rep"):
            view = bot.EventActionView(mode=mode)
            for cid, btn in self._action_buttons(view, mode).items():
                self.assertFalse(btn.disabled, f"{cid} should be enabled by default ({mode})")


class _FakeMessage:
    edit = AsyncMock()


class _FakeChannel:
    async def fetch_message(self, _mid):
        return _FakeMessage()


class SendEventDetailsWiringTest(unittest.IsolatedAsyncioTestCase):
    async def _captured_kwargs(self, date_str):
        captured = {}

        class _CapturingView:
            def __init__(self, *a, **k):
                captured.update(k)

        event = {"mode": "rep", "is_closed": False, "event_message_id": 999,
                 "date": date_str, "time": "20:00"}
        with ExitStack() as es:
            es.enter_context(patch.object(bot, "format_event_details",
                                          lambda *a, **k: discord.Embed(title="x")))
            es.enter_context(patch.object(bot, "EventActionView", _CapturingView))
            await bot.send_event_details(_FakeChannel(), event, 7, "en", True)
        return captured

    async def test_past_dated_event_passes_event_started_true(self):
        captured = await self._captured_kwargs("01.01.2020")
        self.assertIn("event_started", captured)
        self.assertTrue(captured["event_started"])

    async def test_future_dated_event_passes_event_started_false(self):
        captured = await self._captured_kwargs("31.12.2099")
        self.assertIn("event_started", captured)
        self.assertFalse(captured["event_started"])


if __name__ == "__main__":
    unittest.main()
