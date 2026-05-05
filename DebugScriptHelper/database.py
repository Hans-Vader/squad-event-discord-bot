#!/usr/bin/env python3
"""
Database layer for the Event Registration Bot.

Uses SQLite with two main tables:
- guild_settings: per-guild configuration (organizer role, defaults, language, etc.)
- events: per-channel events with JSON blobs for event data and assignments.

Every public function accepts a guild_id to ensure full multi-guild isolation.
"""

import json
import os
import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("event_bot.db")

DB_FILE = os.path.join("data", "event_data.db")

# ---------------------------------------------------------------------------
# JSON helpers for datetime round-tripping
# ---------------------------------------------------------------------------

class _DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        return super().default(obj)


def _datetime_hook(obj):
    if "__datetime__" in obj:
        return datetime.fromisoformat(obj["__datetime__"])
    return obj


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_DateTimeEncoder)


def _loads(raw: str):
    return json.loads(raw, object_hook=_datetime_hook)


# ---------------------------------------------------------------------------
# Default guild settings (used when a guild is first configured)
# ---------------------------------------------------------------------------

DEFAULT_GUILD_SETTINGS = {
    "organizer_role_id": 0,
    "log_channel_id": None,
    "language": "en",
    "server_max_players": 100,
    "infantry_squad_size": 6,
    "vehicle_squad_size": 2,
    "heli_squad_size": 1,
    "max_vehicle_squads": 6,
    "max_heli_squads": 2,
    "max_caster_slots": 2,
    "max_squads_per_user": 1,
    "caster_registration_enabled": True,
    "registration_countdown_seconds": 60,
}


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id     INTEGER PRIMARY KEY,
            settings     TEXT    NOT NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id            INTEGER NOT NULL,
            channel_id          INTEGER NOT NULL,
            event_data          TEXT    NOT NULL,
            user_assignments    TEXT    NOT NULL DEFAULT '{}',
            status              TEXT    NOT NULL DEFAULT 'active',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(guild_id, channel_id, status)
        );

        CREATE INDEX IF NOT EXISTS idx_events_guild
            ON events(guild_id, status);
        CREATE INDEX IF NOT EXISTS idx_events_channel
            ON events(guild_id, channel_id, status);
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialised: {DB_FILE}")


# ---------------------------------------------------------------------------
# Guild settings
# ---------------------------------------------------------------------------

def get_guild_settings(guild_id: int) -> Optional[dict]:
    """Return settings dict for a guild, or None if not configured."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT settings FROM guild_settings WHERE guild_id = ?", (guild_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    settings = _loads(row[0])
    # Backfill any new keys that were added after initial setup
    merged = {**DEFAULT_GUILD_SETTINGS, **settings}
    return merged


def save_guild_settings(guild_id: int, settings: dict):
    """Upsert guild settings."""
    conn = _get_conn()
    with conn:
        conn.execute(
            """INSERT INTO guild_settings (guild_id, settings, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(guild_id) DO UPDATE SET settings=excluded.settings, updated_at=excluded.updated_at""",
            (guild_id, _dumps(settings)),
        )
    conn.close()


def get_guild_language(guild_id: int) -> str:
    """Shortcut: return language code for a guild (default 'de')."""
    settings = get_guild_settings(guild_id)
    if settings is None:
        return DEFAULT_GUILD_SETTINGS["language"]
    return settings.get("language", DEFAULT_GUILD_SETTINGS["language"])


def guild_is_configured(guild_id: int) -> bool:
    """Check if a guild has run /setup."""
    return get_guild_settings(guild_id) is not None


# ---------------------------------------------------------------------------
# Events — one active event per (guild, channel)
# ---------------------------------------------------------------------------

def get_event_by_channel(guild_id: int, channel_id: int) -> Optional[dict]:
    """Return the active event for a channel, or None."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT id, event_data, user_assignments
           FROM events
           WHERE guild_id = ? AND channel_id = ? AND status = 'active'
           LIMIT 1""",
        (guild_id, channel_id),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    event_data = _loads(row[1])
    user_assignments = _loads(row[2])
    return {
        "db_id": row[0],
        "event": event_data,
        "user_assignments": user_assignments,
    }


def get_all_active_events(guild_id: int) -> list[dict]:
    """Return all active events for a guild."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, channel_id, event_data, user_assignments
           FROM events
           WHERE guild_id = ? AND status = 'active'""",
        (guild_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            "db_id": row[0],
            "channel_id": row[1],
            "event": _loads(row[2]),
            "user_assignments": _loads(row[3]),
        })
    return result


def get_all_active_events_global() -> list[dict]:
    """Return all active events across all guilds (for background tasks)."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, guild_id, channel_id, event_data, user_assignments
           FROM events
           WHERE status = 'active'"""
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            "db_id": row[0],
            "guild_id": row[1],
            "channel_id": row[2],
            "event": _loads(row[3]),
            "user_assignments": _loads(row[4]),
        })
    return result


def save_event(db_id: int, event_data: dict, user_assignments: dict):
    """Update an existing event row."""
    conn = _get_conn()
    with conn:
        conn.execute(
            """UPDATE events
               SET event_data = ?, user_assignments = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (_dumps(event_data), _dumps(user_assignments), db_id),
        )
    conn.close()


