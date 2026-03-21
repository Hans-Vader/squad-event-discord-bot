# Testsuite für CoC-Event-Registration Bot

Diese Testsuite wurde entwickelt, um die Hauptfunktionen des Discord-Event-Registrierungsbots zu testen, insbesondere die Wartelisten-Funktionalität und Edge Cases.

## Testumfang

1. **Team-Registrierung**: Testen des Anmeldeprozesses für Teams bis die Event-Kapazität erreicht ist
2. **Wartelisten-Funktionalität**: Automatisches Setzen von Teams auf die Warteliste, wenn das Event voll ist
3. **Größenänderung von Teams**: Vergrößern und Verkleinern von Teams, sowohl im Event als auch auf der Warteliste
4. **Team-Abmeldung**: Entfernen von Teams aus dem Event oder von der Warteliste
5. **Automatische Wartelisten-Verarbeitung**: Nachrücken von Teams von der Warteliste, wenn Plätze frei werden
6. **Kapazitätsänderungen**: Erhöhen der Event-Kapazität und Testen der automatischen Wartelisten-Verarbeitung
7. **Event-Status-Änderungen**: Schließen und Wiedereröffnen des Events

## Edge Cases

- Doppelte Team-Registrierungen (case-insensitive)
- Teilweise Aufstockung von Teams (teilweise im Event, teilweise auf Warteliste)
- Abmeldung von nicht existierenden Teams
- Registrierung während Event geschlossen ist
- Änderung der Teamgröße auf 0 (Abmeldung)
- Team-Registrierung mit identischem Namen aber unterschiedlicher Schreibweise

## Ausführen der Tests

Die Testsuite kann einfach ausgeführt werden mit:

```bash
python3 Test/test.py
```

Die Testergebnisse werden in der Datei `Test/test.log` gespeichert und auf der Konsole ausgegeben.

## Wichtige Funktionen

- `register_team()`: Registriert ein Team für das Event
- `unregister_team()`: Meldet ein Team vom Event ab
- `update_team_size()`: Ändert die Größe eines bestehenden Teams
- `process_waitlist()`: Verarbeitet die Warteliste, wenn Plätze frei werden
- `expand_event_capacity()`: Erweitert die Kapazität des Events
- `close_event()` / `open_event()`: Schließt/öffnet das Event für Anmeldungen

## Testdaten

Die Tests verwenden eine separate Datei für Testdaten (`test_event_data.pkl`), um die Produktionsdaten nicht zu beeinflussen.