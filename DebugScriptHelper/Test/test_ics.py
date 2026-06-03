#!/usr/bin/env python3
"""Unit tests for the ICS calendar export helper."""

import os
import sys
import types
import unittest
from datetime import datetime, timezone

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

# Pin the ICS timezone so the CEST/CET offset assertions are deterministic
# regardless of the test host's TZ (config reads EVENT_TIMEZONE at import).
os.environ.setdefault("EVENT_TIMEZONE", "Europe/Berlin")

from utils import (  # noqa: E402
    _ics_dt,
    _ics_escape,
    _ics_fold,
    _ics_slug,
    build_event_ics,
)


def _base_event(**overrides) -> dict:
    event = {
        "name": "Test Event",
        "date": "15.04.2026",
        "time": "20:00",
        "description": "Some description",
        "duration_minutes": 120,
        "event_message_id": 999000111,
    }
    event.update(overrides)
    return event


def _decode(ics: bytes) -> str:
    return ics.decode("utf-8")


def _lines(ics: bytes) -> list[str]:
    text = _decode(ics)
    # Validate CRLF everywhere
    assert "\n" in text
    assert "\r\n" in text
    return text.split("\r\n")


class IcsEscapeTests(unittest.TestCase):
    def test_escapes_special_chars(self):
        self.assertEqual(_ics_escape("a, b; c"), "a\\, b\\; c")
        self.assertEqual(_ics_escape("back\\slash"), "back\\\\slash")
        self.assertEqual(_ics_escape("line1\nline2"), "line1\\nline2")
        self.assertEqual(_ics_escape("line1\r\nline2"), "line1\\nline2")

    def test_colon_not_escaped(self):
        self.assertEqual(_ics_escape("Op: Foo"), "Op: Foo")

    def test_empty(self):
        self.assertEqual(_ics_escape(""), "")
        self.assertEqual(_ics_escape(None), "")


class IcsFoldTests(unittest.TestCase):
    def test_short_line_unchanged(self):
        self.assertEqual(_ics_fold("SUMMARY:short"), "SUMMARY:short")

    def test_long_ascii_line_is_folded(self):
        line = "DESCRIPTION:" + ("a" * 100)
        folded = _ics_fold(line)
        pieces = folded.split("\r\n")
        self.assertGreater(len(pieces), 1)
        # First piece up to 75 octets, no leading space
        self.assertFalse(pieces[0].startswith(" "))
        self.assertLessEqual(len(pieces[0].encode("utf-8")), 75)
        # Continuation lines start with a single space and stay ≤ 75 octets total
        for cont in pieces[1:]:
            self.assertTrue(cont.startswith(" "))
            self.assertLessEqual(len(cont.encode("utf-8")), 75)

    def test_fold_respects_utf8_octets(self):
        # 'ä' = 2 octets; '🪖' = 4 octets. Place them around the boundary.
        prefix = "DESCRIPTION:" + ("x" * 60)
        line = prefix + "äöü" + "🪖🪖🪖" + ("y" * 60)
        folded = _ics_fold(line)
        # Round-trip must succeed without raising — proves no multibyte split.
        joined = "".join(p.lstrip(" ") if i > 0 else p for i, p in enumerate(folded.split("\r\n")))
        self.assertEqual(joined, line)
        for piece in folded.split("\r\n"):
            self.assertLessEqual(len(piece.encode("utf-8")), 75)


