#!/usr/bin/env python3
"""Unit tests for application-emoji resolution (utils.role_emoji).

Role icons are Discord *application emojis* resolved by name at startup and cached
in utils._APP_EMOJI (via set_application_emojis). role_emoji() maps a role -> emoji
name (ROLE_EMOJI_NAME) -> cached "<:name:id>" string, or None when not uploaded.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

try:
    import discord  # noqa: F401
except ImportError:
    class _AttrStub(types.ModuleType):
        def __getattr__(self, name):
            placeholder = type(name, (), {})
            setattr(self, name, placeholder)
            return placeholder
    sys.modules["discord"] = _AttrStub("discord")
try:
    import dotenv  # noqa: F401
except ImportError:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = dotenv_stub

import utils  # noqa: E402


class _FakeEmoji:
    """Mimics discord.Emoji: has a .name and stringifies to <:name:id>."""
    def __init__(self, name, id_):
        self.name = name
        self._id = id_

    def __str__(self):
        return f"<:{self.name}:{self._id}>"


class RoleEmojiTest(unittest.TestCase):
    def setUp(self):
        # Isolate the module-level cache from other tests / real startup.
        self._saved = utils._APP_EMOJI
        self.addCleanup(lambda: setattr(utils, "_APP_EMOJI", self._saved))

    def test_resolves_by_name_after_load(self):
        n = utils.set_application_emojis([_FakeEmoji("sl", 111), _FakeEmoji("vic_sl", 222)])
        self.assertEqual(n, 2)
        self.assertEqual(utils.role_emoji("Squad Leader"), "<:sl:111>")
        # Driver deliberately aliases the crew-leader icon :vic_sl:.
        self.assertEqual(utils.role_emoji("Driver"), "<:vic_sl:222>")

    def test_missing_emoji_returns_none(self):
        utils.set_application_emojis([_FakeEmoji("sl", 111)])
        # Uploaded set has no "medic" -> caller falls back to the text label.
        self.assertIsNone(utils.role_emoji("Medic"))

    def test_unknown_role_returns_none(self):
        utils.set_application_emojis([_FakeEmoji("sl", 111)])
        self.assertIsNone(utils.role_emoji("Not A Role"))

    def test_empty_cache_returns_none(self):
        utils.set_application_emojis([])
        self.assertIsNone(utils.role_emoji("Squad Leader"))


class UnarmedSuffixTest(unittest.TestCase):
    """No role chosen -> _format_role_suffix shows the unarmed icon (if uploaded)."""
    def setUp(self):
        self._saved = utils._APP_EMOJI
        self.addCleanup(lambda: setattr(utils, "_APP_EMOJI", self._saved))

    def test_no_role_shows_unarmed_when_loaded(self):
        utils.set_application_emojis([_FakeEmoji("unarmed", 999)])
        self.assertEqual(utils._format_role_suffix([], "de", True), " (<:unarmed:999>)")

    def test_no_role_blank_when_unarmed_not_uploaded(self):
        utils.set_application_emojis([_FakeEmoji("sl", 111)])
        self.assertEqual(utils._format_role_suffix([], "de", True), "")

    def test_roles_disabled_never_shows_unarmed(self):
        utils.set_application_emojis([_FakeEmoji("unarmed", 999)])
        self.assertEqual(utils._format_role_suffix([], "de", False), "")

    def test_chosen_role_wins_over_unarmed(self):
        utils.set_application_emojis([_FakeEmoji("sl", 111), _FakeEmoji("unarmed", 999)])
        self.assertEqual(utils._format_role_suffix(["Squad Leader"], "de", True), " (<:sl:111>)")


if __name__ == "__main__":
    unittest.main()
