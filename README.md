# Squad-Event-Registration Discord Bot

A Discord bot for managing squad-based events with interactive registration, waitlist management, and automatic server slot calculation.

![Discord Bot](https://img.shields.io/badge/Discord-Bot-7289DA?style=for-the-badge&logo=discord)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.0+-7289DA?style=for-the-badge&logo=discord&logoColor=white)

## Features

- **Guided squad registration** — Step-by-step flow with dropdowns for squad type (Infantry/Vehicle/Heli) and playstyle (Casual/Normal/Focused)
- **Three squad types** — Infantry, Vehicle, and Heli squads with independent size and count limits
- **Server slot calculation** — Automatic distribution of server capacity across all squad types and casters
- **Multi-squad support** — Configurable number of squads per player
- **Caster + squad simultaneously** — Players can register as caster AND with squads
- **Role-based access control** — Squad-Rep, Community-Rep, and Caster roles/users restrict who can register (all support multi-select with roles and individual users)
- **Early access** — Community-Rep and Caster early-access roles/users can register before the event opens
- **Automatic waitlist** — Squads are promoted automatically when slots open up (with DM notification)
- **Event reminders** — Configurable reminder notification X minutes before event start
- **Event image** — Optional embed image configurable via DM (upload or URL)
- **DM-based event editing** — Organizers edit event properties in a guided DM conversation (15 editable properties)
- **Interactive UI** — Buttons, dropdowns, and modals directly in Discord
- **Concurrency-safe** — `asyncio.Lock` prevents race conditions during simultaneous registrations
- **Atomic data persistence** — Pickle writes via temp file + `os.replace()` prevent data corruption
- **Debounced display updates** — Event display updates are batched during mass registrations

## Commands

### User Commands

| Command | Description |
|---|---|
| `/register` | Starts the guided squad registration (type + playstyle → name) |
| `/register_squad [name]` | Register a squad with a predefined name |
| `/register_caster` | Register as caster |
| `/unregister` | Unregister from the event |
| `/squad_list` | Shows all registered squads |
| `/find [name]` | Search for a squad or player |
| `/help` | Shows available commands |

### Interactive Buttons (in the Event Embed)

All buttons are visible to every user. Permissions are checked on click.

- **Squad anmelden** — Starts the guided registration (type + playstyle → name)
- **Als Caster anmelden** — Direct caster registration
- **Mein Squad/Caster** — Shows own assignments and waitlist position
- **Abmelden** — Unregister squad/caster with confirmation
- **Admin** — Opens admin actions (add/remove squad, edit event via DM, delete event)

### Admin Commands (Organizer role required)

| Command | Description |
|---|---|
| `/event` | Creates a new event (guided wizard: modals → role selection → confirmation) |
| `/show_event` | Shows the event with interactive buttons |
| `/delete_event` | Deletes the current event |
| `/open` | Opens registration immediately |
| `/close` | Closes registration |
| `/admin_add_squad` | Adds a squad (guided flow with dropdown) |
| `/admin_add_caster [user]` | Adds a user as caster (bypasses time/role restrictions) |
| `/admin_remove_caster` | Removes a caster (dropdown selection) |
| `/admin_squad_remove` | Removes a squad (dropdown selection) |
| `/set_max_squads [count]` | Sets max squads per player for the event |
| `/set_ping_role [roles]` | Sets roles to ping when registration opens (up to 3) |
| `/set_squad_rep_role [role] [user]` | Add/remove squad-rep role or user (toggle) |
| `/set_community_rep_role [role] [user]` | Add/remove community-rep role or user (early access, toggle) |
| `/set_caster_role [role] [user]` | Add/remove caster role or user (toggle) |
| `/set_streamer_role [role] [user]` | Add/remove streamer role or user (toggle) |
| `/set_event_reminder [minutes]` | Sets a reminder X minutes before event start (0 = disable) |
| `/set_channel` | Sets the channel for event updates |
| `/admin_waitlist` | Shows the complete waitlist |
| `/admin_user_assignments` | Shows all user assignments |
| `/admin_user_info [user]` | Shows Discord ID, username, and squad/caster assignment |
| `/reset_team_assignment [user]` | Resets a user's assignment |
| `/export_csv` | Exports squad list as CSV |
| `/update` | Refreshes the event display |
| `/admin_help` | Shows admin help |
| `/sync` | Syncs slash commands |
| `/export_log` | Exports the log file |
| `/clear_log` | Clears the log file |
| `/clear_messages [count]` | Deletes messages in the channel |

## Event Creation

Event creation uses a modal followed by an optional post-creation role wizard:

**Modal — Basic Info:**
- Event name, date, time, description
- Registration start time (date/time or "sofort"/"now" for immediately)

The event is created and displayed immediately after the modal is submitted. Server configuration (capacity, squad sizes, limits) uses guild defaults set via `/set_defaults`. Event reminders can be added afterwards with `/set_event_reminder`.

**Post-Creation Role Wizard (optional, 2 steps):**

After the event is created, an ephemeral role wizard appears automatically:

*Step 1 — Squad Roles:*
- Squad-Rep roles/users — who can register squads (role gate, enforced during registration)
- Community-Rep roles/users — who can register squads before registration opens (early access)

*Step 2 — Caster Roles:*
- Caster roles/users — who can register as caster (role gate, enforced during registration)
- Caster early-access roles/users — who can register as caster before registration opens

Each step uses mentionable select menus that support both roles and individual users. Each step can be skipped — if skipped or timed out, no gate is set and anyone can register. Roles can also be configured later with `/set_event_roles`.

Slot calculation example:
```
Server: 100 slots
- Casters: 2 slots
- Vehicle: 5 squads x 2 = 10 slots
- Heli: 2 squads x 1 = 2 slots
- Infantry: (100 - 2 - 10 - 2) / 6 = 14 squads (84 slots)
- Unused: 2 slots
```

## DM Event Editing

Organizers can edit a running event via DM by clicking **Event bearbeiten** in the admin menu. The bot sends a numbered list of 15 editable properties:

1. Event name
2. Date
3. Time
4. Description
5. Server max players
6. Max caster slots
7. Max vehicle squads
8. Max heli squads
9. Infantry squad size
10. Vehicle squad size
11. Heli squad size
12. Max squads per player
13. Event reminder (minutes, 0 = disable)
14. Registration start time
15. Event image (upload an image or paste an HTTPS URL)

Each edit shows old → new value with a confirmation step. The event display in the channel updates automatically after each change.

## Installation

### Prerequisites

- Docker & Docker Compose (recommended)
- Or: Python 3.11+
- Discord Bot Token ([Developer Portal](https://discord.com/developers/applications))

### Docker (recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/FVollbrecht/CoC-Event-Registration.git
   cd CoC-Event-Registration
   ```

2. Create `.env` (based on `.env.dist`):
   ```bash
   cp .env.dist .env
   # Edit values (token, role IDs, etc.)
   ```

3. Start:
   ```bash
   docker-compose up -d
   ```

### Manual

1. Clone and install dependencies:
   ```bash
   pip install discord.py>=2.0.0 python-dotenv>=0.19.2 aiohttp>=3.8.1 pynacl>=1.5.0
   ```

2. Create `.env` and start the bot:
   ```bash
   cp .env.dist .env
   cd DebugScriptHelper
   python bot.py
   ```

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Bot token from the Developer Portal | (required) |
| `ORGANIZER_ROLE` | Role ID for admins/organizers | `0` |
| `LOG_CHANNEL` | Channel ID or name for logs | `log` |
| `ADMIN_IDS` | Comma-separated Discord user IDs | (optional) |
| `CASTER_REGISTRATION_ENABLED` | Enable/disable caster registration | `true` |
| `MAX_SQUADS_PER_USER` | Max squads per player | `1` |
| `SERVER_MAX_PLAYERS` | Server capacity (total players) | `100` |
| `INFANTRY_SQUAD_SIZE` | Players per infantry squad | `6` |
| `VEHICLE_SQUAD_SIZE` | Players per vehicle squad | `2` |
| `HELI_SQUAD_SIZE` | Players per heli squad | `1` |
| `DEFAULT_MAX_VEHICLE_SQUADS` | Default max vehicle squads | `5` |
| `DEFAULT_MAX_HELI_SQUADS` | Default max heli squads | `5` |
| `DEFAULT_MAX_CASTER_SLOTS` | Default max caster slots | `2` |
| `REGISTRATION_COUNTDOWN_SECONDS` | Countdown message before registration opens | `60` |
| `PUID` / `PGID` | Host user/group ID for Docker file permissions | `1000` |

All server configuration (capacity, squad sizes, limits) can be customized per event during creation.

## Data Structure

```python
{
    "name": "My Event",
    "date": "15.04.2026",
    "time": "20:00",
    "description": "Event description",
    "server_max_players": 100,
    "infantry_squad_size": 6,
    "vehicle_squad_size": 2,
    "heli_squad_size": 1,
    "max_player_slots": 98,
    "max_caster_slots": 2,
    "max_vehicle_squads": 5,
    "max_heli_squads": 2,
    "max_squads_per_user": 3,
    "player_slots_used": 42,
    "caster_slots_used": 1,
    "embed_image_url": "https://cdn.discordapp.com/...",
    "squad_rep_role_ids": [123456],
    "squad_rep_user_ids": ["789012"],
    "community_rep_role_ids": [234567],
    "community_rep_user_ids": [],
    "caster_role_ids": [345678],
    "caster_user_ids": [],
    "caster_community_role_ids": [456789],
    "caster_community_user_ids": ["567890"],
    "squads": {
        "Alpha": {"type": "infantry", "playstyle": "Focused", "size": 6, "id": "abc123"},
        "Panzer1": {"type": "vehicle", "playstyle": "Normal", "size": 2, "id": "def456"},
        "Heli1": {"type": "heli", "playstyle": "Normal", "size": 1, "id": "ghi789"}
    },
    "casters": {"123456": {"name": "CasterName", "id": "123456"}},
    "waitlist": [("Bravo", "infantry", "Casual", 6, "jkl012")],
    "caster_waitlist": [("789012", "CasterName2")],
    "registration_open": true,
    "registration_start_time": null,
    "event_reminder_minutes": 30
}
```

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
