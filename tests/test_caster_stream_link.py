#!/usr/bin/env python3
"""Optional stream links for casters.

When an event has `caster_stream_links_enabled`, the caster button opens a modal
with one optional URL field instead of registering straight away. The stored URL
renders as a clickable link behind the caster's name in the public event embed —
so it is validated hard on input: http(s) only, no whitespace and no brackets,
otherwise a caster could break out of the markdown link syntax.

Links live in `event["caster_stream_urls"]` (uid → url), deliberately separate
from `event["casters"]`, so a link survives a waitlist → caster promotion without
the promotion code knowing about it. Every caster-removal path drops the link.
"""

import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import discord  # noqa: E402
import bot  # noqa: E402
import utils  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self):
        self.messages = []
        self.modals = []
        self.deferred = False

    async def send_message(self, content=None, **kwargs):
        self.messages.append(content)

    async def send_modal(self, modal):
        self.modals.append(modal)

    async def defer(self, **kwargs):
        self.deferred = True


class _FakeUser:
    def __init__(self, uid="u1", name="Cass"):
        self.id = uid
        self.name = name
        self.display_name = name
        self.roles = []


class _FakeGuild:
    id = 1


class _Interaction:
    def __init__(self, user=None):
        self.guild = _FakeGuild()
        self.channel_id = 2
        self.user = user or _FakeUser()
        self.response = _FakeResponse()
        self.extras = {}
        self.message = None


def _event(**overrides):
    ev = {
        "name": "Cup Night",
        "date": "31.12.2099", "time": "20:00",
        "mode": "rep",
        "registration_open": True, "is_closed": False,
        "max_caster_slots": 2, "caster_slots_used": 0,
        "casters": {}, "caster_waitlist": [],
        "caster_role_ids": [], "caster_user_ids": [],
        "caster_community_role_ids": [], "caster_community_user_ids": [],
        "caster_stream_links_enabled": True,
        "caster_stream_urls": {},
    }
    ev.update(overrides)
    return ev


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

class ValidateStreamUrlTest(unittest.TestCase):
    def test_accepts_https_and_http(self):
        for raw in ("https://twitch.tv/someone", "http://example.org/live"):
            url, err = bot._validate_stream_url(raw)
            self.assertIsNone(err, raw)
            self.assertEqual(url, raw)

    def test_strips_surrounding_whitespace(self):
        url, err = bot._validate_stream_url("  https://twitch.tv/x  ")
        self.assertIsNone(err)
        self.assertEqual(url, "https://twitch.tv/x")

    def test_empty_means_no_link(self):
        for raw in ("", "   ", None):
            self.assertEqual(bot._validate_stream_url(raw), (None, None))

    def test_rejects_missing_scheme(self):
        for raw in ("twitch.tv/x", "www.twitch.tv/x", "ftp://twitch.tv/x", "//twitch.tv/x"):
            url, err = bot._validate_stream_url(raw)
            self.assertEqual(err, "caster.stream_link_invalid", raw)
            self.assertIsNone(url)

    def test_rejects_scheme_without_host(self):
        url, err = bot._validate_stream_url("https://")
        self.assertEqual(err, "caster.stream_link_invalid")
        self.assertIsNone(url)

    def test_rejects_markdown_breakout(self):
        # The classic escape: close the link early and append your own markdown.
        attacks = [
            "https://ok.tv/a) [click me](https://evil.tv",
            "https://ok.tv/a](https://evil.tv)",
            "https://ok.tv/<script>",
            "https://ok.tv/a b",
            "https://ok.tv/a\nhttps://evil.tv",
            "https://ok.tv/`x`",
            "https://ok.tv/a|b",
            'https://ok.tv/"x"',
        ]
        for raw in attacks:
            url, err = bot._validate_stream_url(raw)
            self.assertEqual(err, "caster.stream_link_invalid", raw)
            self.assertIsNone(url, raw)

    def test_rejects_overlong_url(self):
        url, err = bot._validate_stream_url("https://twitch.tv/" + "x" * bot.STREAM_URL_MAX_LENGTH)
        self.assertEqual(err, "caster.stream_link_invalid")
        self.assertIsNone(url)

    def test_javascript_scheme_rejected(self):
        url, err = bot._validate_stream_url("javascript:alert(1)")
        self.assertEqual(err, "caster.stream_link_invalid")
        self.assertIsNone(url)


