#!/usr/bin/env python3
"""
Utility functions for the Event Registration Bot.

All formatting functions accept a ``lang`` parameter for i18n.
"""

import calendar
import hashlib
import io
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import Embed

from i18n import t
from config import ADMIN_IDS

logger = logging.getLogger("event_bot")

# ---------------------------------------------------------------------------
# Log channel — set per guild at runtime
# ---------------------------------------------------------------------------

# Map guild_id -> discord.TextChannel for log channels
_log_channels: dict[int, discord.TextChannel] = {}


def set_log_channel(guild_id: int, channel: discord.TextChannel):
    _log_channels[guild_id] = channel


def get_log_channel(guild_id: int) -> Optional[discord.TextChannel]:
    return _log_channels.get(guild_id)


async def send_to_log_channel(message: str, guild: discord.Guild = None,
                              guild_id: int = None, level: str = "INFO"):
    """Send a formatted message to the guild's log channel."""
    gid = guild_id or (guild.id if guild else None)
    if not gid:
        return False

    # Also log to file
    getattr(logger, level.lower(), logger.info)(message)

    channel = _log_channels.get(gid)
    if not channel:
        return False

    icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "🚨"}
    labels = {"INFO": "INFO", "WARNING": "WARNUNG", "ERROR": "FEHLER", "CRITICAL": "KRITISCH"}
    icon = icons.get(level, "ℹ️")
    label = labels.get(level, "INFO")
    formatted = f"{icon} **{label}**: {message}"

    try:
        await channel.send(formatted)
        return True
    except Exception as e:
        logger.error(f"Failed to send to log channel: {e}")
        return False


# ---------------------------------------------------------------------------
# Role / permission checks
# ---------------------------------------------------------------------------

def has_organizer_role(user, organizer_role_id: int) -> bool:
    """Check if user has the guild's organizer role or is a bot-level admin."""
    if hasattr(user, "id") and str(user.id) in ADMIN_IDS:
        return True
    if not hasattr(user, "roles"):
        return False
    if organizer_role_id == 0:
        return False
    return any(role.id == organizer_role_id for role in user.roles)


def has_role(user, role_id: int) -> bool:
    """Check if user has a specific role by ID."""
    if hasattr(user, "id") and str(user.id) in ADMIN_IDS:
        return True
    if not hasattr(user, "roles"):
        return False
    return any(role.id == role_id for role in user.roles)


