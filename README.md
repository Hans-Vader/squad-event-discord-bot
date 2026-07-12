# Squad-Event-Registration Discord Bot

A Discord bot for managing squad-based events with interactive registration, waitlist management, and automatic server slot calculation.

![Discord Bot](https://img.shields.io/badge/Discord-Bot-7289DA?style=for-the-badge&logo=discord)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.0+-7289DA?style=for-the-badge&logo=discord&logoColor=white)

## Features

- **Two event modes** — **Representative mode** (register a squad with a name, playstyle, and lead) or **Player mode** (register yourself individually with an optional in-squad role; the bot auto-forms squads from arrival order, no casters, one-user-one-registration). Picked at creation: `/create_event` shows both modes side by side and you choose one with a button.
- **Tentative ("maybe") sign-ups (player mode)** — players can sign up as tentative with the **Tentative** (🤔) button: they pick a squad type (+ optional role) but take no real seat and are listed separately at the bottom of the embed, one field per squad type. Mutually exclusive with a firm sign-up (switching either way carries the type+role over, freeing/promoting seats as needed). Organizers can nudge tentatives to commit via the **Ask tentatives** (📨) button in the admin panel — picking specific tentatives (or all), then pinging them in a public or private thread, or DMing each one. A sibling **Ask registered** (📨) button does the same for the firmly-registered players — a reminder asking them to confirm attendance or withdraw via **Decline** (both modes).
- **Decline / "not attending" toggle (player mode)** — the **Decline** (❌) button doubles as a not-attending toggle: a player with no seat/waitlist/tentative spot who clicks it is marked **declined** and listed in a **🚫 Abgemeldet** field as the very last section of the embed (click again to withdraw — no confirmation, nothing is removed). Registering or going tentative clears the mark automatically.
- **Guided squad registration** — Step-by-step flow with dropdowns for squad type (Infantry/Vehicle/Heli) and playstyle (Casual/Normal/Focused) in rep mode; type + optional multi-role picker (Squad Leader, Medic, Pilot, …) in player mode. The role picker is itself toggleable by the event creator (like playstyle) — disable it and players pick no role and no roles show in the embed. Squad Leaders sort to the top of their squad and are routed into squads without an existing SL when capacity allows.
- **Three squad types** — Infantry, Vehicle, and Heli squads with independent size and count limits
- **Server slot calculation** — Automatic distribution of server capacity across all squad types and casters. The infantry squad cap is always even so both teams get the same count
- **Don't waste slots** — Optional per-event mode that offers leftover seats as **oversized infantry squads in mirrored pairs** (equal numbers per size for two equal teams, at most 9 players, as few oversized squads as possible, optional size whitelist). Reps pick the size at registration; in player mode the bot pre-plans squad capacities. See [docs/dont-waste-slots.md](docs/dont-waste-slots.md)
- **Multi-squad support** — Configurable number of squads per player (1–20)
- **Caster + squad simultaneously** — Players can register as caster AND with squads
- **Role-based access control** — Squad-Rep, Community-Rep, and Caster roles/users restrict who can register (multi-select with roles and individual users)
- **Early access** — Community-Rep and Caster early-access roles/users can register before the event opens
- **Automatic waitlist** — Squads and casters are promoted automatically when slots open up (with DM notification)
- **Registration countdown** — Configurable countdown message before registration opens (auto-deleted when registration starts)
- **Event reminders** — Configurable reminder notification X minutes before event start
- **Event image** — Optional embed image configurable via DM (upload or URL)
- **Calendar export** — Any user can click the **Calendar** button on the event embed to download a `.ics` file for import into Google Calendar, Outlook, Apple Calendar, etc.
- **DM-based event editing** — Organizers edit event properties in a guided DM conversation (18 editable properties)
- **Recurring events** — 12 recurrence types (intervals, weekday-of-month, specific date, specific weekdays/month-days). When the cycle fires, the old event is archived (summary logged + embed deleted) and a fresh event is posted automatically with the same config
- **Configurable event duration** — Set event length (30min–24h presets). Event is archived at `start + duration`; recurrence anchors on this
- **Configurable spawn delay** — For recurring events, the delay between the current event's end and the follow-up's creation (1min–1week presets, default 5min). During this window the old embed stays visible as a read-only snapshot
- **Registration auto-closes at event start** — New signups, unregistrations, and squad swaps are rejected once the event begins
- **Admin panel** — Buttons to add/remove squads and casters (rep mode) or multi-select add/remove players including waitlisted entries (player mode), edit and delete events
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
| `/help` | Show available commands |

### Interactive Buttons (in the Event Embed)

All buttons are visible to every user. Permissions are checked on click.

- **Squad** (🪖) — Rep mode: starts the guided registration (type → playstyle → name)
- **Join** (🪖) — Player mode: pick type and optional in-squad role, then auto-assigned to a squad
- **Tentative** (🤔) — Player mode: sign up as "maybe" (pick type + optional role) without taking a squad seat; switch to/from a firm sign-up at any time
- **Caster** (🎙️) — Direct caster registration
- **Decline** (❌) — Unregister squad/caster/tentative with confirmation. Player-mode second action: clicking while not registered toggles a **declined** ("not attending") mark, shown as the last embed section
- **Admin** (⚙️) — Opens admin panel (organizer only)
- **Calendar** (📅) — Download an `.ics` file to import the event into any calendar app

### Admin Panel (Organizer role required)

The admin panel opens via the **Admin** button and provides actions grouped per row:

| Row | Buttons |
|---|---|
| Squad | Add Squad (with type, playstyle, and representative user selection) · Remove Squad |
| Caster | Add Caster (user selector) · Remove Caster |
| Player (player mode) | Add Player · Remove Player · **Ask tentatives** (📨) — first pick which tentatives to ask (multi-select) or "Ask all", then ask them whether they'll join via a public/private thread ping or DM |
| Registration | Open Registration · Close Registration (· Consolidate Squads in player mode) · **Ask registered** (📨) — remind firmly-registered players to confirm/withdraw, same picker + thread/DM delivery as *Ask tentatives* (both modes) |
| Event | Edit Event (via DM) · Delete Event |

### Organizer Commands

| Command | Description |
|---|---|
| `/create_event` | Create a new event (guided wizard) — a channel can hold several active events at once |
| `/update` | Refresh event display |
| `/set_event_roles` | Add roles to the event (ping, squad-rep, community-rep, caster, caster early-access) |
| `/clear_event_roles` | Clear event roles (all or by category) |
| `/admin_edit_squad` | Edit a squad's size |
| `/admin_waitlist` | Show the current waitlist |
| `/admin_user_assignments` | Show all user-squad assignments |
| `/admin_reset_assignment` | Reset a user's assignment |
| `/export_csv` | Export squad list as CSV |

> **Multiple events per channel:** a channel can hold several active events at the same time — each is its own embed post with its own buttons. To manage a specific event (edit, open/close, delete, …), use the **⚙️ Admin** button on that event's post. When a channel-scoped command (`/update`, `/set_event_roles`, `/admin_waitlist`, `/export_csv`, …) runs in a channel with more than one active event, the bot shows a picker so you choose which event it applies to. There is no separate `/delete_event` command — delete via the **⚙️ Admin** button on the event's post.

### Server Setup Commands (Admin only)

| Command | Description |
|---|---|
| `/setup` | Initial server setup (organizer role, log channel, language) |
| `/set_organizer_role` | Set the organizer role |
| `/set_language` | Set bot language (de/en) |
| `/set_log_channel` | Set the log channel |
| `/config_defaults` | Edit default event parameters via DM dialog (organizer only) |
| `/sync` | Sync slash commands with Discord |

## Event Creation

Event creation uses a multi-step wizard:

**Step 1 — Modal (Basic Info):**
- Event name, date, time, description
- Registration start time (date/time or "sofort"/"now" for immediately)

**Step 2 — Modal (Server Configuration):**
- Server max players, max caster slots (0 = casters disabled), squad sizes (Infantry / Vehicle / Heli, each 1–9), max vehicle squads, max heli squads
- All pre-filled from server defaults (`/config_defaults`)

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
- Max squads per user (1–20)

**Step 7 — Don't waste slots** (only when ≥ 2 slots stay unused):
- Offer the leftover infantry seats as oversized squads — always in equal numbers per size so both teams can be mirrored; any size whose pair still fits the remaining seats is offered. The "Unused" counter only shows seats no pair can absorb anymore.

**Step 8 — Confirmation:**
- Summary embed with all settings including unused slots — confirm or cancel

Each step can be skipped. Server defaults from `/config_defaults` are used as starting values.

Slot calculation example:
```
Server: 100 slots
- Casters: 2 slots
- Vehicle: 5 squads × 2 = 10 slots
- Heli: 2 squads × 1 = 2 slots
- Infantry: (100 − 2 − 10 − 2) / 6 = 14 squads (84 slots)
- Unused: 2 slots
```

The infantry squad count is always rounded down to an even number so both teams get the same count; an odd cap's dropped squad counts as unused. With **Don't waste slots** enabled, unused slots are offered as oversized squads — here, one pair of 7-player infantry squads.

## DM Event Editing

Organizers can edit a running event via DM by clicking **Edit Event** in the admin panel. The bot sends a grouped property list:

**General:** Name, Date, Time, Description
**Squad Config:** Server max players, Max caster slots, Max vehicle/heli squads, Infantry/vehicle/heli squad size, Max squads per user
**Extras:** Event reminder, Registration start time, Event image, Recurrence, Duration, Spawn delay

Each edit shows old → new value with a confirmation step. The event display updates automatically after each change. Edits to date/time, recurrence, duration, or spawn delay are validated — if the next recurrence would fire during the current event (start → end + spawn delay), the edit is rejected with a specific reason.

## Recurring Events

Events can auto-spawn a follow-up when they end. Configured via DM edit properties **Recurrence** (#16), **Duration** (#17), and **Spawn delay** (#18).

- **Non-recurring**: event is archived at `start + duration` (summary logged, embed deleted).
- **Recurring**: embed stays visible as a read-only snapshot until `start + duration + spawn_delay`, then old is archived and new event is posted atomically. Config (name, slot sizes, roles, recurrence, duration, spawn delay) is inherited; runtime state is reset.

See [USER_GUIDE.md](USER_GUIDE.md#recurring-events) for the 12 recurrence types, preset lists, and validation rules.

## Installation

### Prerequisites

- Docker & Docker Compose (recommended)
- Or: Python 3.12+ for local development. The production Docker image runs **Python 3.14** — the supported target, so run the test suite on 3.14 too.
- Discord Bot Token ([Developer Portal](https://discord.com/developers/applications))

### Discord Bot Permissions

#### Privileged Gateway Intents (Developer Portal → Bot)

Both must be enabled manually:

| Intent | Reason |
|---|---|
| **Server Members Intent** | Read member roles to check organizer/squad-rep/caster permissions |
| **Message Content Intent** | Read DM replies during the guided event-edit conversation |

Presence Intent is not required.

#### Bot Permissions (OAuth2 invite)

| Permission | Reason |
|---|---|
| View Channels | Access event channels |
| Send Messages | Post event embeds, responses, and DMs |
| Embed Links | Render event displays as embeds |
| Attach Files | Deliver `/export_csv` output |
| Read Message History | Re-fetch event messages to refresh the display |
| Manage Messages | Edit/delete event, countdown, and ping messages |
| Create Public Threads | Attach the event reminder as a thread on the event message |
| Send Messages in Threads | Post the reminder content inside that thread |
| Mention @everyone, @here and All Roles | Ping configured roles on registration open / event reminder |
| Use Application Commands | Run the slash commands |

Permission integer: `397284488256`. Alternatively, grant **Administrator** for a quick setup.

The bot does **not** need: Manage Roles, Manage Channels, Manage Server, Kick/Ban/Moderate Members, Manage Nicknames, voice permissions, or Add Reactions.

### Docker (recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/Hans-Vader/squad-event-discord-bot.git
   cd squad-event-discord-bot
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
   cd bot
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
| `EVENT_TIMEZONE` | Timezone for ICS calendar export (must match the bot's local time); falls back to `TZ` | `Europe/Berlin` |
| `PUID` / `PGID` | Host user/group ID for Docker file permissions | `1000` |

### Per-Guild Settings (via `/setup` and `/config_defaults`)

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
    "max_vehicle_squads": 6,
    "max_heli_squads": 2,
    "max_squads_per_user": 3,
    "player_slots_used": 42,
    "caster_slots_used": 1,
    "registration_open": True,
    "is_closed": False,
    "registration_start_time": "2026-04-15T19:00:00",
    "duration_minutes": 120,
    "spawn_offset_minutes": 5,
    "recurrence": {"type": "every_weeks", "interval": 1},
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
    "infantry_waitlist": [("Bravo", "infantry", "Casual", 6, "jkl012", "PlayerName")],
    "vehicle_waitlist": [],
    "heli_waitlist": [],
    "caster_waitlist": [("789012", "CasterName2")]
}
```