# ---------------------------------------------------------------------------
# Embed rendering
# ---------------------------------------------------------------------------

class EmbedRenderingTest(unittest.TestCase):
    def _caster_field(self, event, lang="en"):
        embed = utils.format_event_details(event, lang, caster_enabled=True)
        for field in embed.fields:
            if "Caster" in field.name:
                return field.value
        self.fail("no caster field in embed")

    def test_link_rendered_behind_name(self):
        event = _event(
            casters={"u1": {"name": "Cass", "id": "u1"}},
            caster_slots_used=1,
            caster_stream_urls={"u1": "https://twitch.tv/cass"},
        )
        value = self._caster_field(event)
        self.assertIn("**Cass**", value)
        self.assertIn("[🔴 Stream](https://twitch.tv/cass)", value)

    def test_name_only_without_link(self):
        event = _event(casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1)
        value = self._caster_field(event)
        self.assertIn("**Cass**", value)
        self.assertNotIn("Stream](", value)

    def test_waitlisted_caster_shows_link(self):
        event = _event(
            casters={}, caster_waitlist=[("u2", "Wally")],
            caster_stream_urls={"u2": "https://twitch.tv/wally"},
        )
        embed = utils.format_event_details(event, "en", caster_enabled=True)
        wl = [f.value for f in embed.fields if "waitlist" in f.name.lower()]
        self.assertTrue(wl, "no caster waitlist field")
        self.assertIn("[🔴 Stream](https://twitch.tv/wally)", wl[0])

    def test_links_hidden_when_toggle_switched_off(self):
        # Turning the option off must take the links out of the public embed —
        # without deleting them, so switching it back on restores them.
        event = _event(
            caster_stream_links_enabled=False,
            casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1,
            caster_stream_urls={"u1": "https://twitch.tv/cass"},
        )
        self.assertNotIn("Stream](", self._caster_field(event))
        self.assertEqual(event["caster_stream_urls"], {"u1": "https://twitch.tv/cass"})

    def test_long_link_list_stays_under_the_field_cap(self):
        # Stream links make caster lines ~10x longer; an unbounded caster waitlist
        # would otherwise blow Discord's 1024-char field cap and the embed edit
        # would fail silently for the rest of the event.
        long_url = "https://twitch.tv/" + "x" * 170
        event = _event(
            max_caster_slots=12, caster_slots_used=12,
            casters={f"u{i}": {"name": f"Caster{i}", "id": f"u{i}"} for i in range(12)},
            caster_waitlist=[(f"w{i}", f"Waiting{i}") for i in range(12)],
            caster_stream_urls={**{f"u{i}": long_url for i in range(12)},
                                **{f"w{i}": long_url for i in range(12)}},
        )
        embed = utils.format_event_details(event, "en", caster_enabled=True)
        for field in embed.fields:
            self.assertLessEqual(len(field.value), 1024, field.name)
        self.assertIn("more", self._caster_field(event), "overflow must be signalled")

    def test_link_of_other_caster_not_leaked(self):
        event = _event(
            casters={"u1": {"name": "Cass", "id": "u1"}, "u2": {"name": "Dana", "id": "u2"}},
            caster_slots_used=2,
            caster_stream_urls={"u2": "https://twitch.tv/dana"},
        )
        lines = self._caster_field(event).split("\n")
        cass = next(line for line in lines if "Cass" in line)
        dana = next(line for line in lines if "Dana" in line)
        self.assertNotIn("Stream](", cass)
        self.assertIn("https://twitch.tv/dana", dana)