class IcsDtTests(unittest.TestCase):
    def test_formats_utc(self):
        dt = datetime(2026, 4, 15, 18, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(_ics_dt(dt), "20260415T180000Z")

    def test_naive_raises(self):
        with self.assertRaises(ValueError):
            _ics_dt(datetime(2026, 4, 15, 18, 0, 0))


class IcsSlugTests(unittest.TestCase):
    def test_slug_basic(self):
        self.assertEqual(_ics_slug("Hello World"), "hello_world")

    def test_slug_collapses_specials(self):
        self.assertEqual(_ics_slug("Op: Foo, Bar!"), "op_foo_bar")

    def test_slug_empty(self):
        self.assertEqual(_ics_slug(""), "")
        self.assertEqual(_ics_slug("!!!"), "")


class BuildEventIcsTests(unittest.TestCase):
    def test_minimal_event_has_required_fields(self):
        ics = build_event_ics(_base_event(), 1, 2, "https://example/jump")
        lines = _lines(ics)
        self.assertEqual(lines[0], "BEGIN:VCALENDAR")
        self.assertIn("VERSION:2.0", lines)
        self.assertIn("PRODID:-//squad-event-discord-bot//EN", lines)
        self.assertIn("BEGIN:VEVENT", lines)
        self.assertIn("END:VEVENT", lines)
        self.assertIn("END:VCALENDAR", lines[-1] if lines[-1] else lines[-2])
        required_prefixes = ("UID:", "DTSTAMP:", "DTSTART:", "DTEND:", "SUMMARY:")
        for prefix in required_prefixes:
            self.assertTrue(any(l.startswith(prefix) for l in lines), prefix)

    def test_dtstart_summer_time(self):
        # April → CEST (UTC+2). 20:00 local → 18:00 UTC.
        ics = build_event_ics(_base_event(date="15.04.2026", time="20:00"), 1, 2, None)
        self.assertIn("DTSTART:20260415T180000Z", _lines(ics))

    def test_dtstart_winter_time(self):
        # January → CET (UTC+1). 20:00 local → 19:00 UTC.
        ics = build_event_ics(_base_event(date="15.01.2026", time="20:00"), 1, 2, None)
        self.assertIn("DTSTART:20260115T190000Z", _lines(ics))

    def test_dtend_uses_duration(self):
        ics = build_event_ics(
            _base_event(date="15.04.2026", time="20:00", duration_minutes=30),
            1, 2, None,
        )
        lines = _lines(ics)
        self.assertIn("DTSTART:20260415T180000Z", lines)
        self.assertIn("DTEND:20260415T183000Z", lines)

    def test_duration_defaults_to_120(self):
        ev = _base_event(date="15.04.2026", time="20:00")
        ev.pop("duration_minutes")
        ics = build_event_ics(ev, 1, 2, None)
        lines = _lines(ics)
        self.assertIn("DTSTART:20260415T180000Z", lines)
        self.assertIn("DTEND:20260415T200000Z", lines)

    def test_uid_stable_per_message(self):
        a = build_event_ics(_base_event(event_message_id=42), 100, 200, None)
        b = build_event_ics(_base_event(event_message_id=42), 100, 200, None)
        uid_a = next(l for l in _lines(a) if l.startswith("UID:"))
        uid_b = next(l for l in _lines(b) if l.startswith("UID:"))
        self.assertEqual(uid_a, uid_b)
        self.assertEqual(uid_a, "UID:100-200-42@squad-event-bot")

    def test_uid_differs_per_message(self):
        a = build_event_ics(_base_event(event_message_id=42), 100, 200, None)
        b = build_event_ics(_base_event(event_message_id=43), 100, 200, None)
        uid_a = next(l for l in _lines(a) if l.startswith("UID:"))
        uid_b = next(l for l in _lines(b) if l.startswith("UID:"))
        self.assertNotEqual(uid_a, uid_b)

    def test_uid_fallback_when_message_id_missing(self):
        ev = _base_event()
        ev["event_message_id"] = None
        ics = build_event_ics(ev, 100, 200, None)
        uid_line = next(l for l in _lines(ics) if l.startswith("UID:"))
        self.assertEqual(uid_line, "UID:100-200-no-msg@squad-event-bot")

    def test_summary_escapes_special_chars(self):
        ev = _base_event(name="Op: Foo, Bar; Baz\nNext")
        ics = build_event_ics(ev, 1, 2, None)
        self.assertIn("SUMMARY:Op: Foo\\, Bar\\; Baz\\nNext", _lines(ics))

    def test_description_contains_text_and_jump_url(self):
        ev = _base_event(description="Briefing at 19:50")
        ics = build_event_ics(ev, 1, 2, "https://discord.com/channels/1/2/3")
        desc = next(l for l in _lines(ics) if l.startswith("DESCRIPTION:"))
        self.assertIn("Briefing at 19:50", desc)
        self.assertIn("https://discord.com/channels/1/2/3", desc)

    def test_description_without_jump_url(self):
        ev = _base_event(description="Just text")
        ics = build_event_ics(ev, 1, 2, None)
        desc = next(l for l in _lines(ics) if l.startswith("DESCRIPTION:"))
        self.assertEqual(desc, "DESCRIPTION:Just text")

    def test_description_only_jump_url_when_no_description(self):
        ev = _base_event(description="")
        ics = build_event_ics(ev, 1, 2, "https://example/jump")
        desc = next(l for l in _lines(ics) if l.startswith("DESCRIPTION:"))
        self.assertEqual(desc, "DESCRIPTION:https://example/jump")

    def test_description_omitted_when_empty_and_no_url(self):
        ev = _base_event(description="")
        ics = build_event_ics(ev, 1, 2, None)
        lines = _lines(ics)
        self.assertFalse(any(l.startswith("DESCRIPTION:") for l in lines))

    def test_long_description_is_folded(self):
        ev = _base_event(description="A" * 200)
        ics = build_event_ics(ev, 1, 2, None)
        text = _decode(ics)
        # Folded lines should be split with CRLF + space.
        self.assertIn("\r\n A", text)

    def test_unicode_summary_round_trips(self):
        ev = _base_event(name="Squad-Übung 🪖")
        ics = build_event_ics(ev, 1, 2, None)
        # Should be valid UTF-8 and contain the bytes for these characters.
        self.assertIn("Squad-Übung 🪖", _decode(ics))

    def test_invalid_date_raises_value_error(self):
        ev = _base_event(date="bogus")
        with self.assertRaises(ValueError):
            build_event_ics(ev, 1, 2, None)

    def test_output_ends_with_crlf(self):
        ics = build_event_ics(_base_event(), 1, 2, None)
        self.assertTrue(ics.endswith(b"\r\n"))
        self.assertTrue(ics.endswith(b"END:VCALENDAR\r\n"))


if __name__ == "__main__":
    unittest.main()