def is_guild_admin(user) -> bool:
    """Check if user has Discord administrator permission or is bot-level admin."""
    if hasattr(user, "id") and str(user.id) in ADMIN_IDS:
        return True
    if hasattr(user, "guild_permissions"):
        return user.guild_permissions.administrator
    return False


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string in format DD.MM.YYYY."""
    try:
        return datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        return None


def compute_expiry_date(date_str: str, time_str: str = None) -> Optional[datetime]:
    """Compute event expiry: 24 hours after event start."""
    event_dt = parse_date(date_str)
    if not event_dt:
        return None
    if time_str:
        try:
            hours, minutes = map(int, time_str.split(":"))
            event_dt = event_dt.replace(hour=hours, minute=minutes)
        except (ValueError, AttributeError):
            pass
    return event_dt + timedelta(days=1)


# ---------------------------------------------------------------------------
# Player-mode registration helpers
# ---------------------------------------------------------------------------
_SQUAD_TYPES = ("infantry", "vehicle", "heli")
_SQUAD_TYPE_LABEL = {"infantry": "Infantry", "vehicle": "Vehicle", "heli": "Heli"}


def _waitlist_key(squad_type: str) -> str:
    return f"{squad_type}_waitlist"


def _squad_size_for_type(event: dict, squad_type: str) -> int:
    return {
        "infantry": event.get("infantry_squad_size", 6),
        "vehicle": event.get("vehicle_squad_size", 2),
        "heli":     event.get("heli_squad_size", 1),
    }.get(squad_type, 1)


def _max_squads_for_type(event: dict, squad_type: str) -> int:
    """Cap on how many squads of a given type can exist.

    Vehicle and heli are stored directly. Infantry is derived from the seat
    budget after vehicle/heli allocations.
    """
    if squad_type == "vehicle":
        return event.get("max_vehicle_squads", 0)
    if squad_type == "heli":
        return event.get("max_heli_squads", 0)
    seats = event.get("max_player_slots", 0)
    veh_slots = event.get("max_vehicle_squads", 0) * event.get("vehicle_squad_size", 0)
    heli_slots = event.get("max_heli_squads", 0) * event.get("heli_squad_size", 0)
    inf_size = max(1, event.get("infantry_squad_size", 6))
    return max(0, (seats - veh_slots - heli_slots) // inf_size)


def _next_auto_squad_name(event: dict, squad_type: str) -> str:
    label = _SQUAD_TYPE_LABEL.get(squad_type, squad_type.title())
    i = 1
    while f"{label} {i}" in event.get("squads", {}):
        i += 1
    return f"{label} {i}"


def _player_register(event: dict, user_assignments: dict, user_id, display_name: str,
                     squad_type: str) -> tuple:
    """Register a player into the first non-full squad of the type, creating a
    new squad if allowed, otherwise waitlisting them.

    Returns (squad_name_or_None, status). Status is one of:
    'registered', 'waitlisted', 'already_registered', 'invalid_type'.
    """
    if squad_type not in _SQUAD_TYPES:
        return None, "invalid_type"

    uid = str(user_id)
    if uid in user_assignments:
        return None, "already_registered"

    squads = event.setdefault("squads", {})

    for name, squad in squads.items():
        if squad.get("type") != squad_type:
            continue
        members = squad.setdefault("members", [])
        if len(members) < squad.get("size", 0):
            members.append({"user_id": uid, "name": display_name})
            user_assignments[uid] = [name]
            event["player_slots_used"] = event.get("player_slots_used", 0) + 1
            return name, "registered"

    existing_count = sum(1 for s in squads.values() if s.get("type") == squad_type)
    if existing_count < _max_squads_for_type(event, squad_type):
        new_name = _next_auto_squad_name(event, squad_type)
        squads[new_name] = {
            "type": squad_type,
            "size": _squad_size_for_type(event, squad_type),
            "id": generate_squad_id(new_name, squad_type),
            "members": [{"user_id": uid, "name": display_name}],
        }
        user_assignments[uid] = [new_name]
        event["player_slots_used"] = event.get("player_slots_used", 0) + 1
        return new_name, "registered"

    event.setdefault(_waitlist_key(squad_type), []).append(
        (display_name, squad_type, None, 1, uid, display_name))
    return None, "waitlisted"


def _compact_player_squads(event: dict, user_assignments: dict, squad_type: str):
    """Pull last-registered members from later squads into earlier partial
    squads of the same type. Drop trailing empty squads.
    """
    squads = event.get("squads", {})
    type_names = [n for n, s in squads.items() if s.get("type") == squad_type]

    for i, name in enumerate(type_names):
        squad = squads[name]
        size = squad.get("size", 0)
        members = squad.setdefault("members", [])
        while len(members) < size:
            source_name = None
            for later in reversed(type_names[i + 1:]):
                if squads[later].get("members"):
                    source_name = later
                    break
            if source_name is None:
                break
            member = squads[source_name]["members"].pop()
            members.append(member)
            uid = member.get("user_id")
            if uid:
                user_assignments[uid] = [name]

    for name in reversed(type_names):
        squad = squads.get(name)
        if squad is None:
            continue
        if not squad.get("members"):
            del squads[name]
        else:
            break


def _promote_player_waitlist(event: dict, user_assignments: dict, squad_type: str):
    """Pull entries off the waitlist and register them while capacity allows."""
    waitlist = event.get(_waitlist_key(squad_type), [])
    while waitlist:
        entry = waitlist[0]
        if not isinstance(entry, tuple) or len(entry) < 6:
            waitlist.pop(0)
            continue
        uid = entry[4]
        name = entry[5]
        _, status = _player_register(event, user_assignments, uid, name, squad_type)
        if status == "registered":
            waitlist.pop(0)
            continue
        break


def _player_unregister(event: dict, user_assignments: dict, user_id) -> tuple:
    """Remove a player, compact their squad-type, and promote from waitlist.

    Returns (success, squad_name_or_None).
    """
    uid = str(user_id)
    if uid not in user_assignments:
        return False, None

    squad_names = list(user_assignments.get(uid, []))
    user_assignments.pop(uid, None)
    if not squad_names:
        return False, None

    squad_name = squad_names[0]
    squad = event.get("squads", {}).get(squad_name)
    if not squad:
        return False, None

    squad_type = squad.get("type")
    before = len(squad.get("members", []))
    squad["members"] = [m for m in squad.get("members", []) if m.get("user_id") != uid]
    after = len(squad["members"])
    event["player_slots_used"] = max(0, event.get("player_slots_used", 0) - (before - after))

    if squad_type:
        _compact_player_squads(event, user_assignments, squad_type)
        _promote_player_waitlist(event, user_assignments, squad_type)

    return True, squad_name


def compute_event_start(event: dict) -> Optional[datetime]:
    """Parse an event dict's date + time into a naive datetime, or None."""
    date_str = event.get("date")
    time_str = event.get("time")
    if not date_str:
        return None
    try:
        if time_str:
            return datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        return datetime.strptime(date_str, "%d.%m.%Y")
    except (ValueError, AttributeError, TypeError):
        return None


