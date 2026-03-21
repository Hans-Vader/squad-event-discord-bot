#!/bin/bash

# Skript zum Ausführen der Testsuite für den Discord-Bot
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
    python3 Test/test.py
    echo "Test abgeschlossen. Die Ergebnisse wurden in Test/test.log gespeichert."
    echo "Sie können die Zusammenfassung mit 'cat Test/test_summary.md' anzeigen."
    ;;
  2)
    echo "Starte interaktiven Test..."
    python3 Test/interactive_test.py
    ;;
  3)
    echo "Zeige Test-Zusammenfassung..."
    cat Test/test_summary.md
    ;;
  q)
    echo "Programm wird beendet."
    exit 0
    ;;
  *)
    echo "Ungültige Eingabe!"
    ;;
esac