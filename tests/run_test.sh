#!/bin/bash

# Skript zum Ausführen der Testsuite für den Discord-Bot
# Hinweis: Aus dem Projekt-Stammverzeichnis ausführen (z. B. ./tests/run_test.sh),
# da die Pfade relativ zum aktuellen Verzeichnis aufgelöst werden.
echo "=== Event-Bot Testsuite ==="
echo "Wählen Sie eine Option:"
echo "1) Vollständige Testsuite ausführen"
echo "2) Interaktiven Test starten"
echo "3) Test-Zusammenfassung anzeigen"
echo "q) Beenden"

read -p "Auswahl: " choice

case $choice in
  1)
    echo "Führe vollständige Testsuite aus..."
    python3 tests/test.py
    echo "Test abgeschlossen. Die Ergebnisse wurden in tests/test.log gespeichert."
    echo "Sie können die Zusammenfassung mit 'cat tests/test_summary.md' anzeigen."
    ;;
  2)
    echo "Starte interaktiven Test..."
    python3 tests/interactive_test.py
    ;;
  3)
    echo "Zeige Test-Zusammenfassung..."
    cat tests/test_summary.md
    ;;
  q)
    echo "Programm wird beendet."
    exit 0
    ;;
  *)
    echo "Ungültige Eingabe!"
    ;;
esac