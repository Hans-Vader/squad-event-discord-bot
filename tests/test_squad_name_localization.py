#!/usr/bin/env python3
"""Translation keys for localized player-mode squad-name labels.

Player-mode squads are auto-named in a canonical English form ("Infantry 1")
that doubles as the stored dict key. The embed localizes the label at render
time using these keys, so a German guild shows "Infanterie 1".
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

from i18n import t  # noqa: E402


class TestSquadLabelTranslations(unittest.TestCase):
    def test_infantry_labels(self):
        self.assertEqual(t("squad.label_infantry", "de"), "Infanterie")
        self.assertEqual(t("squad.label_infantry", "en"), "Infantry")

    def test_vehicle_labels(self):
        self.assertEqual(t("squad.label_vehicle", "de"), "Fahrzeug")
        self.assertEqual(t("squad.label_vehicle", "en"), "Vehicle")

    def test_heli_labels(self):
        self.assertEqual(t("squad.label_heli", "de"), "Heli")
        self.assertEqual(t("squad.label_heli", "en"), "Heli")

    def test_keys_are_defined(self):
        for tk in ("infantry", "vehicle", "heli"):
            self.assertNotIn("missing", t(f"squad.label_{tk}", "de"))


if __name__ == "__main__":
    unittest.main()
