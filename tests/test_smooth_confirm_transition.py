#!/usr/bin/env python3
"""Confirm dialogs collapse into their result: pressing Confirm REPLACES the dialog
message (e.g. "Abmeldung bestätigen" → "✅ … abgemeldet.") instead of appending a new
ephemeral. send_feedback honours interaction.extras["edit_feedback"], which the shared
BaseConfirmationView._edit_in_place sets at the top of every _confirm callback.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import bot  # noqa: E402


class _Response:
    def __init__(self, done):
        self._done = done
        self.send_message_calls = []
        self.edit_message_calls = []

    def is_done(self):
        return self._done

    async def send_message(self, content=None, **kw):
        self.send_message_calls.append((content, kw))

    async def edit_message(self, content=None, **kw):
        self.edit_message_calls.append((content, kw))


class _Followup:
    def __init__(self):
        self.calls = []

    async def send(self, content=None, **kw):
        self.calls.append((content, kw))


class _Interaction:
    def __init__(self, done, extras=None):
        self.response = _Response(done)
        self.followup = _Followup()
        self.extras = extras if extras is not None else {}
        self.edit_original_calls = []

    async def edit_original_response(self, content=None, **kw):
        self.edit_original_calls.append((content, kw))


class SendFeedbackEditModeTest(unittest.IsolatedAsyncioTestCase):
    async def test_flag_after_defer_edits_dialog_in_place(self):
        # The real flow: _confirm defer()s (done=True), so the result edits the dialog message.
        inter = _Interaction(done=True, extras={"edit_feedback": True})
        await bot.send_feedback(inter, "✅ unregistered")
        self.assertEqual(len(inter.edit_original_calls), 1)
        content, kw = inter.edit_original_calls[0]
        self.assertEqual(content, "✅ unregistered")
        self.assertIsNone(kw["embed"], "red confirm embed must be cleared")
        self.assertIsNone(kw["view"], "Confirm/Cancel buttons must be removed")
        self.assertEqual(inter.followup.calls, [], "must NOT append a new message")

    async def test_flag_without_defer_uses_edit_message(self):
        inter = _Interaction(done=False, extras={"edit_feedback": True})
        await bot.send_feedback(inter, "done")
        self.assertEqual(len(inter.response.edit_message_calls), 1)
        self.assertEqual(inter.response.send_message_calls, [], "must NOT send a new message")

    async def test_no_flag_still_appends_new_message(self):
        # Non-confirm callers are untouched: still a fresh message.
        inter = _Interaction(done=True)  # no edit_feedback flag
        await bot.send_feedback(inter, "hello")
        self.assertEqual(len(inter.followup.calls), 1)
        self.assertEqual(inter.edit_original_calls, [], "no flag → no in-place edit")

    async def test_squad_name_modal_replaces_select_message(self):
        # SquadNameModal.on_submit opts into edit_feedback so the registration result
        # replaces the type/playstyle select message instead of appending a new ephemeral.
        modal = bot.SquadNameModal("1", "2", "infantry", "Normal")
        modal.squad_name._value = "Alpha"
        inter = _Interaction(done=False)
        inter.response.defer_calls = []

        async def _defer(**kw):
            inter.response.defer_calls.append(kw)
        inter.response.defer = _defer

        calls = []
        orig = bot.register_squad

        async def _fake_register(*a, **kw):
            calls.append((a, kw))
        bot.register_squad = _fake_register
        try:
            await modal.on_submit(inter)
        finally:
            bot.register_squad = orig

        self.assertTrue(inter.extras["edit_feedback"])
        self.assertEqual(len(inter.response.defer_calls), 1)
        self.assertEqual(len(calls), 1)

    async def test_edit_in_place_sets_flag_and_stops_view(self):
        view = bot.BaseConfirmationView()
        inter = _Interaction(done=False)
        view._edit_in_place(inter)
        self.assertTrue(inter.extras["edit_feedback"])
        self.assertTrue(view.is_finished(), "view must stop() so on_timeout can't re-add buttons")


if __name__ == "__main__":
    unittest.main()
