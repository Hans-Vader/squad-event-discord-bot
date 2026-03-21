#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Interaktives Testprogramm für den Discord-Bot
Ermöglicht manuelle Tests ohne Discord-Integration
"""

import os
import sys
import logging
from datetime import datetime

# Importiere Test-Funktionen
from test import (
    reset_test_data, load_data, save_data, print_event_summary,
    register_team, unregister_team, update_team_size,
    process_waitlist, expand_event_capacity, close_event, open_event
)

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("Test/interactive_test.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("interactive_test")

def print_help():
    """Zeigt Hilfeinformationen an"""
    print("\n=== INTERAKTIVES TEST-PROGRAMM ===")
    print("Folgende Befehle sind verfügbar:")
    print("  reset              - Setzt die Testdaten zurück")
    print("  status             - Zeigt den aktuellen Status des Events an")
    print("  register <name> <size> - Registriert ein Team")
    print("  unregister <name>  - Meldet ein Team ab")
    print("  update <name> <size> - Ändert die Größe eines Teams")
    print("  expand <slots>     - Erhöht die Event-Kapazität")
    print("  close              - Schließt das Event")
    print("  open               - Öffnet das Event")
    print("  process            - Verarbeitet die Warteliste")
    print("  help               - Zeigt diese Hilfe an")
    print("  exit               - Beendet das Programm")

def main():
    """Hauptfunktion für den interaktiven Test"""
    print("Willkommen zum interaktiven Testprogramm für den Event-Bot!")
    print("Geben Sie 'help' ein, um Hilfeinformationen anzuzeigen.")
    
    # Lade Testdaten
    load_data()
    print_event_summary()
    
    while True:
        try:
            command = input("\nBefehl eingeben: ").strip()
            
            if not command:
                continue
                
            parts = command.split()
            cmd = parts[0].lower()
            
            if cmd == "exit":
                print("Programm wird beendet...")
                break
                
            elif cmd == "help":
                print_help()
                
            elif cmd == "reset":
                reset_test_data()
                print("Testdaten zurückgesetzt.")
                print_event_summary()
                
            elif cmd == "status":
                print_event_summary()
                
            elif cmd == "register":
                if len(parts) < 3:
                    print("Fehler: Format ist 'register <team_name> <size>'")
                    continue
                    
                team_name = parts[1]
                try:
                    size = int(parts[2])
                except ValueError:
                    print("Fehler: Größe muss eine Zahl sein.")
                    continue
                    
                success, message, waitlist = register_team(team_name, size)
                print(f"{'Erfolg' if success else 'Fehler'}: {message}")
                print_event_summary()
                
            elif cmd == "unregister":
                if len(parts) < 2:
                    print("Fehler: Format ist 'unregister <team_name>'")
                    continue
                    
                team_name = parts[1]
                success, message, freed_slots = unregister_team(team_name)
                print(f"{'Erfolg' if success else 'Fehler'}: {message}")
                print_event_summary()
                
            elif cmd == "update":
                if len(parts) < 3:
                    print("Fehler: Format ist 'update <team_name> <new_size>'")
                    continue
                    
                team_name = parts[1]
                try:
                    new_size = int(parts[2])
                except ValueError:
                    print("Fehler: Größe muss eine Zahl sein.")
                    continue
                    
                success, message, _ = update_team_size(team_name, new_size)
                print(f"{'Erfolg' if success else 'Fehler'}: {message}")
                print_event_summary()
                
            elif cmd == "expand":
                if len(parts) < 2:
                    print("Fehler: Format ist 'expand <new_max_slots>'")
                    continue
                    
                try:
                    new_max_slots = int(parts[1])
                except ValueError:
                    print("Fehler: Slot-Anzahl muss eine Zahl sein.")
                    continue
                    
                success, message, processed = expand_event_capacity(new_max_slots)
                print(f"{'Erfolg' if success else 'Fehler'}: {message}")
                print_event_summary()
                
            elif cmd == "close":
                success, message = close_event()
                print(f"{'Erfolg' if success else 'Fehler'}: {message}")
                print_event_summary()
                
            elif cmd == "open":
                success, message, processed = open_event()
                print(f"{'Erfolg' if success else 'Fehler'}: {message}")
                print_event_summary()
                
            elif cmd == "process":
                processed = process_waitlist()
                if processed:
                    teams_str = ", ".join([f"{team_name} (+{size})" for team_name, size in processed])
                    print(f"Warteliste verarbeitet. Folgende Teams sind aufgerückt: {teams_str}")
                else:
                    print("Keine Teams von der Warteliste aufgerückt.")
                print_event_summary()
                
            else:
                print(f"Unbekannter Befehl: {cmd}")
                print("Geben Sie 'help' ein, um Hilfeinformationen anzuzeigen.")
                
        except Exception as e:
            print(f"Fehler bei der Ausführung: {e}")
            logger.error(f"Fehler bei der Ausführung von '{command}': {e}")

if __name__ == "__main__":
    main()