#!/usr/bin/env python3
"""
Diagnostisches Tool zur Überprüfung der Datenstruktur in der event_data.pkl-Datei.
Dieses Skript liest die aktuelle Datenstruktur und gibt Details zum Event aus.
"""

import pickle
import json
import argparse

def check_data(pkl_file='event_data.pkl', json_output=False, detailed=False):
    """
    Prüft und zeigt die Inhalte der event_data.pkl-Datei an.
    
    Parameters:
    - pkl_file: Pfad zur Pickle-Datei (Default: 'event_data.pkl')
    - json_output: Ob die Ausgabe im JSON-Format erfolgen soll (für Scripting, Default: False)
    - detailed: Ob detaillierte Informationen angezeigt werden sollen (Default: False)
    """
    try:
        # Lade die Daten
        with open(pkl_file, 'rb') as f:
            data = pickle.load(f)
        
        # Basis-Datenstruktur
        result = {
            "status": "success",
            "data_structure": {
                "keys": list(data.keys()),
                "types": {k: str(type(v).__name__) for k, v in data.items()}
            }
        }
        
        # Event-Daten
        event_data = data.get('event_data', {})
        if event_data:
            event = event_data.get('event', {})
            if event:
                result["event"] = {
                    "name": event.get('name'),
                    "date": event.get('date'),
                    "time": event.get('time'),
                    "description": event.get('description', 'keine')[:30] + '...' if detailed else '...',
                    "teams_count": len(event.get('teams', {})),
                    "waitlist_count": len(event.get('waitlist', [])),
                    "max_slots": event.get('max_slots', 0),
                    "slots_used": event.get('slots_used', 0),
                    "max_team_size": event.get('max_team_size', 0),
                    "is_closed": event.get('is_closed', False)
                }
                
                # Detaillierte Teamliste, wenn angefordert
                if detailed:
                    result["event"]["teams"] = {}
                    for team_name, team_data in event.get('teams', {}).items():
                        if isinstance(team_data, dict):
                            result["event"]["teams"][team_name] = team_data
                        else:
                            result["event"]["teams"][team_name] = {"size": team_data}
                    
                    result["event"]["waitlist"] = []
                    for entry in event.get('waitlist', []):
                        if len(entry) >= 3:  # Neues Format: (team_name, size, team_id)
                            result["event"]["waitlist"].append({
                                "team_name": entry[0],
                                "size": entry[1],
                                "team_id": entry[2]
                            })
                        else:  # Altes Format: (team_name, size)
                            result["event"]["waitlist"].append({
                                "team_name": entry[0],
                                "size": entry[1]
                            })
            else:
                result["event"] = None
        else:
            result["event"] = None
        
        # Kanal-ID
        result["channel_id"] = data.get('channel_id')
        
        # Benutzer-Team-Zuweisungen
        user_team_assignments = data.get('user_team_assignments', {})
        result["user_team_assignments_count"] = len(user_team_assignments)
        if detailed:
            result["user_team_assignments"] = user_team_assignments
        
        # Ausgabe im gewünschten Format
        if json_output:
            print(json.dumps(result, indent=2))
        else:
            print("=== Event-Bot Daten-Check ===")
            print(f"Datei: {pkl_file}")
            print("\nBasis-Datenstruktur:")
            print(f"- Keys: {', '.join(result['data_structure']['keys'])}")
            for k, v in result['data_structure']['types'].items():
                print(f"- {k}: {v}")
            
            print("\nEvent-Daten:")
            if result["event"]:
                print(f"- Name: {result['event']['name']}")
                print(f"- Datum: {result['event']['date']}")
                print(f"- Uhrzeit: {result['event']['time']}")
                print(f"- Beschreibung: {result['event']['description']}")
                print(f"- Teams: {result['event']['teams_count']}")
                print(f"- Warteliste: {result['event']['waitlist_count']}")
                print(f"- Max. Slots: {result['event']['max_slots']}")
                print(f"- Belegte Slots: {result['event']['slots_used']}")
                print(f"- Max. Teamgröße: {result['event']['max_team_size']}")
                print(f"- Geschlossen: {result['event']['is_closed']}")
                
                if detailed and result["event"]["teams"]:
                    print("\nTeams:")
                    for team_name, team_data in result["event"]["teams"].items():
                        size = team_data.get("size", "?")
                        team_id = team_data.get("id", "keine ID")
                        print(f"  - {team_name} (Größe: {size}, ID: {team_id})")
                
                if detailed and result["event"]["waitlist"]:
                    print("\nWarteliste:")
                    for i, entry in enumerate(result["event"]["waitlist"]):
                        team_name = entry.get("team_name", "?")
                        size = entry.get("size", "?")
                        team_id = entry.get("team_id", "keine ID")
                        print(f"  {i+1}. {team_name} (Größe: {size}, ID: {team_id})")
            else:
                print("Kein aktives Event gefunden.")
            
            print(f"\nKanal-ID: {result['channel_id']}")
            print(f"\nBenutzer-Team-Zuweisungen: {result['user_team_assignments_count']}")
            
            if detailed and user_team_assignments:
                print("\nZuweisungen:")
                for user_id, team_name in user_team_assignments.items():
                    print(f"  - Benutzer {user_id}: {team_name}")
            
            print("\n=== Check abgeschlossen ===")
        
        return result
    
    except FileNotFoundError:
        result = {"status": "error", "message": f"Datei {pkl_file} nicht gefunden."}
        if json_output:
            print(json.dumps(result, indent=2))
        else:
            print(f"Fehler: Datei {pkl_file} nicht gefunden.")
        return result
    
    except Exception as e:
        result = {"status": "error", "message": f"Fehler beim Lesen der Datei: {str(e)}"}
        if json_output:
            print(json.dumps(result, indent=2))
        else:
            print(f"Fehler beim Lesen der Datei: {str(e)}")
        return result

if __name__ == "__main__":
    # Kommandozeilenparameter
    parser = argparse.ArgumentParser(description='Prüft die Datenstruktur der event_data.pkl-Datei.')
    parser.add_argument('--file', default='event_data.pkl', help='Pfad zur Pickle-Datei')
    parser.add_argument('--json', action='store_true', help='Ausgabe im JSON-Format')
    parser.add_argument('--detailed', action='store_true', help='Zeigt detaillierte Informationen an')
    
    args = parser.parse_args()
    check_data(args.file, args.json, args.detailed)