def compute_event_end(event: dict, start: Optional[datetime] = None) -> Optional[datetime]:
    """Event end time: start + duration_minutes (default 120).

    Pass `start` if already computed to avoid a second strptime call.
    """
    if start is None:
        start = compute_event_start(event)
    if start is None:
        return None
    duration = event.get("duration_minutes", 120)
    if not isinstance(duration, int) or duration < 1:
        duration = 120
    return start + timedelta(minutes=duration)


def validate_recurrence_fits(start: datetime, end: datetime, recurrence: Optional[dict],
                             spawn_offset_minutes: int) -> tuple[bool, Optional[str]]:
    """Check whether a recurrence rule fits given the event's end + spawn offset.

    Returns (ok, reason_key). ok=True for non-recurring events. For recurring
    events, ok=True iff the next occurrence is strictly after end+spawn_offset.
    """
    if not recurrence or not isinstance(recurrence, dict) or recurrence.get("type") == "never":
        return True, None
    next_start = compute_next_occurrence(start, recurrence, now=start)
    if next_start is None:
        return False, "recurrence.error.no_next"
    spawn_at = end + timedelta(minutes=max(0, spawn_offset_minutes or 0))
    if next_start <= spawn_at:
        return False, "recurrence.error.next_before_spawn"
    return True, None


