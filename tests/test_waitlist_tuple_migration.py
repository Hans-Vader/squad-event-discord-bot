#!/usr/bin/env python3
"""Waitlist tuples must lose the retired playstyle slot without corrupting data.

Removing the playstyle feature shrank both persisted waitlist shapes by one:

    rep:    (name, type, playstyle, size, squad_id, rep_name)
         →  (name, type, size, squad_id, rep_name)
    player: (name, type, None, 1, uid, name, roles)
         →  (name, type, 1, uid, name, roles)

Without a migration, a live event's stored entries would be read with everything
after index 1 shifted — a rep squad's `size` would come back as "Normal" and a
player's uid would come back as `1`. _ensure_event_keys normalizes them on load;
the detector is "index 2 is not an int", which is true for every old entry
(playstyle string / None) and false for every new one (size / seat count).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import discord  # noqa: E402  (imported for its side effect on bot's imports)
import bot  # noqa: E402
import utils  # noqa: E402


class RepWaitlistMigrationTest(unittest.TestCase):
    def test_old_rep_entry_loses_playstyle_slot(self):
        event = {"infantry_waitlist": [("Alpha", "infantry", "Focused", 6, "sq-1", "Rita")]}
        bot._ensure_event_keys(event)
        self.assertEqual(event["infantry_waitlist"],
                         [("Alpha", "infantry", 6, "sq-1", "Rita")])

    def test_migrated_entry_resolves_to_correct_meta(self):
        event = {"heli_waitlist": [("Charlie", "heli", "Normal", 1, "sq-3", "rep")]}
        bot._ensure_event_keys(event)
        name, stype, size = bot._resolve_squad_meta(event, "sq-3")
        self.assertEqual((name, stype, size), ("Charlie", "heli", 1))

    def test_json_roundtripped_lists_are_migrated_too(self):
        # SQLite stores events as JSON, so tuples come back as lists.
        event = {"vehicle_waitlist": [["Bravo", "vehicle", "Casual", 2, "sq-2", "Rob"]]}
        bot._ensure_event_keys(event)
        self.assertEqual(event["vehicle_waitlist"], [("Bravo", "vehicle", 2, "sq-2", "Rob")])

    def test_short_legacy_entry_without_rep_name(self):
        # Older entries had no rep_name — detection must not rely on length.
        event = {"infantry_waitlist": [("Alpha", "infantry", "Normal", 6, "sq-1")]}
        bot._ensure_event_keys(event)
        self.assertEqual(event["infantry_waitlist"], [("Alpha", "infantry", 6, "sq-1")])


class PlayerWaitlistMigrationTest(unittest.TestCase):
    def test_old_player_entry_loses_none_slot(self):
        event = {"mode": "player",
                 "infantry_waitlist": [("Dora", "infantry", None, 1, "u5", "Dora", ["Medic"])]}
        bot._ensure_event_keys(event)
        self.assertEqual(event["infantry_waitlist"],
                         [("Dora", "infantry", 1, "u5", "Dora", ["Medic"])])

    def test_migrated_player_entry_is_found_by_uid(self):
        event = {"mode": "player",
                 "infantry_waitlist": [("Dora", "infantry", None, 1, "u5", "Dora", [])],
                 "vehicle_waitlist": [], "heli_waitlist": []}
        bot._ensure_event_keys(event)
        self.assertEqual(utils._player_waitlist_type(event, "u5"), "infantry")
        self.assertEqual(utils._player_remove_from_waitlist(event, "u5"), "infantry")
        self.assertEqual(event["infantry_waitlist"], [])


class IdempotencyTest(unittest.TestCase):
    def test_current_shapes_are_left_alone(self):
        event = {
            "infantry_waitlist": [("Alpha", "infantry", 6, "sq-1", "Rita")],
            "heli_waitlist": [("Dora", "heli", 1, "u5", "Dora", [])],
        }
        bot._ensure_event_keys(event)
        self.assertEqual(event["infantry_waitlist"], [("Alpha", "infantry", 6, "sq-1", "Rita")])
        self.assertEqual(event["heli_waitlist"], [("Dora", "heli", 1, "u5", "Dora", [])])

    def test_running_twice_changes_nothing(self):
        event = {"infantry_waitlist": [("Alpha", "infantry", "Normal", 6, "sq-1", "Rita")]}
        bot._ensure_event_keys(event)
        once = list(event["infantry_waitlist"])
        bot._ensure_event_keys(event)
        self.assertEqual(event["infantry_waitlist"], once)

    def test_legacy_shared_waitlist_is_migrated_and_normalized(self):
        # The old single "waitlist" list is first split per type, then normalized.
        event = {"waitlist": [("Alpha", "infantry", "Normal", 6, "sq-1", "Rita")]}
        bot._ensure_event_keys(event)
        self.assertEqual(event["waitlist"], [])
        self.assertEqual(event["infantry_waitlist"], [("Alpha", "infantry", 6, "sq-1", "Rita")])


class RegistrationWritesNewShapeTest(unittest.TestCase):
    def test_player_register_writes_six_element_entry(self):
        event = {
            "mode": "player", "max_player_slots": 1, "player_slots_used": 0,
            "infantry_squad_size": 1, "vehicle_squad_size": 2, "heli_squad_size": 1,
            "max_vehicle_squads": 0, "max_heli_squads": 0,
            "server_max_players": 2, "max_caster_slots": 0,
            "squads": {}, "infantry_waitlist": [], "vehicle_waitlist": [], "heli_waitlist": [],
            "tentative": [], "declined": [],
        }
        ua = {}
        utils._player_register(event, ua, "u1", "One", "infantry")
        utils._player_register(event, ua, "u2", "Two", "infantry")
        self.assertEqual(len(event["infantry_waitlist"]), 1)
        entry = event["infantry_waitlist"][0]
        self.assertEqual(len(entry), 6)
        self.assertEqual(entry[2], 1, "seat count sits at index 2 now")
        self.assertEqual(entry[3], "u2", "uid sits at index 3 now")


if __name__ == "__main__":
    unittest.main(verbosity=2)