# ---------------------------------------------------------------------------
# Registration / editing / cleanup
# ---------------------------------------------------------------------------

class _StoreDrivenCase(unittest.IsolatedAsyncioTestCase):
    def _run_ctx(self, es, event, assignments):
        es.enter_context(patch.object(bot, "_get_event_by_dbid",
                                     return_value=(event, assignments, 7)))
        es.enter_context(patch.object(bot, "save_event", MagicMock()))
        es.enter_context(patch.object(bot, "send_feedback", AsyncMock()))
        es.enter_context(patch.object(bot, "send_to_log_channel", AsyncMock()))
        es.enter_context(patch.object(bot, "update_event_displays", AsyncMock()))
        es.enter_context(patch.object(bot, "get_guild_language", lambda *a, **k: "en"))


class RegisterWithLinkTest(_StoreDrivenCase):
    async def test_link_stored_on_registration(self):
        event, assignments = _event(), {}
        with ExitStack() as es:
            self._run_ctx(es, event, assignments)
            await bot.register_caster(_Interaction(), 1, 2, 7,
                                      stream_url="https://twitch.tv/cass")
        self.assertEqual(event["caster_stream_urls"], {"u1": "https://twitch.tv/cass"})
        self.assertIn("u1", event["casters"])

    async def test_registration_without_link_stores_nothing(self):
        event, assignments = _event(), {}
        with ExitStack() as es:
            self._run_ctx(es, event, assignments)
            await bot.register_caster(_Interaction(), 1, 2, 7)
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_link_survives_waitlist_promotion(self):
        # Both caster slots taken → the new caster is waitlisted with their link.
        event = _event(
            max_caster_slots=1, caster_slots_used=1,
            casters={"u0": {"name": "First", "id": "u0"}},
        )
        assignments = {"u0": ["__caster__"]}
        with ExitStack() as es:
            self._run_ctx(es, event, assignments)
            await bot.register_caster(_Interaction(), 1, 2, 7,
                                      stream_url="https://twitch.tv/cass")
            self.assertEqual([uid for uid, _ in event["caster_waitlist"]], ["u1"])
            self.assertEqual(event["caster_stream_urls"]["u1"], "https://twitch.tv/cass")

            # First caster leaves → u1 is promoted; the link must still be there.
            del event["casters"]["u0"]
            event["caster_slots_used"] -= 1
            es.enter_context(patch.object(bot.bot, "get_channel", return_value=None))
            es.enter_context(patch.object(bot.bot, "fetch_user", AsyncMock(side_effect=Exception)))
            await bot._process_caster_waitlist(event, assignments, 7, 1, 2)

        self.assertIn("u1", event["casters"])
        self.assertEqual(event["caster_stream_urls"]["u1"], "https://twitch.tv/cass")


