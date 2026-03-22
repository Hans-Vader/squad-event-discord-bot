# Squad-Event-Registration Discord Bot

A Discord bot for managing squad-based events with interactive registration, waitlist management, and automatic server slot calculation.

![Discord Bot](https://img.shields.io/badge/Discord-Bot-7289DA?style=for-the-badge&logo=discord)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.0+-7289DA?style=for-the-badge&logo=discord&logoColor=white)

## Features

- **Guided squad registration** — Step-by-step flow with dropdowns for squad type (Infantry/Vehicle/Heli) and playstyle (Casual/Normal/Focused)
- **Three squad types** — Infantry, Vehicle, and Heli squads with independent size and count limits
- **Server slot calculation** — Automatic distribution of server capacity across all squad types and casters
- **Multi-squad support** — Configurable number of squads per player (1–10)
- **Caster + squad simultaneously** — Players can register as caster AND with squads
- **Role-based access control** — Squad-Rep, Community-Rep, and Caster roles/users restrict who can register (multi-select with roles and individual users)
- **Early access** — Community-Rep and Caster early-access roles/users can register before the event opens
- **Automatic waitlist** — Squads and casters are promoted automatically when slots open up (with DM notification)
- **Registration countdown** — Configurable countdown message before registration opens (auto-deleted when registration starts)
- **Event reminders** — Configurable reminder notification X minutes before event start
- **Event image** — Optional embed image configurable via DM (upload or URL)
- **DM-based event editing** — Organizers edit event properties in a guided DM conversation (15 editable properties)
- **Admin panel** — Buttons to add/remove squads and casters, edit and delete events — with representative user selection for admin-added squads
- **Interactive UI** — Buttons, dropdowns, modals, and user selectors directly in Discord
- **Per-guild configuration** — All settings stored per server in SQLite, managed via slash commands
- **Multi-language** — German and English, configurable per server
- **Concurrency-safe** — `asyncio.Lock` prevents race conditions during simultaneous registrations
- **Atomic data persistence** — SQLite database with JSON blobs for event data
- **Debounced display updates** — Event display updates are batched during mass registrations

## Commands

### User Commands

| Command | Description |
|---|---|
| `/register` | Guided squad registration (type → playstyle → name) |
| `/unregister` | Unregister from the event |
| `/help` | Show available commands |

### Interactive Buttons (in the Event Embed)

All buttons are visible to every user. Permissions are checked on click.

- **Squad** (🪖) — Starts the guided registration (type → playstyle → name)
- **Caster** (🎙️) — Direct caster registration
- **Info** (ℹ️) — Shows your assignments and waitlist position
- **Abmelden** (❌) — Unregister squad/caster with confirmation
- **Admin** (⚙️) — Opens admin panel (organizer only)

### Admin Panel (Organizer role required)

The admin panel opens via the **Admin** button and provides 6 actions in 3 rows:

| Row | Buttons |
|---|---|
| Squad | Add Squad (with type, playstyle, and representative user selection) · Remove Squad |
| Caster | Add Caster (user selector) · Remove Caster |
| Event | Edit Event (via DM) · Delete Event |

### Organizer Commands

| Command | Description |
|---|---|
| `/event` | Create a new event (guided wizard) |
| `/delete_event` | Delete the event in this channel |
| `/open` | Open registration immediately |
| `/close` | Close registration |
| `/update` | Refresh event display |
| `/set_event_roles` | Add roles to the event (ping, squad-rep, community-rep, caster, caster early-access) |
| `/clear_event_roles` | Clear event roles (all or by category) |
| `/admin_edit_squad` | Edit a squad's size |
| `/admin_waitlist` | Show the current waitlist |
| `/admin_user_assignments` | Show all user-squad assignments |
| `/admin_reset_assignment` | Reset a user's assignment |
| `/export_csv` | Export squad list as CSV |

### Server Setup Commands (Admin only)

| Command | Description |
|---|---|
| `/setup` | Initial server setup (organizer role, log channel, language) |
| `/set_organizer_role` | Set the organizer role |
| `/set_language` | Set bot language (de/en) |
| `/set_log_channel` | Set the log channel |
| `/set_defaults` | Set default event parameters (server capacity, squad sizes, limits) |
| `/settings` | Show current server settings |
| `/sync` | Sync slash commands with Discord |

## Event Creation

Event creation uses a multi-step wizard:

**Step 1 — Modal (Basic Info):**
- Event name, date, time, description
- Registration start time (date/time or "sofort"/"now" for immediately)

**Step 2 — Modal (Server Configuration):**
- Server max players, max caster slots (0 = casters disabled), squad sizes (Infantry / Vehicle / Heli), max vehicle squads, max heli squads
- All pre-filled from server defaults (`/set_defaults`)

**Step 3 — Squad Roles:**
- Squad-Rep roles/users — who can register squads (role gate)
- Community-Rep roles/users — who can register before registration opens (early access)
- Ping on open toggle

**Step 4 — Caster Roles:**
- Caster roles/users — who can register as caster (role gate)
- Caster early-access roles/users
- Ping on open toggle

**Step 5 — Timing:**
- Event reminder (0–1440 minutes before event start)
- Registration countdown (0–28800 seconds before registration opens)

**Step 6 — Squad Limit:**
- Max squads per user (1–10)

**Step 7 — Confirmation:**
- Summary embed with all settings including unused slots — confirm or cancel

Each step can be skipped. Server defaults from `/set_defaults` are used as starting values.

Slot calculation example:
```
Server: 100 slots
- Casters: 2 slots
- Vehicle: 5 squads × 2 = 10 slots
- Heli: 2 squads × 1 = 2 slots
- Infantry: (100 − 2 − 10 − 2) / 6 = 14 squads (84 slots)
- Unused: 2 slots
```

## DM Event Editing

Organizers can edit a running event via DM by clicking **Edit Event** in the admin panel. The bot sends a grouped property list:

**General:** Name, Date, Time, Description
**Squad Config:** Server max players, Max caster slots, Max vehicle/heli squads, Infantry/vehicle/heli squad size, Max squads per user
**Extras:** Event reminder, Registration start time, Event image

Each edit shows old → new value with a confirmation step. The event display updates automatically after each change.

## Installation

### Prerequisites

- Docker & Docker Compose (recommended)
- Or: Python 3.12+
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
   # Set DISCORD_BOT_TOKEN (required)
   ```

3. Start:
   ```bash
   docker-compose up -d
   ```

4. In Discord, run `/setup` to configure the organizer role, log channel, and language.

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

3. In Discord, run `/setup` to configure the bot.

## Configuration

### Environment Variables (.env)

| Variable | Description | Default |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Bot token from the Developer Portal | (required) |
| `ADMIN_IDS` | Comma-separated Discord user IDs (superadmin, bypass all checks) | (optional) |
| `DEBUG_MODE` | Enable debug logging | `false` |
| `EVENT_DEFAULT_DATE` | Pre-filled date in event creation modal | `last_sunday` |
| `EVENT_DEFAULT_TIME` | Pre-filled time in event creation modal | `20:00` |
| `EVENT_DEFAULT_REG_START` | Pre-filled registration start in event creation modal | (empty) |
| `PUID` / `PGID` | Host user/group ID for Docker file permissions | `1000` |

### Per-Guild Settings (via `/setup` and `/set_defaults`)

| Setting | Default |
|---|---|
| Language | `de` |
| Server max players | `100` |
| Infantry squad size | `6` |
| Vehicle squad size | `2` |
| Heli squad size | `1` |
| Max vehicle squads | `6` |
| Max heli squads | `2` |
| Max caster slots | `2` |
| Max squads per user | `1` |
| Registration countdown | `60` seconds |
| Caster registration | enabled |

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
    "registration_open": True,
    "is_closed": False,
    "registration_start_time": "2026-04-15T19:00:00",
    "countdown_seconds": 60,
    "countdown_sent": False,
    "countdown_message_id": None,
    "ping_on_open": True,
    "ping_message_ids": [123456789],
    "event_reminder_minutes": 30,
    "event_reminder_sent": False,
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
        "Alpha": {"type": "infantry", "playstyle": "Focused", "size": 6, "id": "abc123", "rep_name": "PlayerName"},
        "Panzer1": {"type": "vehicle", "playstyle": "Normal", "size": 2, "id": "def456", "rep_name": "PlayerName"}
    },
    "casters": {"123456": {"name": "CasterName", "id": "123456"}},
    "waitlist": [("Bravo", "infantry", "Casual", 6, "jkl012", "PlayerName")],
    "caster_waitlist": [("789012", "CasterName2")]
}
```

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
