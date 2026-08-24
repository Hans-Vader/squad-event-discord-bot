#!/usr/bin/env python3
"""Unit tests for per-register-type registration limits (seat % + squads/role).

Covers the pure enforcement helpers: register-type classification (early-access
precedence), the seat-% cap math/base, per-group seat counting in both modes,
per-early-access-role squad counting, the combined gate, percent/squad-count
formatting, and presence of the new i18n keys.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import bot  # noqa: E402
from i18n import t, _STRINGS  # noqa: E402

REG = 200      # regular (squad_rep) role id
EARLY = 100    # early-access (community_rep) role id
EARLY2 = 101   # second early-access role id


class _Role:
    def __init__(self, rid):
        self.id = rid


class _Member:
    def __init__(self, role_ids):
        self.roles = [_Role(r) for r in role_ids]


class _Guild:
    def __init__(self, members):
        self._m = members  # {int uid: _Member}

    def get_member(self, uid):
        return self._m.get(int(uid))


def _event(**over):
    ev = {
        "mode": "rep",
        "max_player_slots": 98,
        "squad_rep_role_ids": [REG],
        "community_rep_role_ids": [EARLY],
        "community_rep_cap_percent": None,
        "early_access_squads_per_role": None,
        "squads": {},
    }
    ev.update(over)
    return ev


class TestRegisterType(unittest.TestCase):
    def test_precedence_and_classification(self):
        ev = _event()
        self.assertEqual(bot._member_register_type(_Member([EARLY]), ev), "community_rep")
        self.assertEqual(bot._member_register_type(_Member([REG]), ev), "squad_rep")
        # both roles → early-access wins
        self.assertEqual(bot._member_register_type(_Member([REG, EARLY]), ev), "community_rep")
        self.assertIsNone(bot._member_register_type(_Member([999]), ev))
        self.assertIsNone(bot._member_register_type(None, ev))


class TestSeatCap(unittest.TestCase):
    def test_floor_math_and_none(self):
        ev = _event(community_rep_cap_percent=5)
        # Only early access (community_rep) is capped; regular registration never is.
        self.assertIsNone(bot._seat_cap_slots(ev, "squad_rep"))
        self.assertEqual(bot._seat_cap_slots(ev, "community_rep"), 4)   # 5% of 98 = 4.9 → 4
        self.assertIsNone(bot._seat_cap_slots(_event(), "community_rep"))  # unset → None


class TestSeatsUsed(unittest.TestCase):
    def test_rep_mode_counts_by_rep_group(self):
        ev = _event(squads={"s1": {"size": 6}, "s2": {"size": 2}})
        ua = {"10": ["s1"], "20": ["s2"]}
        guild = _Guild({10: _Member([EARLY]), 20: _Member([REG])})
        self.assertEqual(bot._group_seats_used(ev, ua, guild, "community_rep"), 6)
        self.assertEqual(bot._group_seats_used(ev, ua, guild, "squad_rep"), 2)

    def test_player_mode_counts_members(self):
        ev = _event(mode="player",
                    squads={"Inf 1": {"members": [{"user_id": "10"}, {"user_id": "20"}]}})
        guild = _Guild({10: _Member([EARLY]), 20: _Member([REG])})
        self.assertEqual(bot._group_seats_used(ev, {}, guild, "community_rep"), 1)
        self.assertEqual(bot._group_seats_used(ev, {}, guild, "squad_rep"), 1)


class TestEarlyAccessRoleCounts(unittest.TestCase):
    def test_per_role_counting_with_multi_role_rep(self):
        ev = _event(community_rep_role_ids=[EARLY, EARLY2],
                    squads={"s1": {"size": 6}, "s2": {"size": 6}})
        ua = {"10": ["s1"], "20": ["s2"]}
        guild = _Guild({10: _Member([EARLY, EARLY2]), 20: _Member([EARLY])})
        counts = bot._early_access_role_squad_counts(ev, ua, guild)
        self.assertEqual(counts[EARLY], 2)
        self.assertEqual(counts[EARLY2], 1)


class TestSplitCaps(unittest.TestCase):
    """The seat-% cap and the per-role squad-count cap are checked independently."""

    def test_seat_cap_only(self):
        ev = _event(community_rep_cap_percent=5, squads={"s1": {"size": 4}})  # cap = 4
        ua = {"10": ["s1"]}
        guild = _Guild({10: _Member([EARLY])})
        self.assertEqual(bot._check_seat_cap(ev, ua, guild, _Member([EARLY]), 1)[1],
                         "gate.seat_cap_reached")
        self.assertTrue(bot._check_seat_cap(_event(community_rep_cap_percent=50), {},
                                            _Guild({}), _Member([EARLY]), 6)[0])
        # Seat cap ignores the per-role squad cap entirely.
        self.assertTrue(bot._check_seat_cap(
            _event(early_access_squads_per_role=1, squads={"s1": {"size": 6}}),
            {"10": ["s1"]}, _Guild({10: _Member([EARLY])}), _Member([EARLY]), 6)[0])
        # Lifted once open; no-op for ungrouped.
        self.assertTrue(bot._check_seat_cap(
            _event(registration_open=True, community_rep_cap_percent=1), {}, _Guild({}),
            _Member([EARLY]), 50)[0])
        self.assertTrue(bot._check_seat_cap(
            _event(community_rep_cap_percent=1), {}, _Guild({}), _Member([999]), 50)[0])

    def test_squad_count_cap_only(self):
        ev = _event(early_access_squads_per_role=1, squads={"s1": {"size": 6}})
        ua = {"10": ["s1"]}
        guild = _Guild({10: _Member([EARLY])})
        self.assertEqual(bot._check_squad_count_cap(ev, ua, guild, _Member([EARLY]), "rep")[1],
                         "gate.squad_role_cap_reached")
        # Count cap ignores the seat-% cap; rep-only; lifted once open.
        self.assertTrue(bot._check_squad_count_cap(
            _event(community_rep_cap_percent=5, squads={"s1": {"size": 99}}),
            {"10": ["s1"]}, _Guild({10: _Member([EARLY])}), _Member([EARLY]), "rep")[0])
        self.assertTrue(bot._check_squad_count_cap(ev, ua, guild, _Member([EARLY]), "player")[0])
        self.assertTrue(bot._check_squad_count_cap(
            _event(registration_open=True, early_access_squads_per_role=1,
                   squads={"s1": {"size": 6}}),
            ua, guild, _Member([EARLY]), "rep")[0])


class TestCapUsageStrings(unittest.TestCase):
    """Usage strings shown in the confirm/reject messages."""

    def test_seat_cap_usage(self):
        # 4 seats used of 98 → 4%, cap 50%.
        ev = _event(community_rep_cap_percent=50, max_player_slots=98, squads={"s1": {"size": 4}})
        guild = _Guild({10: _Member([EARLY])})
        self.assertEqual(bot._seat_cap_usage(ev, {"10": ["s1"]}, guild, _Member([EARLY])), "4%/50%")
        # None when uncapped / open / ungrouped.
        self.assertIsNone(bot._seat_cap_usage(_event(), {}, _Guild({}), _Member([EARLY])))
        self.assertIsNone(bot._seat_cap_usage(
            _event(registration_open=True, community_rep_cap_percent=50), {}, _Guild({}), _Member([EARLY])))
        self.assertIsNone(bot._seat_cap_usage(
            _event(community_rep_cap_percent=50), {}, _Guild({}), _Member([999])))

    def test_squad_role_cap_usage(self):
        # Member holds two early-access roles; show the most-used one.
        ev = _event(community_rep_role_ids=[EARLY, EARLY2], early_access_squads_per_role=5,
                    squads={"s1": {"size": 6}, "s2": {"size": 6}})
        ua = {"10": ["s1"], "20": ["s2"]}
        guild = _Guild({10: _Member([EARLY, EARLY2]), 20: _Member([EARLY])})
        # EARLY has 2 squads, EARLY2 has 1 → binding is 2/5.
        self.assertEqual(bot._squad_role_cap_usage(ev, ua, guild, _Member([EARLY, EARLY2])), "2/5")
        self.assertIsNone(bot._squad_role_cap_usage(_event(), {}, _Guild({}), _Member([EARLY])))

    def test_check_returns_usage_on_block(self):
        ev = _event(community_rep_cap_percent=5, max_player_slots=98, squads={"s1": {"size": 4}})
        ua = {"10": ["s1"]}
        guild = _Guild({10: _Member([EARLY])})
        ok, key, usage = bot._check_seat_cap(ev, ua, guild, _Member([EARLY]), 1)
        self.assertFalse(ok)
        self.assertTrue(usage and usage.endswith("/5%"))
        ev2 = _event(early_access_squads_per_role=1, squads={"s1": {"size": 6}})
        ok, key, usage = bot._check_squad_count_cap(ev2, {"10": ["s1"]},
                                                    _Guild({10: _Member([EARLY])}), _Member([EARLY]), "rep")
        self.assertFalse(ok)
        self.assertEqual(usage, "1/1")


class TestCheckRegistrationLimits(unittest.TestCase):
    def test_seat_cap_rejects(self):
        ev = _event(community_rep_cap_percent=5,  # cap = 4 seats
                    squads={"s1": {"size": 4}})
        ua = {"10": ["s1"]}
        guild = _Guild({10: _Member([EARLY])})
        ok, key, _usage = bot._check_registration_limits(ev, ua, guild, _Member([EARLY]), 1, "rep")
        self.assertFalse(ok)
        self.assertEqual(key, "gate.seat_cap_reached")

    def test_seat_cap_allows_under(self):
        ev = _event(community_rep_cap_percent=50)  # cap = 49
        ok, key, _usage = bot._check_registration_limits(ev, {}, _Guild({}), _Member([EARLY]), 6, "rep")
        self.assertTrue(ok)
        self.assertIsNone(key)

    def test_per_role_squad_cap_rejects(self):
        ev = _event(early_access_squads_per_role=1, squads={"s1": {"size": 6}})
        ua = {"10": ["s1"]}
        guild = _Guild({10: _Member([EARLY])})
        ok, key, _usage = bot._check_registration_limits(ev, ua, guild, _Member([EARLY]), 6, "rep")
        self.assertFalse(ok)
        self.assertEqual(key, "gate.squad_role_cap_reached")

    def test_player_mode_ignores_squad_count_cap(self):
        ev = _event(mode="player", early_access_squads_per_role=1,
                    squads={"Inf 1": {"members": [{"user_id": "10"}]}})
        guild = _Guild({10: _Member([EARLY])})
        ok, key, _usage = bot._check_registration_limits(ev, {}, guild, _Member([EARLY]), 1, "player")
        self.assertTrue(ok)  # squad-count cap is rep-only; no seat-% cap set

    def test_ungrouped_member_unrestricted(self):
        ev = _event(community_rep_cap_percent=1)
        ok, key, _usage = bot._check_registration_limits(ev, {}, _Guild({}), _Member([999]), 50, "rep")
        self.assertTrue(ok)
        self.assertIsNone(key)

    def test_user_squad_limit_exemption(self):
        # Early-access member skips the per-user squad limit only while closed.
        self.assertTrue(bot._exempt_from_user_squad_limit(_event(), _Member([EARLY])))
        self.assertFalse(
            bot._exempt_from_user_squad_limit(_event(registration_open=True), _Member([EARLY])))
        # Regular and ungrouped members are never exempt.
        self.assertFalse(bot._exempt_from_user_squad_limit(_event(), _Member([REG])))
        self.assertFalse(bot._exempt_from_user_squad_limit(_event(), _Member([999])))

    def test_early_access_limits_lifted_once_registration_open(self):
        # Both caps are exceeded, but registration is open → limits lifted.
        ev = _event(registration_open=True,
                    community_rep_cap_percent=5,        # cap = 4 seats
                    early_access_squads_per_role=1,
                    squads={"s1": {"size": 6}})
        ua = {"10": ["s1"]}
        guild = _Guild({10: _Member([EARLY])})
        ok, key, _usage = bot._check_registration_limits(ev, ua, guild, _Member([EARLY]), 6, "rep")
        self.assertTrue(ok)
        self.assertIsNone(key)


class TestFormattingAndPresets(unittest.TestCase):
    def test_percent_and_count_format(self):
        self.assertEqual(bot._format_property_value({"community_rep_cap_percent": 50}, "community_rep_cap_percent", "percent", "en"), "50%")
        self.assertEqual(bot._format_property_value({"community_rep_cap_percent": None}, "community_rep_cap_percent", "percent", "en"), "No limit")
        self.assertEqual(bot._format_property_value({"early_access_squads_per_role": 3}, "early_access_squads_per_role", "squad_count", "en"), "3")
        self.assertEqual(bot._format_property_value({"early_access_squads_per_role": None}, "early_access_squads_per_role", "squad_count", "de"), "Kein Limit")

    def test_preset_lists_and_none_sentinel(self):
        self.assertIsNone(bot._PERCENT_PRESETS[0])
        self.assertIsNone(bot._COUNT_PRESETS[0])
        self.assertLessEqual(len(bot._PERCENT_PRESETS), 25)
        self.assertLessEqual(len(bot._COUNT_PRESETS), 25)
        self.assertNotIn(96, bot._PERCENT_PRESETS)  # 96–99 dropped to fit the cap
        opts = bot._capped_options("limit.prefix.regular", bot._PERCENT_PRESETS,
                                   bot._format_percent_value, "en", 50)
        self.assertEqual(opts[0].value, "none")
        self.assertEqual(opts[0].label, "Regular: No limit")  # context-carrying label
        self.assertTrue(any(o.value == "50" and o.default and o.label == "Regular: 50%" for o in opts))
        self.assertIsNone(bot.WizardSlotLimitsView._value("none"))
        self.assertEqual(bot.WizardSlotLimitsView._value("50"), 50)


class TestI18nKeys(unittest.TestCase):
    KEYS = [
        "limit.none", "percent.value", "wizard.slot_limits_title", "wizard.slot_limits_desc",
        "wizard.cap_early_pct_title", "wizard.cap_early_squads_title",
        "edit.property.early_pct_cap", "edit.property.early_squad_cap",
        "gate.seat_cap_reached", "gate.squad_role_cap_reached",
        "limit.prefix.regular", "limit.prefix.early", "limit.squads_per_user", "limit.squads_per_role",
        "wizard.cap_regular_squads_title",
        "squad.cap_info_seat", "squad.cap_info_squads",
    ]

    def test_gate_messages_have_usage_placeholder(self):
        for k in ("gate.seat_cap_reached", "gate.squad_role_cap_reached"):
            for lang in ("de", "en"):
                self.assertIn("{usage}", _STRINGS[k][lang])

    def test_present_both_languages(self):
        for k in self.KEYS:
            self.assertIn(k, _STRINGS, f"missing {k}")
            for lang in ("de", "en"):
                self.assertNotIn("missing", t(k, lang))

    def test_role_labels_no_longer_mention_users(self):
        for k in ("wizard.squad_rep_title", "wizard.community_rep_title",
                  "wizard.summary_squad_roles", "wizard.summary_community_roles"):
            for lang in ("de", "en"):
                v = t(k, lang)
                self.assertNotIn("/users", v)
                self.assertNotIn("/Benutzer", v)


if __name__ == "__main__":
    unittest.main()