class UpdateAndCleanupTest(_StoreDrivenCase):
    async def test_update_replaces_link(self):
        event = _event(casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1,
                       caster_stream_urls={"u1": "https://twitch.tv/old"})
        with ExitStack() as es:
            self._run_ctx(es, event, {"u1": ["__caster__"]})
            ok = await bot.update_caster_stream_url(_Interaction(), 1, 7,
                                                   "https://twitch.tv/new")
        self.assertTrue(ok)
        self.assertEqual(event["caster_stream_urls"]["u1"], "https://twitch.tv/new")

    async def test_empty_update_clears_link(self):
        event = _event(casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1,
                       caster_stream_urls={"u1": "https://twitch.tv/old"})
        with ExitStack() as es:
            self._run_ctx(es, event, {"u1": ["__caster__"]})
            await bot.update_caster_stream_url(_Interaction(), 1, 7, None)
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_update_rejected_for_non_caster(self):
        event = _event(caster_stream_urls={})
        with ExitStack() as es:
            self._run_ctx(es, event, {})
            ok = await bot.update_caster_stream_url(_Interaction(), 1, 7,
                                                   "https://twitch.tv/x")
        self.assertFalse(ok)
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_update_rejected_when_toggle_off(self):
        # A modal opened before the organizer flipped the option off must not write.
        event = _event(caster_stream_links_enabled=False,
                       casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1)
        with ExitStack() as es:
            self._run_ctx(es, event, {"u1": ["__caster__"]})
            ok = await bot.update_caster_stream_url(_Interaction(), 1, 7,
                                                   "https://twitch.tv/x")
        self.assertFalse(ok)
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_registration_ignores_link_when_toggle_off(self):
        event = _event(caster_stream_links_enabled=False)
        with ExitStack() as es:
            self._run_ctx(es, event, {})
            await bot.register_caster(_Interaction(), 1, 2, 7,
                                      stream_url="https://twitch.tv/cass")
        self.assertIn("u1", event["casters"], "registration itself still goes through")
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_unregister_drops_link(self):
        event = _event(casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1,
                       caster_stream_urls={"u1": "https://twitch.tv/cass"})
        with ExitStack() as es:
            self._run_ctx(es, event, {"u1": ["__caster__"]})
            await bot.unregister_caster(_Interaction(), 1, 2, 7)
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_unregister_from_waitlist_drops_link(self):
        event = _event(caster_waitlist=[("u1", "Cass")],
                       caster_stream_urls={"u1": "https://twitch.tv/cass"})
        with ExitStack() as es:
            self._run_ctx(es, event, {"u1": ["__caster__"]})
            await bot.unregister_caster(_Interaction(), 1, 2, 7)
        self.assertEqual(event["caster_stream_urls"], {})


# ---------------------------------------------------------------------------
# Caster button behaviour
# ---------------------------------------------------------------------------

class CasterButtonTest(unittest.IsolatedAsyncioTestCase):
    async def _press(self, event, assignments, es):
        es.enter_context(patch.object(bot, "_dbid_from_message", lambda *a, **k: 7))
        es.enter_context(patch.object(bot, "_get_event_by_dbid",
                                     return_value=(event, assignments, 7)))
        es.enter_context(patch.object(bot, "get_guild_settings",
                                     lambda *a, **k: {"language": "en",
                                                      "caster_registration_enabled": True}))
        es.enter_context(patch.object(bot, "register_caster", AsyncMock()))
        view = bot.EventActionView(lang="en", mode="rep")
        inter = _Interaction()
        await view._register_caster(inter)
        return inter

    async def test_modal_opened_when_enabled(self):
        with ExitStack() as es:
            inter = await self._press(_event(), {}, es)
        self.assertEqual(len(inter.response.modals), 1)
        modal = inter.response.modals[0]
        self.assertIsInstance(modal, bot.CasterStreamLinkModal)
        self.assertFalse(modal.editing)
        self.assertFalse(inter.response.deferred)

    async def test_no_modal_when_disabled(self):
        with ExitStack() as es:
            inter = await self._press(_event(caster_stream_links_enabled=False), {}, es)
            self.assertEqual(inter.response.modals, [])
            self.assertTrue(inter.response.deferred, "falls back to direct registration")
            bot.register_caster.assert_awaited_once()

    async def test_already_registered_gets_edit_modal(self):
        event = _event(casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1,
                       caster_stream_urls={"u1": "https://twitch.tv/cass"})
        with ExitStack() as es:
            inter = await self._press(event, {"u1": ["__caster__"]}, es)
        self.assertEqual(len(inter.response.modals), 1)
        modal = inter.response.modals[0]
        self.assertTrue(modal.editing)
        self.assertEqual(modal.stream_url.default, "https://twitch.tv/cass")

    async def test_already_registered_rejected_when_disabled(self):
        event = _event(caster_stream_links_enabled=False,
                       casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1)
        with ExitStack() as es:
            inter = await self._press(event, {"u1": ["__caster__"]}, es)
        self.assertEqual(inter.response.modals, [])
        self.assertEqual(inter.response.messages, [bot.t("caster.already_registered", "en")])

    async def test_closed_registration_blocks_link_edit(self):
        # Editing a link is a registration action — after close it must be denied.
        event = _event(is_closed=True, registration_open=False,
                       casters={"u1": {"name": "Cass", "id": "u1"}}, caster_slots_used=1)
        with ExitStack() as es:
            inter = await self._press(event, {"u1": ["__caster__"]}, es)
        self.assertEqual(inter.response.modals, [])
        self.assertEqual(inter.response.messages, [bot.t("reg.closed_message", "en")])


