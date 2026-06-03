#!/usr/bin/env python3
"""Bot-level admins (ADMIN_IDS) must NOT bypass the registration role gate.

`has_role` is used only by the registration gate, so it's a literal role check —
admins are subject to it like everyone else. Their admin powers come from
`has_organizer_role` / `is_guild_admin`, which keep their own ADMIN_IDS bypass.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _AttrStub(types.ModuleType):
    def __getattr__(self, name):
        placeholder = type(name, (), {})
        setattr(self, name, placeholder)
        return placeholder


# Prefer the real libraries when installed (dev/CI always has discord.py as a
# hard dependency). Only fall back to a lightweight stub when they are absent, so
# this module never replaces a real `discord` in sys.modules and thereby breaks a
# sibling test that does `import bot` (which needs the real discord.ext.commands).
try:
    import discord  # noqa: F401
except ImportError:
    sys.modules["discord"] = _AttrStub("discord")
try:
    import dotenv  # noqa: F401
except ImportError:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = dotenv_stub

import utils  # noqa: E402

RID = 555
ORG = 777
ADMIN_UID = 4242


class _Role:
    def __init__(self, rid):
        self.id = rid


class _Perms:
    def __init__(self, administrator):
        self.administrator = administrator


class _User:
    def __init__(self, uid, role_ids=(), administrator=False):
        self.id = uid
        self.roles = [_Role(r) for r in role_ids]
        self.guild_permissions = _Perms(administrator)


class TestAdminRoleGate(unittest.TestCase):
    def setUp(self):
        self._orig = utils.ADMIN_IDS
        utils.ADMIN_IDS = {str(ADMIN_UID)}

    def tearDown(self):
        utils.ADMIN_IDS = self._orig

    def test_admin_does_not_bypass_has_role(self):
        admin_no_role = _User(ADMIN_UID, role_ids=())
        self.assertFalse(utils.has_role(admin_no_role, RID))

    def test_has_role_is_literal_membership(self):
        self.assertTrue(utils.has_role(_User(1, role_ids=(RID,)), RID))
        self.assertFalse(utils.has_role(_User(1, role_ids=(999,)), RID))

    def test_admin_powers_retained(self):
        admin = _User(ADMIN_UID, role_ids=())
        # Organizer + guild-admin checks still bypass for ADMIN_IDS.
        self.assertTrue(utils.has_organizer_role(admin, ORG))
        self.assertTrue(utils.is_guild_admin(admin))

    def test_non_admin_organizer_still_role_gated(self):
        # A non-admin without the organizer role isn't treated as organizer.
        self.assertFalse(utils.has_organizer_role(_User(1, role_ids=()), ORG))
        self.assertTrue(utils.has_organizer_role(_User(1, role_ids=(ORG,)), ORG))


if __name__ == "__main__":
    unittest.main()
