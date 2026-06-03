#!/usr/bin/env python3
"""The pre-creation confirmation summary must list the newer event parameters.

`_build_confirmation_embed` is shown for approval AND re-posted to the log channel,
so it needs to include recurrence, duration, the recreate-after delay, and the
early-access slot caps — not just the original fields.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bot  # noqa: E402
from i18n import t, _STRINGS  # noqa: E402

# _build_confirmation_embed resolves the guild language via the DB; force English
# so the tests don't need a database.
bot.get_guild_language = lambda *_a, **_k: "en"


def _event(**over):
    ev = {
        "name": "Cup Night", "date": "31.12.2099", "time": "20:00",
        "mode": "rep", "registration_open": False, "registration_start_time": None,
        "server_max_players": 100, "max_caster_slots": 2,
        "infantry_squad_size": 6, "vehicle_squad_size": 2, "heli_squad_size": 1,
        "max_vehicle_squads": 2, "max_heli_squads": 1, "max_squads_per_user": 1,
        "event_reminder_minutes": None, "playstyle_enabled": True,
        "recurrence": {"type": "every_weeks", "interval": 1},
        "duration_minutes": 120, "spawn_offset_minutes": 5,
        "community_rep_role_ids": [100], "community_rep_user_ids": [],
        "squad_rep_role_ids": [200], "squad_rep_user_ids": [],
        "caster_role_ids": [], "caster_user_ids": [],
        "caster_community_role_ids": [], "caster_community_user_ids": [],
        "community_rep_cap_percent": 50, "early_access_squads_per_role": 3,
    }
    ev.update(over)
    return ev


def _fields(embed):
    return {f.name: f.value for f in embed.fields}


class TestConfirmationSummary(unittest.TestCase):
    def test_new_params_present(self):
        fields = _fields(bot._build_confirmation_embed(_event(), 0))
        names = "\n".join(fields)
        # The new parameter fields are present.
        self.assertIn(t("wizard.summary_recurrence", "en"), names)
        self.assertIn(t("wizard.summary_duration", "en"), names)
        self.assertIn(t("wizard.summary_spawn_offset", "en"), names)   # recurring → shown
        self.assertIn(t("wizard.summary_slot_limits", "en"), names)
        # Formatted values appear.
        joined = "\n".join(fields.values())
        self.assertIn("50%", joined)              # early-access % cap
        self.assertIn("3", joined)                # max squads per early-access role
        self.assertEqual(fields[t("wizard.summary_duration", "en")],
                         bot._format_duration_value(120, "en"))

    def test_spawn_offset_hidden_when_not_recurring(self):
        fields = _fields(bot._build_confirmation_embed(_event(recurrence={"type": "never"}), 0))
        self.assertNotIn(t("wizard.summary_spawn_offset", "en"), "\n".join(fields))

    def test_slot_limits_hidden_without_early_access_roles(self):
        fields = _fields(bot._build_confirmation_embed(_event(community_rep_role_ids=[]), 0))
        self.assertNotIn(t("wizard.summary_slot_limits", "en"), "\n".join(fields))

    def test_player_mode_omits_squad_per_role_line(self):
        embed = bot._build_confirmation_embed(_event(mode="player"), 0)
        slot_field = _fields(embed).get(t("wizard.summary_slot_limits", "en"), "")
        self.assertIn(t("wizard.summary_early_pct_cap", "en"), slot_field)
        self.assertNotIn(t("wizard.summary_early_squad_cap", "en"), slot_field)

    def test_new_i18n_keys_present(self):
        for key in ("wizard.summary_recurrence", "wizard.summary_duration",
                    "wizard.summary_spawn_offset", "wizard.summary_slot_limits",
                    "wizard.summary_early_pct_cap", "wizard.summary_early_squad_cap"):
            self.assertIn(key, _STRINGS, f"missing {key}")
            for lang in ("de", "en"):
                self.assertNotIn("missing", t(key, lang))


if __name__ == "__main__":
    unittest.main()