class ModalSubmitTest(unittest.IsolatedAsyncioTestCase):
    def _modal(self, value, editing=False):
        modal = bot.CasterStreamLinkModal(1, 2, 7, "en", editing=editing)
        modal.stream_url._value = value
        return modal

    async def test_invalid_url_reports_and_does_not_register(self):
        modal = self._modal("twitch.tv/nope")
        with patch.object(bot, "register_caster", AsyncMock()) as reg:
            inter = _Interaction()
            await modal.on_submit(inter)
            reg.assert_not_awaited()
        self.assertEqual(inter.response.messages, [bot.t("caster.stream_link_invalid", "en")])

    async def test_valid_url_registers(self):
        modal = self._modal("https://twitch.tv/cass")
        with patch.object(bot, "register_caster", AsyncMock()) as reg:
            await modal.on_submit(_Interaction())
            reg.assert_awaited_once()
            self.assertEqual(reg.await_args.kwargs["stream_url"], "https://twitch.tv/cass")

    async def test_editing_routes_to_update(self):
        modal = self._modal("", editing=True)
        with patch.object(bot, "update_caster_stream_url", AsyncMock()) as upd:
            await modal.on_submit(_Interaction())
            upd.assert_awaited_once()
            self.assertIsNone(upd.await_args.args[-1], "empty input clears the link")


# ---------------------------------------------------------------------------
# Admin plumbing
# ---------------------------------------------------------------------------

class AdminToggleTest(unittest.TestCase):
    def test_toggle_is_an_editable_property(self):
        rows = [p for p in bot._EDIT_PROPERTIES if p[1] == "caster_stream_links_enabled"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "bool")

    def test_hidden_in_player_mode(self):
        keys = [p[1] for p in bot._visible_edit_properties({"mode": "player"})]
        self.assertNotIn("caster_stream_links_enabled", keys)
        keys = [p[1] for p in bot._visible_edit_properties({"mode": "rep"})]
        self.assertIn("caster_stream_links_enabled", keys)

    def test_hidden_when_casters_are_disabled(self):
        keys = [p[1] for p in bot._visible_edit_properties({"mode": "rep", "max_caster_slots": 0})]
        self.assertNotIn("caster_stream_links_enabled", keys)

    def test_property_dropdown_stays_within_discord_limit(self):
        for mode in ("rep", "player"):
            visible = bot._visible_edit_properties({"mode": mode})
            self.assertLessEqual(len(visible), 25, f"{mode} mode exceeds the select cap")

    def test_event_defaults_include_the_keys(self):
        event = {}
        bot._ensure_event_keys(event)
        self.assertFalse(event["caster_stream_links_enabled"])
        self.assertEqual(event["caster_stream_urls"], {})

    def test_toggle_carried_into_recurrence_followups(self):
        import database
        self.assertIn("caster_stream_links_enabled", database._CARRY_OVER_KEYS)
        self.assertNotIn("caster_stream_urls", database._CARRY_OVER_KEYS,
                         "stored links are runtime state, they must not be cloned")


# ---------------------------------------------------------------------------
# Admin panel: add caster with a link
# ---------------------------------------------------------------------------

