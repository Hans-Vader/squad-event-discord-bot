# Einrichtung des CoC-Event-Registration Discord Bots

Diese Anleitung hilft dir bei der vollständigen Einrichtung des CoC-Event-Registration Discord Bots auf deinem Server.

## Voraussetzungen

- Python 3.8 oder höher
- Discord Bot Token (erstellt über das [Discord Developer Portal](https://discord.com/developers/applications))
- Discord Server mit Administrator-Berechtigungen
- Grundlegende Kenntnisse über Discord-Berechtigungen und Bot-Einrichtung

## Detaillierte Installations-Schritte

### 1. Repository klonen

```bash
git clone https://github.com/FVollbrecht/CoC-Event-Registration.git
cd CoC-Event-Registration
```

### 2. Virtuelle Umgebung erstellen (empfohlen)

Eine virtuelle Umgebung hilft dir, Abhängigkeiten sauber zu verwalten:

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Abhängigkeiten installieren

```bash
# Methode 1: Mit der requirements.txt (wenn vorhanden)
pip install -r requirements.txt

# Methode 2: Manuell die wichtigsten Pakete installieren
pip install discord.py>=2.0.0 python-dotenv>=0.19.2 aiohttp>=3.8.1

# Optional für Voice-Support (nicht notwendig für die Kernfunktionalität)
pip install pynacl>=1.5.0
```

### 4. Umgebungsvariablen einrichten

Erstelle eine Datei `.env` im Hauptverzeichnis mit folgendem Inhalt:

```
DISCORD_TOKEN=dein_bot_token
ORGANIZER_ROLE=Organizer
CLAN_REP_ROLE=Clan Rep
LOG_CHANNEL=log
```

Ersetze `dein_bot_token` mit deinem eigenen Discord Bot Token, das du im Discord Developer Portal erstellt hast.

**Wichtig:** Die Rollennamen und der Log-Kanal-Name können angepasst werden. Stelle sicher, dass sie genau mit den Namen auf deinem Discord-Server übereinstimmen.

### 5. Erstellen eines Discord Bot Tokens (falls noch nicht vorhanden)

1. Besuche das [Discord Developer Portal](https://discord.com/developers/applications)
2. Klicke auf "New Application" und gib einen Namen ein
3. Gehe zum Bereich "Bot" und klicke auf "Add Bot"
4. Unter dem Abschnitt "TOKEN" klicke auf "Copy" oder "Reset Token", um dein Bot-Token zu erhalten
5. Aktiviere die folgenden Intents unter "Privileged Gateway Intents":
   - Presence Intent
   - Server Members Intent
   - Message Content Intent

### 6. Bot zum Server hinzufügen

1. Gehe im Developer Portal zum Bereich "OAuth2" > "URL Generator"
2. Wähle unter "Scopes" die Option "bot" und "applications.commands"
3. Wähle unter "Bot Permissions" mindestens diese Berechtigungen:
   - Manage Roles
   - Manage Channels
   - Read Messages/View Channels
   - Send Messages
   - Manage Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Add Reactions
4. Kopiere die generierte URL und öffne sie in deinem Browser
5. Wähle deinen Server aus und autorisiere den Bot

### 7. Datenstruktur initialisieren

Bevor du den Bot startest, initialisiere die Datenstruktur:

```bash
python initialize_data.py
```

Dies erstellt die Datei `event_data.pkl` mit einer leeren Event-Struktur.

### 8. Bot starten

```bash
python bot.py
```

Bei erfolgreicher Einrichtung solltest du in der Konsole Nachrichten wie "Bot eingeloggt als..." sehen.

## Konfiguration auf dem Discord-Server

### 1. Rollen einrichten

Erstelle diese Rollen mit den entsprechenden Berechtigungen:

- **Organizer** (Administrator-Rolle)
  - Berechtigungen: Administrator oder mindestens Nachrichten verwalten, Rollen verwalten
  
- **Clan Rep** (Teamleiter-Rolle)
  - Berechtigungen: Nachrichten senden, Reaktionen hinzufügen

### 2. Kanäle einrichten

- **registration** (Haupt-Kanal für Interaktionen)
  - Berechtigungen für den Bot: Nachrichten lesen/senden/verwalten, Einbettungen
  
- **log** (Kanal für System-Logs)
  - Berechtigungen für den Bot: Nachrichten senden
  - Beschränke den Zugriff so, dass nur Administratoren und der Bot diesen Kanal sehen können

### 3. Erweiterte Bot-Berechtigungen

Stelle sicher, dass der Bot diese Berechtigungen in den relevanten Kanälen hat:

- Nachrichten lesen und anzeigen
- Nachrichten senden und verwalten
- Einbettungen senden
- Dateien anhängen
- Reaktionen hinzufügen
- Slash-Befehle verwenden

## Erste Schritte nach der Installation

### 1. Befehle synchronisieren

Nach dem ersten Start des Bots solltest du die Slash-Commands synchronisieren:

```
/sync_commands
```

### 2. Grundlegende Befehle testen

Teste folgende Befehle, um sicherzustellen, dass alles funktioniert:

1. `/help` - Zeigt die Hilfe an
2. `/create_event` - Erstellt ein Test-Event mit den neuen Vorlagen
3. `/show_event` - Zeigt das Event mit allen Buttons an

### 3. Administratoren einrichten

Weise die "Organizer"-Rolle den Personen zu, die Admin-Berechtigungen haben sollen.

## Fehlerbehebung

### Häufige Probleme und Lösungen

- **Bot startet nicht**:
  - Überprüfe, ob das Token in der `.env`-Datei korrekt ist
  - Stelle sicher, dass alle erforderlichen Packages installiert sind
  - Überprüfe die Berechtigungen im Bot-Tab des Developer Portals

- **Slash-Commands werden nicht angezeigt**:
  - Führe `/sync_commands` aus
  - Stelle sicher, dass der Bot die "applications.commands"-Berechtigung hat
  - Warte einige Minuten, da Discord manchmal Zeit braucht, um Commands zu registrieren

- **Datenbank-Fehler**:
  - Überprüfe, ob `event_data.pkl` existiert und der Bot Schreibrechte hat
  - Führe `python initialize_data.py` erneut aus, um die Datei neu zu erstellen

- **Bestätigungsdialoge funktionieren nicht**:
  - Stelle sicher, dass du die neueste Version von Discord.py (2.0+) verwendest
  - Überprüfe, ob der Bot die richtigen Intent-Berechtigungen hat

- **Log-Kanal-Fehler**:
  - Überprüfe, ob der in `.env` angegebene Log-Kanal existiert
  - Stelle sicher, dass der Bot Berechtigungen hat, in diesen Kanal zu schreiben

### Support und weitere Hilfe

Wenn du weiterhin Probleme hast oder Hilfe benötigst:

1. Überprüfe die ausführliche Dokumentation in der README.md und im USER_GUIDE.md
2. Erstelle ein Issue im [GitHub-Repository](https://github.com/FVollbrecht/CoC-Event-Registration/issues)
3. Kontaktiere die Entwickler über Discord für direkten Support

## Aktualisierung des Bots

Um den Bot auf die neueste Version zu aktualisieren:

```bash
git pull
pip install -r requirements.txt  # Falls es Änderungen bei den Abhängigkeiten gab
```

Nach der Aktualisierung starte den Bot neu und führe `/sync_commands` aus, um sicherzustellen, dass alle Befehle aktuell sind.