def create_event(guild_id: int, channel_id: int, event_data: dict) -> int:
    """Insert a new active event. Returns the new row id."""
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            """INSERT INTO events (guild_id, channel_id, event_data, user_assignments, status)
               VALUES (?, ?, ?, '{}', 'active')""",
            (guild_id, channel_id, _dumps(event_data)),
        )
        new_id = cur.lastrowid
    conn.close()
    logger.info(f"Event created: db_id={new_id}, guild={guild_id}, channel={channel_id}")
    return new_id


def delete_event(db_id: int):
    """Mark an event as deleted (soft-delete). Uses unique status to avoid UNIQUE constraint."""
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE events SET status = 'deleted_' || id, updated_at = datetime('now') WHERE id = ?",
            (db_id,),
        )
    conn.close()
    logger.info(f"Event deleted: db_id={db_id}")


def expire_event(db_id: int):
    """Mark an event as expired (soft-delete). Uses unique status to avoid UNIQUE constraint."""
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE events SET status = 'expired_' || id, updated_at = datetime('now') WHERE id = ?",
            (db_id,),
        )
    conn.close()
    logger.info(f"Event expired: db_id={db_id}")


def channel_has_active_event(guild_id: int, channel_id: int) -> bool:
    """Check if a channel already has an active event."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM events WHERE guild_id = ? AND channel_id = ? AND status = 'active' LIMIT 1",
        (guild_id, channel_id),
    ).fetchone()
    conn.close()
    return row is not None


# ---------------------------------------------------------------------------
# Convenience: build default event data dict
# ---------------------------------------------------------------------------

def build_default_event(settings: dict, name: str, date: str, time_str: str,
                        description: str = None, **overrides) -> dict:
    """Build a fresh event dict from guild settings + creation params."""
    server_max = overrides.get("server_max_players", settings["server_max_players"])
    max_casters = overrides.get("max_caster_slots", settings["max_caster_slots"])
    max_player_slots = server_max - max_casters

    return {
        "name": name,
        "date": date,
        "time": time_str,
        "description": description,
        "server_max_players": server_max,
        "infantry_squad_size": overrides.get("infantry_squad_size", settings["infantry_squad_size"]),
        "vehicle_squad_size": overrides.get("vehicle_squad_size", settings["vehicle_squad_size"]),
        "heli_squad_size": overrides.get("heli_squad_size", settings["heli_squad_size"]),
        "max_player_slots": max_player_slots,
        "max_caster_slots": max_casters,
        "max_vehicle_squads": overrides.get("max_vehicle_squads", settings["max_vehicle_squads"]),
        "max_heli_squads": overrides.get("max_heli_squads", settings["max_heli_squads"]),
        "max_squads_per_user": overrides.get("max_squads_per_user", settings["max_squads_per_user"]),
        "player_slots_used": 0,
        "caster_slots_used": 0,
        "squads": {},
        "casters": {},
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
        "caster_waitlist": [],
        "registration_open": overrides.get("registration_open", False),
        "registration_start_time": overrides.get("registration_start_time", None),
        "is_closed": False,
        "event_message_id": None,
        "ping_role_ids": [],
        "squad_rep_role_ids": [],
        "squad_rep_user_ids": [],
        "community_rep_role_ids": [],
        "community_rep_user_ids": [],
        "caster_role_ids": [],
        "caster_user_ids": [],
        "caster_community_role_ids": [],
        "caster_community_user_ids": [],
        "streamer_role_ids": [],
        "streamer_user_ids": [],
        "embed_image_url": overrides.get("embed_image_url", None),
        "event_reminder_minutes": overrides.get("event_reminder_minutes", None),
        "event_reminder_sent": False,
        "countdown_seconds": overrides.get("countdown_seconds", None),
        "countdown_sent": False,
        "announcement_sent": False,
        "ping_on_open": overrides.get("ping_on_open", False),
        "ping_message_ids": [],
        "recurrence": overrides.get("recurrence", {"type": "never"}),
        "duration_minutes": overrides.get("duration_minutes", 120),
        "spawn_offset_minutes": overrides.get("spawn_offset_minutes", 5),
        "mode": overrides.get("mode", "rep"),
    }


# ---------------------------------------------------------------------------
# Convenience: clone an event dict for a recurrence follow-up
# ---------------------------------------------------------------------------

_CARRY_OVER_KEYS = (
    "name", "description",
    "server_max_players", "max_caster_slots",
    "max_vehicle_squads", "max_heli_squads",
    "infantry_squad_size", "vehicle_squad_size", "heli_squad_size",
    "max_squads_per_user",
    "event_reminder_minutes", "embed_image_url",
    "countdown_seconds", "ping_on_open",
    "ping_role_ids",
    "squad_rep_role_ids", "squad_rep_user_ids",
    "community_rep_role_ids", "community_rep_user_ids",
    "caster_role_ids", "caster_user_ids",
    "caster_community_role_ids", "caster_community_user_ids",
    "streamer_role_ids", "streamer_user_ids",
    "recurrence",
    "duration_minutes", "spawn_offset_minutes",
    "mode",
)


def clone_event_for_recurrence(old_event: dict, new_start: datetime) -> dict:
    """Build a fresh event dict for a recurrence follow-up.

    Carries config (name, slot sizes, role pings, recurrence rule, duration,
    spawn offset) from `old_event`, resets runtime state (squads, waitlists,
    slot counters, message ids, archival/spawn flags), and re-anchors date/time
    to `new_start`.
    """
    new_date = new_start.strftime("%d.%m.%Y")
    new_time = new_start.strftime("%H:%M")

    cloned = {key: old_event.get(key) for key in _CARRY_OVER_KEYS}

    # Lists need defensive copies so mutations on the new event don't leak back.
    for key, value in cloned.items():
        if isinstance(value, list):
            cloned[key] = list(value)
        elif isinstance(value, dict):
            cloned[key] = dict(value)

    max_player_slots = (cloned.get("server_max_players") or 0) - (cloned.get("max_caster_slots") or 0)

    cloned.update({
        "date": new_date,
        "time": new_time,
        "max_player_slots": max_player_slots,
        "player_slots_used": 0,
        "caster_slots_used": 0,
        "squads": {},
        "casters": {},
        "infantry_waitlist": [],
        "vehicle_waitlist": [],
        "heli_waitlist": [],
        "caster_waitlist": [],
        "is_closed": False,
        "event_message_id": None,
        "event_reminder_sent": False,
        "countdown_sent": False,
        "announcement_sent": False,
        "ping_message_ids": [],
    })

    # Registration start: preserve the delta from the original event start.
    orig_open = bool(old_event.get("registration_open"))
    orig_reg_start = old_event.get("registration_start_time")
    old_start_str = f"{old_event.get('date', '')} {old_event.get('time', '')}".strip()
    orig_event_dt = None
    try:
        orig_event_dt = datetime.strptime(old_start_str, "%d.%m.%Y %H:%M")
    except (ValueError, AttributeError):
        pass

    if orig_open and orig_reg_start is None:
        cloned["registration_open"] = True
        cloned["registration_start_time"] = None
    elif isinstance(orig_reg_start, datetime) and orig_event_dt:
        delta = orig_event_dt - orig_reg_start
        new_reg = new_start - delta
        if new_reg <= datetime.now():
            cloned["registration_open"] = True
            cloned["registration_start_time"] = None
        else:
            cloned["registration_open"] = False
            cloned["registration_start_time"] = new_reg
    else:
        cloned["registration_open"] = False
        cloned["registration_start_time"] = None

    return cloned