class AdminAddCasterTest(_StoreDrivenCase):
    def _view(self, target):
        view = bot._AdminAddCasterView(1, 2, 7)
        view.user_select._values = [target]
        return view

    async def test_user_select_opens_the_link_modal(self):
        event = _event()
        with ExitStack() as es:
            self._run_ctx(es, event, {})
            inter = _Interaction(user=_FakeUser("admin", "Admin"))
            await self._view(_FakeUser("u2", "Dana"))._user_selected(inter)
        self.assertEqual(len(inter.response.modals), 1)
        modal = inter.response.modals[0]
        self.assertEqual(modal.title, bot.t("admin.add_caster", "en"))
        self.assertFalse(inter.response.deferred, "a modal needs a fresh interaction")
        self.assertEqual(event["casters"], {}, "nothing added until the modal is submitted")

    async def test_submitting_the_modal_adds_the_caster_with_the_link(self):
        event = _event()
        with ExitStack() as es:
            self._run_ctx(es, event, {})
            inter = _Interaction(user=_FakeUser("admin", "Admin"))
            await self._view(_FakeUser("u2", "Dana"))._user_selected(inter)
            modal = inter.response.modals[0]
            modal.stream_url._value = "https://twitch.tv/dana"
            await modal.on_submit(_Interaction(user=_FakeUser("admin", "Admin")))
        self.assertIn("u2", event["casters"])
        self.assertEqual(event["caster_stream_urls"], {"u2": "https://twitch.tv/dana"})

    async def test_empty_field_adds_the_caster_without_a_link(self):
        event = _event()
        with ExitStack() as es:
            self._run_ctx(es, event, {})
            inter = _Interaction(user=_FakeUser("admin", "Admin"))
            await self._view(_FakeUser("u2", "Dana"))._user_selected(inter)
            modal = inter.response.modals[0]
            modal.stream_url._value = ""
            await modal.on_submit(_Interaction(user=_FakeUser("admin", "Admin")))
        self.assertIn("u2", event["casters"])
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_invalid_link_adds_nobody(self):
        event = _event()
        with ExitStack() as es:
            self._run_ctx(es, event, {})
            inter = _Interaction(user=_FakeUser("admin", "Admin"))
            await self._view(_FakeUser("u2", "Dana"))._user_selected(inter)
            modal = inter.response.modals[0]
            modal.stream_url._value = "twitch.tv/dana"
            submit = _Interaction(user=_FakeUser("admin", "Admin"))
            await modal.on_submit(submit)
        self.assertEqual(submit.response.messages, [bot.t("caster.stream_link_invalid", "en")])
        self.assertEqual(event["casters"], {})

    async def test_no_modal_when_the_toggle_is_off(self):
        event = _event(caster_stream_links_enabled=False)
        with ExitStack() as es:
            self._run_ctx(es, event, {})
            inter = _Interaction(user=_FakeUser("admin", "Admin"))
            await self._view(_FakeUser("u2", "Dana"))._user_selected(inter)
        self.assertEqual(inter.response.modals, [])
        self.assertIn("u2", event["casters"], "falls back to adding straight away")
        self.assertEqual(event["caster_stream_urls"], {})

    async def test_waitlisted_admin_add_keeps_the_link(self):
        event = _event(max_caster_slots=1, caster_slots_used=1,
                       casters={"u0": {"name": "First", "id": "u0"}})
        with ExitStack() as es:
            self._run_ctx(es, event, {"u0": ["__caster__"]})
            inter = _Interaction(user=_FakeUser("admin", "Admin"))
            await self._view(_FakeUser("u2", "Dana"))._user_selected(inter)
            modal = inter.response.modals[0]
            modal.stream_url._value = "https://twitch.tv/dana"
            await modal.on_submit(_Interaction(user=_FakeUser("admin", "Admin")))
        self.assertEqual([uid for uid, _ in event["caster_waitlist"]], ["u2"])
        self.assertEqual(event["caster_stream_urls"], {"u2": "https://twitch.tv/dana"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