def parse_registration_start(value: str) -> Optional[datetime]:
    """Parse registration start time flexibly.

    Supports: DD.MM.YYYY HH:MM, DD.MM HH:MM, ISO 8601, 'sofort'/'now'.
    Returns datetime or None.
    """
    text = value.strip()
    if not text:
        return None

    # ISO 8601
    if len(text) >= 10 and text[4] == "-":
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    normalized = text.replace("/", ".").replace("-", ".")

    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    for fmt in ("%d.%m %H:%M", "%d.%m %H:%M:%S"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return dt.replace(year=datetime.now().year)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Event creation defaults
# ---------------------------------------------------------------------------

def compute_last_sunday(reference_date=None):
    """Compute the last Sunday of the current or next month.

    If the last Sunday of the current month has already passed,
    returns the last Sunday of the next month.
    """
    now = reference_date or datetime.now()
    year, month = now.year, now.month

    last_day = calendar.monthrange(year, month)[1]
    dt = datetime(year, month, last_day)
    days_since_sunday = (dt.weekday() + 1) % 7
    last_sunday = dt - timedelta(days=days_since_sunday)

    if last_sunday.date() >= now.date():
        return last_sunday

    # Advance to next month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime(year, month, last_day)
    days_since_sunday = (dt.weekday() + 1) % 7
    return dt - timedelta(days=days_since_sunday)



def _add_months(dt: datetime, n: int) -> datetime:
    """Return dt shifted by n months, capping day to the target month's length."""
    month_index = dt.month - 1 + n
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> Optional[datetime]:
    """Return the nth occurrence (1-based) of `weekday` (0=Mon..6=Sun) in year/month, or None."""
    first = datetime(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (n - 1) * 7
    last_day = calendar.monthrange(year, month)[1]
    if day > last_day:
        return None
    return first.replace(day=day)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> datetime:
    """Return the last occurrence of `weekday` in year/month."""
    last_day = calendar.monthrange(year, month)[1]
    last = datetime(year, month, last_day)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


_MAX_CATCHUP_ITERATIONS = 10_000


def _advance_once(current: datetime, rec: dict) -> Optional[datetime]:
    """Advance `current` by one step according to `rec`. Returns None if rule won't fire."""
    if not rec or not isinstance(rec, dict):
        return None
    rtype = rec.get("type", "never")

    if rtype == "never":
        return None

    if rtype in ("every_minutes", "every_hours", "every_days", "every_weeks"):
        n = rec.get("interval")
        if not isinstance(n, int) or n < 1:
            return None
        unit = rtype.removeprefix("every_")
        return current + timedelta(**{unit: n})

    if rtype == "every_month":
        return _add_months(current, 1)

    if rtype in ("first_weekday", "fourth_weekday", "last_weekday"):
        weekday = current.weekday()
        nxt = _add_months(current.replace(day=1), 1)
        if rtype == "first_weekday":
            target = _nth_weekday_of_month(nxt.year, nxt.month, weekday, 1)
        elif rtype == "fourth_weekday":
            target = _nth_weekday_of_month(nxt.year, nxt.month, weekday, 4)
        else:
            target = _last_weekday_of_month(nxt.year, nxt.month, weekday)
        if target is None:
            return None
        return target.replace(hour=current.hour, minute=current.minute)

    if rtype == "specific_date":
        date_str = rec.get("date")
        time_str = rec.get("time") or current.strftime("%H:%M")
        if not date_str:
            return None
        try:
            target = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        except (ValueError, AttributeError, TypeError):
            return None
        return target if target > current else None

    if rtype == "specific_weekdays":
        wanted = sorted(set(rec.get("weekdays", [])))
        if not wanted:
            return None
        for offset in range(1, 8):
            candidate = current + timedelta(days=offset)
            if candidate.weekday() in wanted:
                return candidate
        return None

    if rtype == "specific_month_days":
        wanted = sorted(set(rec.get("month_days", [])))
        if not wanted:
            return None
        candidate = current
        for _ in range(62):
            candidate = candidate + timedelta(days=1)
            if candidate.day in wanted:
                return candidate
        return None

    return None


_INTERVAL_UNIT_SECONDS = {
    "every_minutes": 60,
    "every_hours": 3600,
    "every_days": 86400,
    "every_weeks": 604800,
}


def compute_next_occurrence(current: datetime, rec: dict, now: Optional[datetime] = None) -> Optional[datetime]:
    """Compute the next event start after `current` per the recurrence rule.

    Anchors on `current` (not `now`) to avoid drift. For fixed-interval types
    (every_minutes/hours/days/weeks) we jump directly via math. For irregular
    types we advance in the rule's stride until the result is strictly after
    `now`. Returns None if the rule is 'never' or the data is malformed.
    """
    if not rec or not isinstance(rec, dict) or rec.get("type") == "never":
        return None
    now = now or datetime.now()
    rtype = rec.get("type")

    if rtype in _INTERVAL_UNIT_SECONDS:
        n = rec.get("interval")
        if not isinstance(n, int) or n < 1:
            return None
        stride = n * _INTERVAL_UNIT_SECONDS[rtype]
        delta_sec = (now - current).total_seconds()
        steps = int(delta_sec // stride) + 1 if delta_sec >= 0 else 1
        unit = rtype.removeprefix("every_")
        return current + timedelta(**{unit: n * steps})

    candidate = current
    for _ in range(_MAX_CATCHUP_ITERATIONS):
        nxt = _advance_once(candidate, rec)
        if nxt is None:
            return None
        if nxt > now:
            return nxt
        candidate = nxt
    logger.warning(f"compute_next_occurrence: catch-up loop cap hit for rec={rec}")
    return None


def compute_reg_start_15th(hour=15, minute=55, reference_date=None):
    """Compute the 15th of the current or next month at the given time.

    If the 15th at the specified time has already passed this month,
    returns the 15th of the next month.
    """
    now = reference_date or datetime.now()
    year, month = now.year, now.month

    candidate = datetime(year, month, 15, hour, minute)
    if candidate > now:
        return candidate

    # Advance to next month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return datetime(year, month, 15, hour, minute)


def resolve_event_defaults():
    """Resolve .env event defaults into concrete pre-fill strings.

    Returns dict with keys 'date', 'time', 'reg_start', each either
    a formatted string or empty string (no pre-fill).
    """
    from config import EVENT_DEFAULT_DATE, EVENT_DEFAULT_TIME, EVENT_DEFAULT_REG_START

    result = {"date": "", "time": "", "reg_start": ""}

    if EVENT_DEFAULT_DATE.lower() == "last_sunday":
        result["date"] = compute_last_sunday().strftime("%d.%m.%Y")
    elif EVENT_DEFAULT_DATE:
        result["date"] = EVENT_DEFAULT_DATE

    if EVENT_DEFAULT_TIME:
        result["time"] = EVENT_DEFAULT_TIME

    if EVENT_DEFAULT_REG_START:
        parsed = parse_registration_start(EVENT_DEFAULT_REG_START)
        if parsed:
            result["reg_start"] = parsed.strftime("%d.%m.%Y %H:%M")
        else:
            result["reg_start"] = EVENT_DEFAULT_REG_START

    return result


# ---------------------------------------------------------------------------
# Squad ID generation
# ---------------------------------------------------------------------------

def generate_squad_id(squad_name: str, current_squads: int) -> str:
    unique_base = f"{squad_name}_{current_squads}_{int(time.time())}"
    return hashlib.md5(unique_base.encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------
# Event summary (for log channel before deletion/expiry)
# ---------------------------------------------------------------------------

def build_event_summary_embed(event: dict, lang: str = "de") -> Embed:
    """Build a summary embed for a completed/expired/deleted event."""
    embed = Embed(
        title=t("event.summary_title", lang, name=event.get("name", "?")),
        color=discord.Color.orange(),
    )

    date_str = event.get("date", "?")
    time_str = event.get("time", "?")
    embed.add_field(name=t("event.summary_date", lang), value=f"{date_str} {time_str}", inline=True)

    squads = event.get("squads", {})
    total_wl = sum(len(event.get(f"{st}_waitlist", [])) for st in ("infantry", "vehicle", "heli"))
    embed.add_field(
        name=t("event.summary_squads", lang),
        value=f"{len(squads)} (+{total_wl} {t('embed.waitlist_label', lang, count=total_wl)})",
        inline=True,
    )

    casters = event.get("casters", {})
    caster_wl = event.get("caster_waitlist", [])
    embed.add_field(
        name=t("event.summary_casters", lang),
        value=f"{len(casters)} (+{len(caster_wl)})",
        inline=True,
    )

    used = event.get("player_slots_used", 0)
    max_slots = event.get("max_player_slots", 0)
    embed.add_field(
        name=t("event.summary_players", lang),
        value=t("event.summary_slots_used", lang, used=used, max=max_slots),
        inline=False,
    )

    # List squads
    if squads:
        lines = []
        for squad_id, data in squads.items():
            type_map = {"infantry": "Inf.", "vehicle": "Veh.", "heli": "Heli"}
            tl = type_map.get(data.get("type", ""), "?")
            rep = data.get("rep_name", "")
            rep_suffix = f" — {rep}" if rep else ""
            lines.append(f"[{data.get('playstyle', 'Normal')}] **{data.get('name', squad_id)}** ({tl}, {data.get('size', 0)}){rep_suffix}")
        embed.add_field(
            name=f"{t('embed.squads_label', lang)} ({len(squads)})",
            value="\n".join(lines[:25]) or "—",
            inline=False,
        )

    if casters:
        caster_lines = [f"**{d.get('name', '?')}**" for d in casters.values()]
        embed.add_field(
            name=f"{t('event.summary_casters', lang)} ({len(casters)})",
            value="\n".join(caster_lines[:10]) or "—",
            inline=False,
        )

    embed.set_footer(text=datetime.now().strftime("%d.%m.%Y %H:%M"))
    return embed


# ---------------------------------------------------------------------------
# Format event embed (main display)
# ---------------------------------------------------------------------------

def format_event_details(event: dict, lang: str = "de",
                         caster_enabled: bool = True) -> Embed | str:
    """Format event details as Discord embed."""
    if not event:
        return t("general.no_active_event", lang)

    if not event.get("name") or not event.get("date"):
        return t("general.no_active_event", lang)

    embed = Embed(
        title=t("embed.title", lang, name=event["name"]),
        description=event.get("description") or None,
        color=discord.Color.blue(),
    )

    # Event start (Discord timestamp)
    event_date_str = event["date"]
    event_time_str = event.get("time", "20:00")
    try:
        event_dt = datetime.strptime(f"{event_date_str} {event_time_str}", "%d.%m.%Y %H:%M")
        event_ts = int(event_dt.timestamp())
        embed.add_field(name=t("embed.event_start", lang), value=f"<t:{event_ts}:f>\n<t:{event_ts}:R>", inline=True)
    except ValueError:
        embed.add_field(name=t("embed.event_start", lang), value=f"{event_date_str} {event_time_str}", inline=True)

    # Registration status
    reg_open = event.get("registration_open", False)
    is_closed = event.get("is_closed", False)
    if is_closed:
        reg_status = t("reg.closed", lang)
    elif reg_open:
        reg_status = t("reg.open", lang)
    else:
        start_time = event.get("registration_start_time")
        if start_time and isinstance(start_time, datetime):
            ts = int(start_time.timestamp())
            reg_status = t("reg.opens_at", lang, ts=ts)
        else:
            reg_status = t("reg.not_open_yet", lang)
    embed.add_field(name=t("embed.registration", lang), value=reg_status, inline=True)

    # Reminder
    reminder_minutes = event.get("event_reminder_minutes")
    if reminder_minutes:
        if event.get("event_reminder_sent", False):
            embed.add_field(name=t("embed.reminder", lang),
                            value=t("embed.reminder_sent", lang, minutes=reminder_minutes), inline=True)
        else:
            embed.add_field(name=t("embed.reminder", lang),
                            value=t("embed.reminder_value", lang, minutes=reminder_minutes), inline=True)

    # Slot overview
    server_cap = event.get("server_max_players", 100)
    inf_size = event.get("infantry_squad_size", 6)
    veh_size = event.get("vehicle_squad_size", 2)
    heli_size = event.get("heli_squad_size", 1)
    max_vehicles = event.get("max_vehicle_squads", 6)
    max_helis = event.get("max_heli_squads", 2)
    max_casters = event.get("max_caster_slots", 2)
    max_squads_user = event.get("max_squads_per_user", 1)

    player_used = event.get("player_slots_used", 0)
    caster_used = event.get("caster_slots_used", 0) if caster_enabled else 0
    total_used = player_used + caster_used
    available = server_cap - total_used

    squads_all = event.get("squads", {})
    vehicle_count = sum(1 for d in squads_all.values() if d.get("type") == "vehicle")
    heli_count = sum(1 for d in squads_all.values() if d.get("type") == "heli")
    infantry_count = sum(1 for d in squads_all.values() if d.get("type") == "infantry")

    vehicle_player_slots = max_vehicles * veh_size
    heli_player_slots = max_helis * heli_size
    infantry_player_slots = max(0, server_cap - max_casters - vehicle_player_slots - heli_player_slots)
    max_inf_squads = infantry_player_slots // inf_size if inf_size > 0 else 0
    unused = server_cap - max_casters - (max_inf_squads * inf_size) - vehicle_player_slots - heli_player_slots

    is_player_mode = event.get("mode") == "player"

    # Slot overview — compact inline grid (row 1: server, caster, max/player)
    overview_name_key = "embed.seats_overview" if is_player_mode else "embed.server_overview"
    embed.add_field(
        name=t(overview_name_key, lang),
        value=t("embed.server_overview_value", lang, cap=server_cap, free=available, unused=unused),
        inline=True)
    if not is_player_mode:
        embed.add_field(name=t("embed.max_per_user_label", lang, count=max_squads_user), value="\u200b", inline=True)

    # Squad type fields — each type always shown with count/max
    squads = event.get("squads", {})
    infantry_squads = {n: d for n, d in squads.items() if d.get("type") == "infantry"}
    vehicle_squads = {n: d for n, d in squads.items() if d.get("type") == "vehicle"}
    heli_squads = {n: d for n, d in squads.items() if d.get("type") == "heli"}

    for squad_group, type_key, count, max_count, size in [
        (infantry_squads, "infantry", infantry_count, max_inf_squads, inf_size),
        (vehicle_squads, "vehicle", vehicle_count, max_vehicles, veh_size),
        (heli_squads, "heli", heli_count, max_helis, heli_size),
    ]:
        size_label = "Größe" if lang == "de" else "Size"
        name = t("embed.type_" + type_key, lang) + f" ({count}/{max_count}) [{size_label}: {size}]"
        if squad_group:
            text = ""
            for squad_id, data in squad_group.items():
                if is_player_mode:
                    members = data.get("members", [])
                    filled = len(members)
                    names = ", ".join(m.get("name", "?") for m in members) or "—"
                    text += f"**{data.get('name', squad_id)}** ({filled}/{data.get('size', 0)}): {names}\n"
                else:
                    playstyle = data.get("playstyle", "Normal")
                    sq_size = data.get("size", 0)
                    rep = data.get("rep_name")
                    rep_suffix = f" — {rep}" if rep else ""
                    text += f"[{playstyle}] **{data.get('name', squad_id)}** ({sq_size}){rep_suffix}\n"
            embed.add_field(name=name, value=text, inline=False)
        else:
            embed.add_field(name=name, value=t("embed.no_entries", lang), inline=False)

        # Type waitlist — directly below its registered entries
        wl = event.get(f"{type_key}_waitlist", [])
        if wl:
            wl_text = ""
            for i, entry in enumerate(wl):
                if is_player_mode:
                    # (display_name, type, None, 1, user_id, display_name)
                    player_name = entry[5] if len(entry) > 5 else entry[0]
                    wl_text += f"{i+1}. **{player_name}**\n"
                else:
                    squad_name, _squad_type, playstyle, sq_size, _squad_id, *_rest = entry
                    rep_name = _rest[0] if _rest else None
                    rep_suffix = f" — {rep_name}" if rep_name else ""
                    wl_text += f"{i+1}. [{playstyle}] **{squad_name}** ({sq_size}){rep_suffix}\n"
            embed.add_field(
                name=t("embed.type_waitlist_label", lang, type=t(f"embed.type_{type_key}", lang), count=len(wl)),
                value=wl_text, inline=False)

    # Caster field — always shown when enabled and mode allows casters
    if is_player_mode:
        caster_enabled = False
    if caster_enabled:
        casters = event.get("casters", {})
        caster_used = event.get("caster_slots_used", 0)
        name = t("embed.caster_overview_compact", lang, count=caster_used, max=max_casters)
        if casters:
            caster_text = "\n".join(f"**{d.get('name', '?')}**" for d in casters.values())
            embed.add_field(name=name, value=caster_text, inline=False)
        else:
            embed.add_field(name=name, value=t("embed.no_entries", lang), inline=False)

        # Caster waitlist — directly below caster entries
        caster_wl = event.get("caster_waitlist", [])
        if caster_wl:
            cwl_text = "\n".join(f"{i+1}. **{name}**" for i, (_, name) in enumerate(caster_wl))
            embed.add_field(name=t("embed.caster_waitlist_label", lang, count=len(caster_wl)), value=cwl_text, inline=False)

    # Image
    embed_image_url = event.get("embed_image_url")
    if embed_image_url:
        embed.set_image(url=embed_image_url)

    embed.set_footer(text=t("embed.footer", lang))
    return embed


# ---------------------------------------------------------------------------
# Log file management
# ---------------------------------------------------------------------------

LOG_FILE_PATH = "discord_bot.log"
LOG_BACKUP_FOLDER = "log_backups"


def export_log_file() -> Optional[dict]:
    try:
        if not os.path.exists(LOG_FILE_PATH):
            return None
        buf = io.BytesIO()
        with open(LOG_FILE_PATH, "rb") as f:
            buf.write(f.read())
        buf.seek(0)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return {"buffer": buf, "filename": f"log_export_{ts}.log"}
    except Exception as e:
        logger.error(f"Error exporting log: {e}")
        return None


def clear_log_file() -> bool:
    try:
        if not os.path.exists(LOG_FILE_PATH):
            return False
        os.makedirs(LOG_BACKUP_FOLDER, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        shutil.copy2(LOG_FILE_PATH, f"{LOG_BACKUP_FOLDER}/log_backup_{ts}.log")
        with open(LOG_FILE_PATH, "w") as f:
            f.write(f"--- Log reset: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        return True
    except Exception as e:
        logger.error(f"Error clearing log: {e}")
        return False
