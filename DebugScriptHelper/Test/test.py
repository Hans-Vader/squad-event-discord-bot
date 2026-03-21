#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Testsuite für Bot-Funktionalität
Testet insbesondere Wartelisten-Funktionalität und Edge Cases
"""

import os
import sys
import pickle
import logging
import random
import string
from datetime import datetime

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("Test/test.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("event_bot_test")

# Pfade für Testdaten
TEST_DATA_FILE = "Test/test_event_data.pkl"

# Globale Testdaten
event_data = {}
user_team_assignments = {}

def reset_test_data():
    """Setzt die Testdaten auf Standardwerte zurück"""
    global event_data, user_team_assignments
    
    # Standardwerte für Event-Daten
    event_data = {
        "event": {
            "name": "Test Event",
            "date": "2025-04-01",
            "time": "20:00",
            "description": "Dies ist ein Test-Event für automatisierte Tests",
            "teams": {},
            "waitlist": [],
            "max_slots": 60,
            "slots_used": 0,
            "max_team_size": 12,
            "is_closed": False
        }
    }
    
    # Leere Team-Zuweisungen
    user_team_assignments = {}
    
    # Daten speichern
    save_data()
    logger.info("Test-Daten zurückgesetzt")

def save_data():
    """Speichert die Testdaten"""
    with open(TEST_DATA_FILE, 'wb') as f:
        pickle.dump((event_data, None, user_team_assignments), f)

def load_data():
    """Lädt die Testdaten"""
    global event_data, user_team_assignments
    
    if os.path.exists(TEST_DATA_FILE):
        with open(TEST_DATA_FILE, 'rb') as f:
            event_data, _, user_team_assignments = pickle.load(f)
    else:
        reset_test_data()

def generate_random_id():
    """Generiert eine zufällige Discord-User-ID"""
    return ''.join(random.choices(string.digits, k=18))

def generate_team_id(team_name):
    """Generiert eine einzigartige Team-ID"""
    import hashlib
    team_hash = hashlib.md5(team_name.lower().encode()).hexdigest()
    return team_hash[:10]

def register_team(team_name, team_size, user_id=None):
    """
    Registriert ein Team für das Event
    
    Parameters:
    - team_name: Name des Teams
    - team_size: Größe des Teams
    - user_id: Optional - Discord-ID des Team-Repräsentanten
    
    Returns:
    - (success, message, waitlist_status)
      - success: Bool - Ob die Registrierung erfolgreich war
      - message: Nachricht mit Details zur Registrierung
      - waitlist_status: None oder (position, expected_slots)
    """
    event = event_data["event"]
    team_name = team_name.strip()
    team_name_lower = team_name.lower()
    
    # Check if team name already exists (case insensitive)
    if any(name.lower() == team_name_lower for name in event["teams"]):
        return False, f"Ein Team mit dem Namen '{team_name}' ist bereits registriert.", None
    
    # Check if team is on waitlist
    for i, entry in enumerate(event["waitlist"]):
        if len(entry) >= 3:  # Neues Format mit IDs
            wl_team, wl_size, _ = entry
        else:
            wl_team, wl_size = entry
            
        if wl_team.lower() == team_name_lower:
            return False, f"Ein Team mit dem Namen '{team_name}' steht bereits auf der Warteliste.", None
            
    # Check if event is closed
    if event.get("is_closed", False):
        return False, "Die Anmeldungen für dieses Event sind derzeit geschlossen.", None
        
    # Check if enough slots are available
    available_slots = event["max_slots"] - event["slots_used"]
    
    # Generiere die Team-ID
    team_id = generate_team_id(team_name)
    
    if available_slots >= team_size:
        # Directly register the team to the event
        event["teams"][team_name] = {"size": team_size, "id": team_id}
        event["slots_used"] += team_size
        
        # Assign team to user if user_id is provided
        if user_id:
            user_team_assignments[str(user_id)] = team_name
            
        save_data()
        return True, f"Team '{team_name}' wurde erfolgreich mit {team_size} Teilnehmern registriert.", None
    else:
        # Add team to waitlist
        event["waitlist"].append((team_name, team_size, team_id))
        
        # Calculate expected wait time
        waitlist_position = len(event["waitlist"])
        
        # Assign team to user if user_id is provided
        if user_id:
            user_team_assignments[str(user_id)] = team_name
            
        save_data()
        return True, f"Team '{team_name}' wurde auf die Warteliste gesetzt (Position: {waitlist_position}).", (waitlist_position, team_size)

def unregister_team(team_name, user_id=None):
    """
    Meldet ein Team vom Event ab
    
    Parameters:
    - team_name: Name des Teams
    - user_id: Optional - Discord-ID des Team-Repräsentanten
    
    Returns:
    - (success, message, freed_slots)
      - success: Bool - Ob die Abmeldung erfolgreich war
      - message: Nachricht mit Details zur Abmeldung
      - freed_slots: Anzahl der freigewordenen Slots
    """
    event = event_data["event"]
    team_name_lower = team_name.lower()
    freed_slots = 0
    
    # Suche Team in Event-Anmeldungen
    team_removed = False
    for name in list(event["teams"].keys()):
        if name.lower() == team_name_lower:
            team_data = event["teams"][name]
            
            if isinstance(team_data, dict):
                team_size = team_data.get("size", 0)
            else:
                team_size = team_data
                
            # Slot-Zähler aktualisieren
            event["slots_used"] -= team_size
            freed_slots = team_size
            
            # Team entfernen
            del event["teams"][name]
            team_removed = True
            
            # Log
            logger.info(f"Team '{name}' ({team_size} Plätze) vom Event entfernt")
            break
    
    # Suche Team in der Warteliste
    waitlist_indices = []
    for i, entry in enumerate(event["waitlist"]):
        if len(entry) >= 3:  # Format: (team_name, size, team_id)
            wl_team, wl_size, _ = entry
        else:
            wl_team, wl_size = entry
            
        if wl_team.lower() == team_name_lower:
            waitlist_indices.append(i)
            logger.info(f"Team '{wl_team}' ({wl_size} Plätze) von der Warteliste entfernt")
    
    # Entferne Teams von der Warteliste (in umgekehrter Reihenfolge, um Index-Verschiebungen zu vermeiden)
    for i in sorted(waitlist_indices, reverse=True):
        entry = event["waitlist"].pop(i)
        team_removed = True
    
    # Entferne Benutzerzuweisungen für dieses Team
    for uid, team in list(user_team_assignments.items()):
        if team.lower() == team_name_lower:
            del user_team_assignments[uid]
            logger.info(f"Team-Zuweisung für Benutzer {uid} entfernt")
    
    if not team_removed:
        return False, f"Team '{team_name}' ist weder angemeldet noch auf der Warteliste.", 0
    
    # Speichere Änderungen
    save_data()
    
    return True, f"Team '{team_name}' wurde erfolgreich abgemeldet.", freed_slots

def update_team_size(team_name, new_size, user_id=None):
    """
    Aktualisiert die Größe eines Teams
    
    Parameters:
    - team_name: Name des Teams
    - new_size: Neue Teamgröße
    - user_id: Optional - Discord-ID des Team-Repräsentanten
    
    Returns:
    - (success, message, free_slots)
      - success: Bool - Ob die Aktualisierung erfolgreich war
      - message: Nachricht mit Details zur Aktualisierung
      - free_slots: Anzahl der freigewordenen Slots (negativ = benötigte Slots)
    """
    event = event_data["event"]
    team_name_lower = team_name.lower()
    
    # Prüfe, ob das Event geschlossen ist
    if event.get("is_closed", False) and new_size > 0:
        return False, "Die Anmeldungen für dieses Event sind derzeit geschlossen.", 0
    
    # Prüfe Abmeldung (size == 0)
    if new_size == 0:
        return unregister_team(team_name, user_id)
    
    # Teamgrößenbeschränkung prüfen
    if new_size > event["max_team_size"]:
        return False, f"Die maximale Teamgröße ist {event['max_team_size']}.", 0
    
    # Team im Event suchen
    team_in_event = False
    old_size = 0
    real_team_name = team_name
    
    for name, data in list(event["teams"].items()):
        if name.lower() == team_name_lower:
            team_in_event = True
            real_team_name = name
            
            if isinstance(data, dict):
                old_size = data.get("size", 0)
            else:
                old_size = data
            
            break
    
    # Team in Warteliste suchen
    team_in_waitlist = False
    waitlist_entries = []
    
    for i, entry in enumerate(event["waitlist"]):
        if len(entry) >= 3:  # Format: (team_name, size, team_id)
            wl_team, wl_size, wl_team_id = entry
        else:
            wl_team, wl_size = entry
            wl_team_id = None
            
        if wl_team.lower() == team_name_lower:
            team_in_waitlist = True
            waitlist_entries.append((i, wl_team, wl_size, wl_team_id))
    
    # Team nicht gefunden
    if not team_in_event and not team_in_waitlist:
        return False, f"Team '{team_name}' nicht gefunden.", 0
    
    # Keine Änderung
    if team_in_event and old_size == new_size:
        return True, f"Team '{real_team_name}' ist bereits mit {new_size} Personen angemeldet.", 0
    
    # Berechne Größenunterschied (positive = Vergrößerung, negative = Verkleinerung)
    if team_in_event:
        size_diff = new_size - old_size
    else:
        # Team nur auf Warteliste
        size_diff = new_size - sum(entry[2] for entry in waitlist_entries)
    
    # Verfügbare Slots im Event
    available_slots = event["max_slots"] - event["slots_used"]
    
    # Team vergrößern
    if size_diff > 0:
        # Team im Event vergrößern
        if team_in_event:
            # Passt direkt ins Event
            if available_slots >= size_diff:
                if isinstance(event["teams"][real_team_name], dict):
                    event["teams"][real_team_name]["size"] = new_size
                else:
                    event["teams"][real_team_name] = new_size
                
                event["slots_used"] += size_diff
                logger.info(f"Team '{real_team_name}' von {old_size} auf {new_size} vergrößert")
                save_data()
                return True, f"Team '{real_team_name}' wurde von {old_size} auf {new_size} vergrößert.", -size_diff
            else:
                # Teilweise ins Event, Rest auf Warteliste
                if available_slots > 0:
                    new_event_size = old_size + available_slots
                    if isinstance(event["teams"][real_team_name], dict):
                        event["teams"][real_team_name]["size"] = new_event_size
                    else:
                        event["teams"][real_team_name] = new_event_size
                    
                    event["slots_used"] += available_slots
                    
                    # Rest auf Warteliste
                    waitlist_size = size_diff - available_slots
                    
                    # Team-ID ermitteln/generieren
                    if isinstance(event["teams"][real_team_name], dict):
                        team_id = event["teams"][real_team_name].get("id")
                        if not team_id:
                            team_id = generate_team_id(real_team_name)
                            event["teams"][real_team_name]["id"] = team_id
                    else:
                        team_id = generate_team_id(real_team_name)
                    
                    # Auf Warteliste setzen
                    event["waitlist"].append((real_team_name, waitlist_size, team_id))
                    
                    logger.info(f"Team '{real_team_name}' teilweise vergrößert: {old_size} -> {new_event_size} im Event, {waitlist_size} auf Warteliste")
                    save_data()
                    return True, f"Team '{real_team_name}' wurde teilweise vergrößert: {old_size} -> {new_event_size} im Event, {waitlist_size} auf Warteliste.", -available_slots
                else:
                    # Komplett auf die Warteliste
                    team_id = None
                    if isinstance(event["teams"][real_team_name], dict):
                        team_id = event["teams"][real_team_name].get("id")
                    
                    if not team_id:
                        team_id = generate_team_id(real_team_name)
                    
                    event["waitlist"].append((real_team_name, size_diff, team_id))
                    
                    logger.info(f"Team '{real_team_name}' bleibt bei {old_size}, zusätzliche {size_diff} auf Warteliste")
                    save_data()
                    return True, f"Team '{real_team_name}' bleibt bei {old_size} im Event, zusätzliche {size_diff} auf Warteliste.", 0
        else:
            # Team nur auf Warteliste vergrößern
            # Entferne alte Einträge
            for i in sorted([entry[0] for entry in waitlist_entries], reverse=True):
                event["waitlist"].pop(i)
            
            # Füge neuen Eintrag hinzu
            team_id = next((entry[3] for entry in waitlist_entries if entry[3]), None) or generate_team_id(team_name)
            event["waitlist"].append((team_name, new_size, team_id))
            
            logger.info(f"Team '{team_name}' auf Warteliste von {sum(entry[2] for entry in waitlist_entries)} auf {new_size} vergrößert")
            save_data()
            return True, f"Team '{team_name}' wurde auf der Warteliste von {sum(entry[2] for entry in waitlist_entries)} auf {new_size} vergrößert.", 0
    
    # Team verkleinern
    else:  # size_diff < 0
        size_diff_abs = abs(size_diff)
        
        # Team im Event verkleinern
        if team_in_event:
            if isinstance(event["teams"][real_team_name], dict):
                event["teams"][real_team_name]["size"] = new_size
            else:
                event["teams"][real_team_name] = new_size
            
            event["slots_used"] -= size_diff_abs
            
            logger.info(f"Team '{real_team_name}' von {old_size} auf {new_size} verkleinert")
            save_data()
            return True, f"Team '{real_team_name}' wurde von {old_size} auf {new_size} verkleinert.", size_diff_abs
        else:
            # Team nur auf Warteliste verkleinern
            # Entferne alte Einträge
            for i in sorted([entry[0] for entry in waitlist_entries], reverse=True):
                event["waitlist"].pop(i)
            
            # Füge neuen Eintrag hinzu
            team_id = next((entry[3] for entry in waitlist_entries if entry[3]), None) or generate_team_id(team_name)
            event["waitlist"].append((team_name, new_size, team_id))
            
            logger.info(f"Team '{team_name}' auf Warteliste von {sum(entry[2] for entry in waitlist_entries)} auf {new_size} verkleinert")
            save_data()
            return True, f"Team '{team_name}' wurde auf der Warteliste von {sum(entry[2] for entry in waitlist_entries)} auf {new_size} verkleinert.", 0

def process_waitlist(free_slots=0):
    """
    Verarbeitet die Warteliste, nachdem Slots frei geworden sind
    
    Parameters:
    - free_slots: Anzahl der frei gewordenen Slots (optional)
    
    Returns:
    - Liste mit verarbeiteten Teams: [(team_name, moved_size), ...]
    """
    event = event_data["event"]
    if not event["waitlist"]:
        return []
    
    # Berechne tatsächlich verfügbare Slots
    available_slots = event["max_slots"] - event["slots_used"]
    if available_slots <= 0:
        return []
    
    processed_teams = []
    waitlist_to_remove = []
    
    # Verarbeite die Warteliste in Reihenfolge
    for i, entry in enumerate(event["waitlist"]):
        if available_slots <= 0:
            break
            
        if len(entry) >= 3:  # Format: (team_name, size, team_id)
            team_name, team_size, team_id = entry
        else:
            team_name, team_size = entry
            team_id = generate_team_id(team_name)
        
        # Bestimme, wie viele Slots vom Team aufgerückt werden können
        slots_to_move = min(team_size, available_slots)
        
        # Prüfe, ob das Team bereits im Event ist
        team_in_event = False
        for name in event["teams"]:
            if name.lower() == team_name.lower():
                team_in_event = True
                # Erhöhe die Teamgröße im Event
                if isinstance(event["teams"][name], dict):
                    event["teams"][name]["size"] += slots_to_move
                else:
                    event["teams"][name] += slots_to_move
                break
        
        # Füge Team zum Event hinzu, wenn es noch nicht existiert
        if not team_in_event:
            event["teams"][team_name] = {"size": slots_to_move, "id": team_id}
        
        # Aktualisiere die Slot-Zähler
        event["slots_used"] += slots_to_move
        available_slots -= slots_to_move
        
        # Verarbeite den Wartelisten-Eintrag
        remaining_size = team_size - slots_to_move
        
        if remaining_size > 0:
            # Teilweise aufgerückt, Rest bleibt auf Warteliste
            event["waitlist"][i] = (team_name, remaining_size, team_id)
        else:
            # Komplett aufgerückt, entferne von Warteliste
            waitlist_to_remove.append(i)
        
        processed_teams.append((team_name, slots_to_move))
        logger.info(f"Team '{team_name}': {slots_to_move} Mitglieder von der Warteliste aufgerückt")
    
    # Entferne Einträge von der Warteliste (in umgekehrter Reihenfolge)
    for i in sorted(waitlist_to_remove, reverse=True):
        event["waitlist"].pop(i)
    
    # Daten speichern
    if processed_teams:
        save_data()
    
    return processed_teams

def expand_event_capacity(new_max_slots):
    """
    Erhöht die maximale Anzahl der Slots für das Event
    
    Parameters:
    - new_max_slots: Neue maximale Slotanzahl
    
    Returns:
    - (success, message, processed_teams)
      - success: Bool - Ob die Erweiterung erfolgreich war
      - message: Nachricht mit Details zur Erweiterung
      - processed_teams: Liste mit verarbeiteten Teams: [(team_name, moved_size), ...]
    """
    event = event_data["event"]
    
    # Prüfe, ob die neue Slotanzahl größer ist
    if new_max_slots <= event["max_slots"]:
        return False, f"Die neue maximale Slotanzahl muss größer als die aktuelle ({event['max_slots']}) sein.", []
    
    # Speichere alte Werte für Logging
    old_max_slots = event["max_slots"]
    
    # Aktualisiere die maximale Slotanzahl
    event["max_slots"] = new_max_slots
    
    # Berechne zusätzliche Slots
    additional_slots = new_max_slots - old_max_slots
    
    # Prozessiere die Warteliste
    processed_teams = process_waitlist(additional_slots)
    
    # Daten speichern
    save_data()
    
    if not processed_teams:
        return True, f"Event-Kapazität von {old_max_slots} auf {new_max_slots} erhöht. Keine Teams auf der Warteliste.", []
    else:
        teams_str = ", ".join([f"{team_name} (+{size})" for team_name, size in processed_teams])
        return True, f"Event-Kapazität von {old_max_slots} auf {new_max_slots} erhöht. Folgende Teams sind aufgerückt: {teams_str}", processed_teams

def close_event():
    """
    Schließt die Anmeldungen für das Event
    
    Returns:
    - (success, message)
      - success: Bool - Ob das Schließen erfolgreich war
      - message: Nachricht mit Details zum Schließen
    """
    event = event_data["event"]
    
    # Prüfe, ob das Event bereits geschlossen ist
    if event.get("is_closed", False):
        return False, "Das Event ist bereits geschlossen."
    
    # Schließe das Event
    event["is_closed"] = True
    
    # Daten speichern
    save_data()
    
    return True, f"Die Anmeldungen für das Event '{event['name']}' wurden geschlossen."

def open_event():
    """
    Öffnet die Anmeldungen für das Event wieder
    
    Returns:
    - (success, message, processed_teams)
      - success: Bool - Ob das Öffnen erfolgreich war
      - message: Nachricht mit Details zum Öffnen
      - processed_teams: Liste mit verarbeiteten Teams (falls Warteliste prozessiert wurde)
    """
    event = event_data["event"]
    
    # Prüfe, ob das Event bereits geöffnet ist
    if not event.get("is_closed", False):
        return False, "Das Event ist bereits geöffnet.", []
    
    # Öffne das Event
    event["is_closed"] = False
    
    # Prozessiere die Warteliste (falls Slots verfügbar sind)
    processed_teams = process_waitlist()
    
    # Daten speichern
    save_data()
    
    if not processed_teams:
        return True, f"Die Anmeldungen für das Event '{event['name']}' wurden wieder geöffnet.", []
    else:
        teams_str = ", ".join([f"{team_name} (+{size})" for team_name, size in processed_teams])
        return True, f"Die Anmeldungen für das Event '{event['name']}' wurden wieder geöffnet. Folgende Teams sind aufgerückt: {teams_str}", processed_teams

def print_event_summary():
    """Gibt eine Zusammenfassung des Events aus"""
    event = event_data["event"]
    
    logger.info(f"\n{'=' * 50}")
    logger.info(f"EVENT-ZUSAMMENFASSUNG: {event['name']}")
    logger.info(f"Datum: {event['date']} {event['time']}")
    logger.info(f"Status: {'Geschlossen' if event.get('is_closed', False) else 'Offen'}")
    logger.info(f"Kapazität: {event['slots_used']}/{event['max_slots']} Slots verwendet")
    logger.info(f"Max. Teamgröße: {event['max_team_size']}")
    logger.info(f"\nANGEMELDETE TEAMS ({len(event['teams'])}): ")
    
    for i, (name, data) in enumerate(event['teams'].items(), 1):
        if isinstance(data, dict):
            team_size = data.get("size", 0)
            team_id = data.get("id", "N/A")
        else:
            team_size = data
            team_id = "N/A (altes Format)"
            
        logger.info(f"{i}. {name} (Größe: {team_size}, ID: {team_id})")
    
    logger.info(f"\nWARTELISTE ({len(event['waitlist'])}): ")
    for i, entry in enumerate(event['waitlist'], 1):
        if len(entry) >= 3:  # Format: (team_name, size, team_id)
            team_name, team_size, team_id = entry
        else:
            team_name, team_size = entry
            team_id = "N/A (altes Format)"
            
        logger.info(f"{i}. {team_name} (Größe: {team_size}, ID: {team_id})")
    
    logger.info(f"\nBENUTZER-TEAM-ZUWEISUNGEN ({len(user_team_assignments)}): ")
    for user_id, team_name in user_team_assignments.items():
        logger.info(f"Benutzer {user_id} -> Team '{team_name}'")
    
    logger.info(f"{'=' * 50}\n")

def run_test_suite():
    """Führt die vollständige Testsuite aus"""
    logger.info("Starte Testprogramm für Event-Bot")
    logger.info(f"Zeitstempel: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Daten laden/zurücksetzen
    reset_test_data()
    
    # Basisdaten ausgeben
    print_event_summary()
    
    # Test 1: Teams anmelden bis Event voll ist
    logger.info("\n=== Test 1: Teams anmelden bis Event voll ist ===")
    max_slots = event_data["event"]["max_slots"]
    logger.info(f"Eventkapazität: {max_slots} Slots")
    
    # 5 Teams mit verschiedenen Größen anmelden
    user_id1 = generate_random_id()
    success, message, _ = register_team("Alpha Team", 10, user_id1)
    logger.info(f"Team 1: {message}")
    
    user_id2 = generate_random_id()
    success, message, _ = register_team("Beta Squad", 15, user_id2)
    logger.info(f"Team 2: {message}")
    
    user_id3 = generate_random_id()
    success, message, _ = register_team("Gamma Force", 12, user_id3)
    logger.info(f"Team 3: {message}")
    
    user_id4 = generate_random_id()
    success, message, _ = register_team("Delta Crew", 8, user_id4)
    logger.info(f"Team 4: {message}")
    
    user_id5 = generate_random_id()
    success, message, _ = register_team("Epsilon Group", 11, user_id5)
    logger.info(f"Team 5: {message}")
    
    print_event_summary()
    
    # Test 2: Weitere Teams sollten auf die Warteliste kommen
    logger.info("\n=== Test 2: Teams auf Warteliste setzen ===")
    
    user_id6 = generate_random_id()
    success, message, waitlist = register_team("Zeta Squad", 9, user_id6)
    logger.info(f"Team 6 (sollte auf Warteliste): {message}")
    
    user_id7 = generate_random_id()
    success, message, waitlist = register_team("Theta Team", 7, user_id7)
    logger.info(f"Team 7 (sollte auf Warteliste): {message}")
    
    print_event_summary()
    
    # Test 3: Edge Case - Doppelte Registrierung
    logger.info("\n=== Test 3: Edge Case - Doppelte Registrierung ===")
    
    # Versuche, ein Team mit dem gleichen Namen (case-insensitive) zu registrieren
    success, message, _ = register_team("alpha team", 5)
    logger.info(f"Doppelte Registrierung: {message}")
    
    # Test 4: Edge Case - Teamgröße ändern
    logger.info("\n=== Test 4: Edge Case - Teamgröße ändern ===")
    
    # Team im Event verkleinern
    success, message, _ = update_team_size("Alpha Team", 8, user_id1)
    logger.info(f"Team verkleinern: {message}")
    
    # Team im Event vergrößern (sollte klappen)
    success, message, _ = update_team_size("Alpha Team", 9, user_id1)
    logger.info(f"Team leicht vergrößern: {message}")
    
    # Team im Event stark vergrößern (sollte teilweise auf Warteliste)
    success, message, _ = update_team_size("Beta Squad", 20, user_id2)
    logger.info(f"Team stark vergrößern: {message}")
    
    # Team auf Warteliste verkleinern
    success, message, _ = update_team_size("Zeta Squad", 5, user_id6)
    logger.info(f"Wartelisten-Team verkleinern: {message}")
    
    # Team auf Warteliste vergrößern
    success, message, _ = update_team_size("Theta Team", 10, user_id7)
    logger.info(f"Wartelisten-Team vergrößern: {message}")
    
    print_event_summary()
    
    # Test 5: Edge Case - Team abmelden
    logger.info("\n=== Test 5: Edge Case - Team abmelden ===")
    
    # Team aus Event abmelden
    success, message, freed_slots = unregister_team("Gamma Force", user_id3)
    logger.info(f"Team aus Event abmelden: {message}, Freigewordene Slots: {freed_slots}")
    
    # Teams sollten von der Warteliste aufrücken
    logger.info("Nach Abmeldung (Warteliste sollte verarbeitet werden):")
    print_event_summary()
    
    # Team von Warteliste abmelden
    success, message, freed_slots = unregister_team("Theta Team", user_id7)
    logger.info(f"Team von Warteliste abmelden: {message}")
    
    # Nicht existierendes Team abmelden
    success, message, _ = unregister_team("Nichtexistierendes Team")
    logger.info(f"Nicht-existierendes Team abmelden: {message}")
    
    print_event_summary()
    
    # Test 6: Edge Case - Event schließen
    logger.info("\n=== Test 6: Edge Case - Event schließen/öffnen ===")
    
    success, message = close_event()
    logger.info(f"Event schließen: {message}")
    
    # Versuch, Team anzumelden bei geschlossenem Event
    user_id8 = generate_random_id()
    success, message, _ = register_team("Geschlossenes Team", 5, user_id8)
    logger.info(f"Team bei geschlossenem Event anmelden: {message}")
    
    # Event wieder öffnen
    success, message, processed = open_event()
    logger.info(f"Event öffnen: {message}")
    if processed:
        logger.info(f"Verarbeitete Teams beim Öffnen: {processed}")
    
    # Team nach Wiedereröffnung anmelden
    success, message, _ = register_team("Neueröffnetes Team", 7, user_id8)
    logger.info(f"Team nach Wiedereröffnung anmelden: {message}")
    
    print_event_summary()
    
    # Test 7: Edge Case - Kapazität erweitern
    logger.info("\n=== Test 7: Edge Case - Event-Kapazität erweitern ===")
    
    # Erweitere die Event-Kapazität
    new_capacity = event_data["event"]["max_slots"] + 15
    success, message, processed = expand_event_capacity(new_capacity)
    logger.info(f"Kapazität erweitern: {message}")
    if processed:
        logger.info(f"Verarbeitete Teams bei Erweiterung: {processed}")
    
    print_event_summary()
    
    # Test 8: Edge Case - Team auf 0 setzen (abmelden)
    logger.info("\n=== Test 8: Edge Case - Team auf Größe 0 setzen ===")
    
    success, message, _ = update_team_size("Delta Crew", 0, user_id4)
    logger.info(f"Team auf Größe 0 setzen: {message}")
    
    print_event_summary()
    
    # Test 9: Vollständige Wartelisten-Verarbeitung
    logger.info("\n=== Test 9: Vollständige Wartelisten-Verarbeitung ===")
    
    # Melde alle Teams ab und registriere neue, um eine klare Warteliste zu haben
    for team_name in list(event_data["event"]["teams"].keys()):
        unregister_team(team_name)
    
    for i in range(len(event_data["event"]["waitlist"])):
        if event_data["event"]["waitlist"]:
            team_name = event_data["event"]["waitlist"][0][0]
            unregister_team(team_name)
    
    # Setze die maximale Slotanzahl zurück
    event_data["event"]["max_slots"] = 60
    event_data["event"]["slots_used"] = 0
    
    # Fülle das Event wieder
    register_team("Team A", 25)
    register_team("Team B", 30)
    
    # Füge Teams zur Warteliste hinzu
    register_team("Team C", 10)
    register_team("Team D", 15)
    register_team("Team E", 20)
    
    logger.info("Neu aufgesetzte Event-Situation:")
    print_event_summary()
    
    # Erhöhe die Kapazität deutlich
    new_capacity = 100
    success, message, processed = expand_event_capacity(new_capacity)
    logger.info(f"Kapazität stark erweitern: {message}")
    if processed:
        logger.info(f"Verarbeitete Teams bei großer Erweiterung: {processed}")
    
    print_event_summary()
    
    # Zusammenfassung am Ende
    logger.info("\n=== TESTSUITE ABGESCHLOSSEN ===")
    logger.info("Der Testlauf des Event-Bots wurde erfolgreich abgeschlossen.")
    logger.info(f"Zeitstempel: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    # Führe die vollständige Testsuite aus
    import sys
    
    try:
        # Option: Nur Testergebnisse zurückgeben
        if len(sys.argv) > 1 and sys.argv[1] == "--summary-only":
            print("Führe Tests mit --summary-only aus...")
            logger.info("Test-Modus: Nur Zusammenfassung")
        
        run_test_suite()
        
        # Erfolgsmeldung als Bestätigung
        print("\nTests erfolgreich abgeschlossen.")
        
    except Exception as e:
        logger.error(f"Fehler während der Testausführung: {e}")
        print(f"FEHLER: {e}")
        sys.exit(1)
    
    # Erfolgreicher Abschluss
    sys.exit(0)