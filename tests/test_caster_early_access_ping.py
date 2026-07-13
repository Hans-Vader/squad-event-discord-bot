#!/usr/bin/env python3
"""Caster early-access users must be pinged when an event is created not-yet-open.

The creation-time early-access ping (WizardConfirmationView._confirm) used to mention only the
squad-side community reps (community_rep_*), silently ignoring the caster early-access ids
(caster_community_*). So the casters an organizer granted early access never got pinged — and if
ONLY casters had early access, no early-access ping fired at all. Both id pairs must be included.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import discord  # noqa: E402
import bot  # noqa: E402


class _FakeMessage:
    def __init__(self, mid=999):
        self.id = mid


class _FakeChannel:
    def __init__(self):
        self.sent = []  # list of content strings

    async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
        self.sent.append(content)
        return _FakeMessage()


def _make_event(**overrides):
    ev = {
        "name": "Cup Night", "date": "31.12.2099", "time": "20:00",
        "mode": "rep", "max_caster_slots": 2,
        "ping_on_open": True, "registration_open": False,
        "community_rep_role_ids": [], "community_rep_user_ids": [],
        "caster_community_role_ids": [], "caster_community_user_ids": [],
    }
    ev.update(overrides)
    return ev


class CasterEarlyAccessPingTest(unittest.IsolatedAsyncioTestCase):
    async def _run_confirm(self, event):
        ch = _FakeChannel()
        interaction = MagicMock()
        interaction.response.edit_message = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        view = bot.WizardConfirmationView(7, 42, event, {}, {}, MagicMock(name="creator"))
        with patch.object(bot, "get_guild_language", return_value="de"), \
             patch.object(bot.bot, "get_channel", return_value=ch), \
             patch.object(bot, "format_event_details", return_value=discord.Embed()), \
             patch.object(bot, "EventActionView", return_value=MagicMock()), \
             patch.object(bot, "create_event", return_value=1), \
             patch.object(bot, "save_event"), \
             patch.object(bot, "send_to_log_channel", new=AsyncMock()), \
             patch.object(bot, "_build_confirmation_embed", return_value=discord.Embed()), \
             patch.object(bot, "get_log_channel", return_value=None):
            await view._confirm(interaction)
        # The early-access ping is the second send (first is the event embed).
        return ch.sent[1] if len(ch.sent) > 1 else None

    async def test_caster_early_users_are_pinged(self):
        ping = await self._run_confirm(_make_event(caster_community_user_ids=["555", "666"]))
        self.assertIsNotNone(ping, "an early-access ping should fire for caster-only early access")
        self.assertIn("<@555>", ping)
        self.assertIn("<@666>", ping)

    async def test_caster_early_roles_and_reps_combined(self):
        ping = await self._run_confirm(_make_event(
            community_rep_user_ids=["111"], caster_community_role_ids=["222"]))
        self.assertIn("<@111>", ping)
        self.assertIn("<@&222>", ping)

    async def test_no_early_ids_no_ping(self):
        ch_sent = await self._run_confirm(_make_event())
        self.assertIsNone(ch_sent, "no early-access ids → no early-access ping")


if __name__ == "__main__":
    unittest.main()
