#!/usr/bin/env python3
"""Unit tests for the event-settings log-channel feature.

Covers the new i18n title key used when the approved event settings are posted
to the guild log channel after event creation.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

from i18n import t  # noqa: E402


class TestEventCreatedSettingsTitle(unittest.TestCase):
    def test_german_title_includes_event_name(self):
        result = t("log.event_created_settings_title", "de", name="Operation Foo")
        self.assertEqual(result, "Event-Einstellungen: Operation Foo")

    def test_english_title_includes_event_name(self):
        result = t("log.event_created_settings_title", "en", name="Operation Foo")
        self.assertEqual(result, "Event settings: Operation Foo")

    def test_key_is_defined(self):
        # A defined key must not fall back to the missing-key placeholder.
        result = t("log.event_created_settings_title", "de", name="X")
        self.assertNotIn("missing", result)


if __name__ == "__main__":
    unittest.main()
