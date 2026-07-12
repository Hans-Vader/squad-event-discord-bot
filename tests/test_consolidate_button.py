#!/usr/bin/env python3
"""The organizer admin panel exposes a 'consolidate squads' button in player
mode only, wired to the consolidation confirmation flow."""

import os
import sys
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import bot  # noqa: E402
from i18n import t  # noqa: E402

# AdminActionView resolves the guild language via the DB; force English so the
# tests don't need a database.
bot.get_guild_language = lambda *_a, **_k: "en"


def _labels(view):
    return [c.label for c in view.children if getattr(c, "label", None)]


class AdminConsolidateButtonTest(unittest.TestCase):
    def _panel(self, mode):
        ev = {"mode": mode, "squads": {}}
        with mock.patch.object(bot, "_get_event_by_dbid", return_value=(ev, {}, 1)):
            return bot.AdminActionView(1, 2, 1)

    def test_button_present_in_player_mode(self):
        self.assertIn(t("admin.consolidate_squads", "en"), _labels(self._panel("player")))

    def test_button_absent_in_rep_mode(self):
        self.assertNotIn(t("admin.consolidate_squads", "en"), _labels(self._panel("rep")))


if __name__ == "__main__":
    unittest.main()
