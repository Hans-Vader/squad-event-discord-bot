#!/usr/bin/env python3
"""Mode-neutral role labels in the "Role Configuration" Step 1 wizard.

The first role-config step is shared between rep mode and player mode, so its
labels must describe function ("allowed to register" / "early access") rather
than squad-mode personas ("Squad rep" / "Community rep"). The step title also
carries a step counter that only applies in rep mode (player mode skips the
later caster step), so the counter is injected per-mode via the {step} slot.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

from i18n import t  # noqa: E402


class TestRoleLabelUnification(unittest.TestCase):
    def test_squad_rep_title_is_function_based(self):
        # Roles-only now (user selection was removed for these groups).
        self.assertEqual(t("wizard.squad_rep_title", "en"),
                         "Roles allowed to register (optional)")
        self.assertEqual(t("wizard.squad_rep_title", "de"),
                         "Rollen mit Anmeldeberechtigung (optional)")

    def test_community_rep_title_is_early_access(self):
        self.assertEqual(t("wizard.community_rep_title", "en"),
                         "Roles with early access (optional)")
        self.assertEqual(t("wizard.community_rep_title", "de"),
                         "Rollen mit Vorab-Zugang (optional)")

    def test_summary_labels_match_selects(self):
        self.assertEqual(t("wizard.summary_squad_roles", "en"),
                         "Roles allowed to register")
        self.assertEqual(t("wizard.summary_community_roles", "en"),
                         "Roles with early access")
        self.assertEqual(t("wizard.summary_squad_roles", "de"),
                         "Rollen mit Anmeldeberechtigung")
        self.assertEqual(t("wizard.summary_community_roles", "de"),
                         "Rollen mit Vorab-Zugang")

    def test_no_squad_mode_jargon_remains(self):
        for key in ("wizard.squad_rep_title", "wizard.community_rep_title",
                    "wizard.summary_squad_roles", "wizard.summary_community_roles",
                    "wizard.squad_roles_desc"):
            for lang in ("en", "de"):
                value = t(key, lang)
                self.assertNotIn("missing", value)
                self.assertNotIn("Squad rep", value)
                self.assertNotIn("Community rep", value)
                self.assertNotIn("Squad-Rep", value)
                self.assertNotIn("Community-Rep", value)

    def test_squad_denied_message_is_mode_neutral(self):
        for lang in ("en", "de"):
            value = t("gate.squad_denied", lang)
            self.assertNotIn("squad", value.lower())

    def test_wizard_titles_have_no_step_counter(self):
        # Step counters like "1/2" / "Schritt 1/2" were removed from all wizard titles.
        self.assertEqual(t("wizard.squad_roles_title", "en"), "Role Configuration: Registration Access")
        self.assertEqual(t("wizard.squad_roles_title", "de"), "Rollen-Konfiguration: Anmeldeberechtigung")
        for key in ("wizard.squad_roles_title", "wizard.caster_roles_title", "squad.step_1_title"):
            for lang in ("en", "de"):
                value = t(key, lang)
                self.assertNotRegex(value, r"\d+\s*/\s*\d+")
                self.assertNotIn("Step ", value)
                self.assertNotIn("Schritt ", value)


if __name__ == "__main__":
    unittest.main()
