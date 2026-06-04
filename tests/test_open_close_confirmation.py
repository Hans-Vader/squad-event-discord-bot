#!/usr/bin/env python3
"""Admin Open/Close ask for confirmation before acting; Open warns about pings.

Clicking Open or Close in the admin panel now sends an ephemeral Confirm/Cancel prompt
and does NOT act immediately. The Open prompt lists the roles/users that will be pinged
when ping_on_open is configured (rendered as mentions in the embed, which does not ping).
The real open/close work runs only on Confirm.
"""

import os
import sys
import unittest
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import discord  # noqa: E402
import bot  # noqa: E402

# Views/handlers resolve the guild language via the DB; force English so tests need no DB.
bot.get_guild_language = lambda *_a, **_k: "en"


class _Response:
    def __init__(self):
        self.sent = None

    async def send_message(self, content=None, embed=None, view=None, ephemeral=False):
        self.sent = {"content": content, "embed": embed, "view": view}

    async def defer(self, *a, **k):
        pass

    async def edit_message(self, **kwargs):
        self.sent = kwargs


class _Interaction:
    def __init__(self):
        self.response = _Response()
        self.message = None
        self.guild = None
        self.user = type("U", (), {"name": "admin"})()


def _admin_view():
    v = bot.AdminActionView.__new__(bot.AdminActionView)
    v.guild_id, v.channel_id = 1, 2
    return v


class OpenConfirmEmbedTest(unittest.TestCase):
    def _event(self, **over):
        ev = {"name": "Cup Night", "ping_on_open": False,
              "ping_role_ids": [], "squad_rep_role_ids": [], "squad_rep_user_ids": [],
              "caster_role_ids": [], "caster_user_ids": []}
        ev.update(over)
        return ev

    def test_warning_lists_targets_when_ping_configured(self):
        embed = bot._build_open_confirm_embed(self._event(ping_on_open=True, ping_role_ids=[123]), "en")
        self.assertIn("<@&123>", embed.description)
        self.assertIn("notification", embed.description.lower())

    def test_no_warning_when_ping_disabled(self):
        embed = bot._build_open_confirm_embed(self._event(ping_on_open=False, ping_role_ids=[123]), "en")
        self.assertNotIn("<@&123>", embed.description)
        self.assertNotIn("notification", embed.description.lower())

    def test_no_warning_when_no_targets(self):
        embed = bot._build_open_confirm_embed(self._event(ping_on_open=True), "en")
        self.assertNotIn("notification", embed.description.lower())


class AdminShowsPromptTest(unittest.IsolatedAsyncioTestCase):
    async def test_open_shows_confirmation_without_opening(self):
        event = {"name": "X", "registration_open": False, "ping_on_open": False}
        with patch.object(bot, "_get_channel_event", return_value=(event, {}, 7)):
            inter = _Interaction()
            await _admin_view()._open(inter)
        self.assertIsInstance(inter.response.sent["view"], bot.OpenConfirmationView)
        self.assertFalse(event["registration_open"], "Open must not act before confirmation")

    async def test_open_already_open_skips_confirmation(self):
        event = {"name": "X", "registration_open": True}
        captured = {}

        async def _fb(interaction, msg, **k):
            captured["msg"] = msg

        with ExitStack() as es:
            es.enter_context(patch.object(bot, "_get_channel_event", return_value=(event, {}, 7)))
            es.enter_context(patch.object(bot, "send_feedback", _fb))
            inter = _Interaction()
            await _admin_view()._open(inter)
        self.assertIsNone(inter.response.sent, "no confirmation when already open")
        self.assertEqual(captured["msg"], bot.t("reg.already_open", "en"))

    async def test_close_shows_confirmation_without_closing(self):
        event = {"name": "X", "mode": "rep", "registration_open": True, "is_closed": False}
        with patch.object(bot, "_get_channel_event", return_value=(event, {}, 7)):
            inter = _Interaction()
            await _admin_view()._close(inter)
        self.assertIsInstance(inter.response.sent["view"], bot.CloseConfirmationView)
        self.assertTrue(event["registration_open"], "Close must not act before confirmation")
        self.assertFalse(event["is_closed"])


class ConfirmPerformsActionTest(unittest.IsolatedAsyncioTestCase):
    async def _run_confirm(self, view, event):
        save_spy = MagicMock()
        with ExitStack() as es:
            es.enter_context(patch.object(bot, "_get_channel_event", return_value=(event, {}, 7)))
            es.enter_context(patch.object(bot, "save_event", save_spy))
            es.enter_context(patch.object(bot, "send_feedback", AsyncMock()))
            es.enter_context(patch.object(bot, "send_to_log_channel", AsyncMock()))
            es.enter_context(patch.object(bot, "update_event_displays", AsyncMock()))
            es.enter_context(patch.object(bot, "_set_channel_announcement", AsyncMock()))
            es.enter_context(patch.object(bot.bot, "get_channel", return_value=None))
            await view._confirm(_Interaction())
        return save_spy

    async def test_open_confirm_opens_registration(self):
        event = {"name": "X", "registration_open": False, "is_closed": False, "ping_on_open": False}
        await self._run_confirm(bot.OpenConfirmationView(1, 2), event)
        self.assertTrue(event["registration_open"])
        self.assertFalse(event["is_closed"])

    async def test_close_confirm_rep_reverts_to_early_access(self):
        event = {"name": "X", "mode": "rep", "registration_open": True, "is_closed": False,
                 "registration_start_time": datetime(2020, 1, 1, 20, 0)}
        await self._run_confirm(bot.CloseConfirmationView(1, 2), event)
        self.assertFalse(event["registration_open"])
        self.assertFalse(event["is_closed"])
        self.assertIsNone(event["registration_start_time"])

    async def test_close_confirm_player_mode_locks(self):
        event = {"name": "X", "mode": "player", "registration_open": True, "is_closed": False}
        await self._run_confirm(bot.CloseConfirmationView(1, 2), event)
        self.assertTrue(event["is_closed"])
        self.assertFalse(event["registration_open"])


if __name__ == "__main__":
    unittest.main()
