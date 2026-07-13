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
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import Embed

from i18n import t
from config import ADMIN_IDS, EVENT_TIMEZONE

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
    """Check if user has a specific role by ID.

    Literal role membership — bot-level admins (ADMIN_IDS) are NOT bypassed here,
    so they're subject to the registration role gate like everyone else. Admin
    powers come from has_organizer_role / is_guild_admin instead.
    """
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


# ---------------------------------------------------------------------------
# Player-mode registration helpers
# ---------------------------------------------------------------------------
_SQUAD_TYPES = ("infantry", "vehicle", "heli")
_SQUAD_TYPE_LABEL = {"infantry": "Infantry", "vehicle": "Vehicle", "heli": "Heli"}

# Per-role display translations. Stored role values are English; the dropdown
# label and the embed parenthetical render the localized form. Roles missing
# from this map fall back to the raw English value (matching the playstyle
# convention).
_ROLE_LABEL_TRANSLATIONS = {
    "Logi driver": {"de": "Logi-Fahrer"},
    "Mortar":      {"de": "Mörser"},
}


def role_label(role, lang):
    """Return the localized display label for a stored role value. Returns
    None if `role` is falsy. Falls back to the English value when no
    translation exists for `lang`."""
    if not role:
        return None
    return _ROLE_LABEL_TRANSLATIONS.get(role, {}).get(lang, role)


def _get_member_roles(member: dict) -> list:
    """Return a list of role values for a member, supporting both the new
    `roles` (list) and the legacy `role` (string) schemas."""
    roles = member.get("roles")
    if isinstance(roles, list):
        return roles
    single = member.get("role")
    return [single] if single else []


def _squad_has_sl(squad) -> bool:
    """True if any member of the squad holds the "Squad Leader" role."""
    return any("Squad Leader" in _get_member_roles(m) for m in squad.get("members", []))


def _format_role_suffix(roles, lang) -> str:
    """Render a player's roles as a parenthetical suffix, or "" when none.

    Returns the COMPLETE suffix including the surrounding parentheses (" (a, b)")
    so callers append it directly to a name — a role-less player gets no empty
    "()" tail and no "(Egal)" placeholder.
    """
    labels = [role_label(r, lang) for r in (roles or []) if r]
    return f" ({', '.join(labels)})" if labels else ""


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
    # The infantry cap is always even so both teams get the same squad count.
    return _even_infantry_max(max(0, (seats - veh_slots - heli_slots) // inf_size))


def _even_infantry_max(raw_max: int) -> int:
    """Round an infantry squad cap down to an even count so both teams get the
    same number of squads. Caps below 2 are left alone so tiny configs stay
    usable."""
    return raw_max if raw_max < 2 else raw_max - raw_max % 2


def infantry_unused_pool(event: dict) -> int:
    """Seats the don't-waste mode can hand out as oversized squads: the seat
    remainder plus — when the base squad count would be odd — one whole base
    squad, because the infantry squad count must stay even (two equal teams)."""
    inf_size = event.get("infantry_squad_size", 6)
    if inf_size <= 0:
        return 0
    veh_slots = event.get("max_vehicle_squads", 0) * event.get("vehicle_squad_size", 0)
    heli_slots = event.get("max_heli_squads", 0) * event.get("heli_squad_size", 0)
    inf_slots = max(0, event.get("max_player_slots", 0) - veh_slots - heli_slots)
    return inf_slots - _even_infantry_max(inf_slots // inf_size) * inf_size


MAX_SQUAD_PLAYERS = 9  # hard in-game limit — no squad can hold more players


def dont_waste_slots_possible(event: dict) -> bool:
    """True when the don't-waste-slots mode could do anything at all: a base
    size below the in-game squad limit and a pool that fits at least one
    oversized pair. Applies to both modes — reps pick oversized sizes
    themselves, player mode pre-plans squad capacities."""
    return (event.get("infantry_squad_size", 6) < MAX_SQUAD_PLAYERS
            and infantry_unused_pool(event) >= 2)


def dont_waste_slots_active(event: dict) -> bool:
    """True when the mode is enabled and can actually do anything."""
    return bool(event.get("dont_waste_slots")) and dont_waste_slots_possible(event)


def _allowed_extras(event: dict, free_pool: int) -> list:
    """Extra-seat values of the oversized sizes the organizer allows and whose
    pair still fits `free_pool`."""
    base = event.get("infantry_squad_size", 6)
    allowed = event.get("dont_waste_allowed_sizes")
    return [k - base
            for k in range(base + 1, min(base + free_pool // 2, MAX_SQUAD_PLAYERS) + 1)
            if not (allowed and k not in allowed)]


def _max_pairs(event: dict, counts: dict | None = None):
    """Remaining pair budget from the organizer's oversized-squad cap
    (`dont_waste_max_squads`), or None when unlimited. With `counts`
    (registered oversized squads per size, rep mode) an incomplete pair counts
    as 2 — its mirror is reserved and completing it must never be blocked."""
    cap = event.get("dont_waste_max_squads")
    if not cap:
        return None
    used = sum(c + (c % 2) for c in (counts or {}).values())
    return max(0, cap // 2 - used // 2)


def _pair_plan(free_pool: int, extras: list, max_pairs: int | None = None) -> dict:
    """Canonical plan for absorbing the remaining pool with oversized pairs:
    least wasted seats first, then the fewest oversized squads, preferring
    bigger squads on ties, using at most `max_pairs` pairs (None = unlimited).
    Returns {extra_seats_per_squad: number_of_pairs}."""
    coins = sorted({2 * e for e in extras if e > 0}, reverse=True)
    if free_pool < 2 or not coins or max_pairs == 0:
        return {}
    reach = {0: {}}  # exactly-absorbed seats -> pair multiset {coin: n}
    for total in range(2, free_pool + 1):
        best = None
        for coin in coins:
            prev = reach.get(total - coin)
            if prev is None:
                continue
            if best is None or sum(prev.values()) + 1 < sum(best.values()):
                best = dict(prev)
                best[coin] = best.get(coin, 0) + 1
        # The DP minimizes pairs per total, so a total whose minimum exceeds
        # the cap is unreachable within it (any larger total needs even more).
        if best is not None and (max_pairs is None or sum(best.values()) <= max_pairs):
            reach[total] = best
    return {coin // 2: n for coin, n in reach[max(reach)].items()}


def _pair_cover(target: int, extras: list, max_pairs: int | None = None) -> dict:
    """Minimal set of oversized pairs whose extra seats cover AT LEAST
    `target`: fewest pairs first, then least excess capacity, bigger squads
    preferred, using at most `max_pairs` pairs. Returns {extra: n_pairs}
    ({} when target <= 0, nothing fits, or the cap prevents covering)."""
    coins = sorted({2 * e for e in extras if e > 0}, reverse=True)
    if target <= 0 or not coins or max_pairs == 0:
        return {}
    reach = {0: {}}
    for total in range(2, target + max(coins) + 1):
        cand = None
        for coin in coins:
            prev = reach.get(total - coin)
            if prev is None:
                continue
            if cand is None or sum(prev.values()) + 1 < sum(cand.values()):
                cand = dict(prev)
                cand[coin] = cand.get(coin, 0) + 1
        if cand is not None and (max_pairs is None or sum(cand.values()) <= max_pairs):
            reach[total] = cand
    best = None
    for total, combo in reach.items():
        if total < target:
            continue
        key = (sum(combo.values()), total)
        if best is None or key < best[0]:
            best = (key, combo)
    return {coin // 2: n for coin, n in best[1].items()} if best else {}


def planned_infantry_capacities(event: dict) -> list:
    """Deterministic capacity layout for player-mode infantry squads: base
    squads first, the minimal-plan oversized pairs last (biggest at the end),
    so regular squads fill up before any oversized capacity is used."""
    base = event.get("infantry_squad_size", 6)
    cap = _max_squads_for_type(event, "infantry")
    if not dont_waste_slots_active(event):
        return [base] * cap
    pool = infantry_unused_pool(event)
    plan = _pair_plan(pool, _allowed_extras(event, pool), _max_pairs(event))
    oversized = sorted(base + extra
                       for extra, pairs in plan.items()
                       for _ in range(2 * pairs))
    if len(oversized) > cap:
        # Tiny caps (exempt from the even rule) can't hold a full pair.
        return [base] * cap
    return [base] * (cap - len(oversized)) + oversized


def infantry_size_options(event: dict) -> list:
    """Infantry squad sizes currently offerable, as [(size, remaining), ...]
    ascending with the base size always first.

    With "don't waste slots" mode off (or in player mode) only the base size is
    returned. When on, the unused pool may be absorbed by oversized squads that
    must always come in equal numbers per size (mirrored across two manually
    split teams): the first oversized registration locks its size until all
    oversized squads are gone, an incomplete pair keeps its size offered and
    reserves one squad slot for the mirror, and a pool remainder that cannot
    form a pair stays unused.
    """
    base = event.get("infantry_squad_size", 6)
    base_max = _max_squads_for_type(event, "infantry")
    inf_squads = [d for d in event.get("squads", {}).values()
                  if d.get("type") == "infantry"]
    free_slots = max(0, base_max - len(inf_squads))

    pool = infantry_unused_pool(event)
    active = event.get("mode", "rep") != "player" and bool(event.get("dont_waste_slots"))
    if not active:
        return [(base, free_slots)]

    counts: dict[int, int] = {}
    for d in inf_squads:
        size = d.get("size", base)
        if size > base:
            counts[size] = counts.get(size, 0) + 1

    if not counts and pool < 2:
        return [(base, free_slots)]

    pending = sum(1 for c in counts.values() if c % 2)
    consumed = sum((size - base) * c for size, c in counts.items())
    reserved = sum(size - base for size, c in counts.items() if c % 2)
    free_pool = max(0, pool - consumed - reserved)
    options = [(base, max(0, free_slots - pending))]

    # Offered are the pairs of the canonical plan (least waste, then fewest
    # oversized squads — so as many regular squads as possible), plus mirrors
    # of incomplete pairs. The organizer may additionally whitelist sizes.
    plan = _pair_plan(free_pool, _allowed_extras(event, free_pool),
                      _max_pairs(event, counts))
    candidates = set(counts) | {base + e for e in plan}
    for size in sorted(candidates):
        c = counts.get(size, 0)
        extra = size - base
        others_pending = pending - (1 if c % 2 else 0)
        avail = max(0, free_slots - others_pending)
        if c % 2:
            # Incomplete pair: the mirror stays registerable (even if a config
            # edit shrank the pool or excluded the size — equal counts win);
            # anything beyond it only per plan.
            if avail < 1:
                remaining = 0
            else:
                remaining = 1 + 2 * min(plan.get(extra, 0), (avail - 1) // 2)
        else:
            remaining = 2 * min(plan.get(extra, 0), avail // 2)
        if remaining > 0:
            options.append((size, remaining))
    return options


def infantry_wasted_seats(event: dict) -> int:
    """Pool seats that can no longer be absorbed by oversized squads: the
    leftover once no oversized size is offerable anymore (0 while any option —
    including a pending mirror — is still open). In player mode the bot plans
    capacities itself, so the waste is simply the plan's static residual."""
    base = event.get("infantry_squad_size", 6)
    pool = infantry_unused_pool(event)
    if event.get("mode", "rep") == "player":
        # Player mode plans the whole layout, so the plan absorption is the
        # full picture — the residual (incl. any cap-stranded seats) is waste.
        plan = _pair_plan(pool, _allowed_extras(event, pool), _max_pairs(event))
        return max(0, pool - sum(2 * extra * n for extra, n in plan.items()))
    counts: dict[int, int] = {}
    for d in event.get("squads", {}).values():
        size = d.get("size", base)
        if d.get("type") == "infantry" and size > base:
            counts[size] = counts.get(size, 0) + 1
    consumed = sum((size - base) * c for size, c in counts.items())
    if any(size != base for size, _ in infantry_size_options(event)):
        # Optimistic while options are open: only seats no further pair can
        # absorb (cap/whitelist-stranded, given what's already registered) are
        # wasted. Reserved mirror seats of incomplete pairs will be filled, so
        # they leave the free pool and don't count as waste.
        reserved = sum(size - base for size, c in counts.items() if c % 2)
        free_pool = max(0, pool - consumed - reserved)
        plan = _pair_plan(free_pool, _allowed_extras(event, free_pool),
                          _max_pairs(event, counts))
        return max(0, free_pool - sum(2 * extra * n for extra, n in plan.items()))
    return max(0, pool - consumed)


def _next_auto_squad_name(event: dict, squad_type: str) -> str:
    label = _SQUAD_TYPE_LABEL.get(squad_type, squad_type.title())
    i = 1
    while f"{label} {i}" in event.get("squads", {}):
        i += 1
    return f"{label} {i}"


def _try_place_player(event: dict, user_assignments: dict, uid: str,
                      display_name: str, squad_type: str,
                      roles: Optional[list] = None) -> Optional[str]:
    """Place the player into the first non-full squad of the given type, or
    create a new squad if under the cap. Returns the squad name on success,
    or None if there's no capacity (caller decides whether to waitlist).

    No waitlist side effects — safe to call from the waitlist promoter.

    When `roles` contains "Squad Leader", the player is routed into a squad
    without an existing SL, or into a freshly-created squad when the cap
    allows. Only when the squad cap is reached does a second SL share a
    squad with another one.
    """
    squads = event.setdefault("squads", {})
    roles = list(roles or [])
    is_sl = "Squad Leader" in roles

    def _add_member(name, squad):
        members = squad.setdefault("members", [])
        entry = {"user_id": uid, "name": display_name}
        if roles:
            entry["roles"] = list(roles)
        members.append(entry)
        user_assignments[uid] = [name]
        event["player_slots_used"] = event.get("player_slots_used", 0) + 1
        return name

    for name, squad in squads.items():
        if squad.get("type") != squad_type:
            continue
        if len(squad.setdefault("members", [])) >= squad.get("size", 0):
            continue
        if is_sl and _squad_has_sl(squad):
            continue
        return _add_member(name, squad)

    existing_count = sum(1 for s in squads.values() if s.get("type") == squad_type)
    if existing_count < _max_squads_for_type(event, squad_type):
        size = _squad_size_for_type(event, squad_type)
        if squad_type == "infantry":
            # Don't-waste mode: the Nth squad's capacity comes from the
            # pre-planned layout (base squads first, oversized pairs last).
            layout = planned_infantry_capacities(event)
            if existing_count < len(layout):
                size = layout[existing_count]
        new_name = _next_auto_squad_name(event, squad_type)
        squads[new_name] = {
            "type": squad_type,
            "size": size,
            "id": generate_squad_id(new_name, squad_type),
            "members": [],
        }
        return _add_member(new_name, squads[new_name])

    if is_sl:
        for name, squad in squads.items():
            if squad.get("type") != squad_type:
                continue
            if len(squad.get("members", [])) >= squad.get("size", 0):
                continue
            return _add_member(name, squad)

    return None


def _player_register(event: dict, user_assignments: dict, user_id, display_name: str,
                     squad_type: str, roles: Optional[list] = None) -> tuple:
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

    # Ending up with a seat or waitlist spot supersedes any "declined" mark.
    _remove_declined(event, uid)

    placed = _try_place_player(event, user_assignments, uid, display_name, squad_type, roles)
    if placed is not None:
        return placed, "registered"

    event.setdefault(_waitlist_key(squad_type), []).append(
        (display_name, squad_type, None, 1, uid, display_name, list(roles or [])))
    return None, "waitlisted"


def _squad_number_key(name: str):
    """Sort key for auto-named squads ("Infantry 1", "Infantry 2", ...) by their
    numeric suffix. Names without a numeric suffix sort last, deterministically.
    """
    tail = name.rsplit(" ", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, 0)


def _replan_player_capacities(event: dict, squads: dict, type_names: list) -> list:
    """Re-derive the infantry capacity layout from the ACTUAL player count:
    as many base squads as possible plus the minimal oversized pairs for the
    overflow. Returns members shed from squads whose capacity shrank — the
    caller re-seats them after compaction (total capacity covers everyone)."""
    base = event.get("infantry_squad_size", 6)
    players = sum(len(squads[n].get("members", [])) for n in type_names)
    n_exist = len(type_names)
    overflow = max(0, players - n_exist * base)
    cover = _pair_cover(overflow, _allowed_extras(event, infantry_unused_pool(event)),
                        _max_pairs(event))
    oversized = sorted(base + extra
                       for extra, pairs in cover.items()
                       for _ in range(2 * pairs))
    if len(oversized) > n_exist:
        return []
    assigned = [base] * (n_exist - len(oversized)) + oversized
    if sum(assigned) < players:
        return []  # degenerate (whitelist/config drift): keep current capacities
    displaced = []
    for name, size in zip(type_names, assigned):
        squad = squads[name]
        squad["size"] = size
        members = squad.setdefault("members", [])
        while len(members) > size:
            displaced.append(members.pop())
    return displaced


def _compact_player_squads(event: dict, user_assignments: dict, squad_type: str,
                           replan: bool = False):
    """Pull last-registered members from later squads into earlier partial
    squads of the same type. Drop trailing empty squads.

    Squads are processed in numeric order (Infantry 1, 2, 3, ...) rather than
    dict-insertion order, so consolidation deterministically keeps the
    lowest-numbered squads regardless of how the dict was built.

    `replan` re-derives don't-waste capacities from the actual player count —
    only the real consolidation (event start / admin button) does that; the
    per-unregister compaction must NOT shrink capacities, or later
    registrations could no longer grow back into the planned layout.
    """
    squads = event.get("squads", {})
    type_names = sorted(
        (n for n, s in squads.items() if s.get("type") == squad_type),
        key=_squad_number_key)

    displaced = []
    if replan and squad_type == "infantry" and dont_waste_slots_active(event):
        displaced = _replan_player_capacities(event, squads, type_names)

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

    # Members shed by a capacity replan get the remaining gaps.
    for member in displaced:
        for name in type_names:
            squad = squads[name]
            if len(squad.setdefault("members", [])) < squad.get("size", 0):
                squad["members"].append(member)
                uid = member.get("user_id")
                if uid:
                    user_assignments[uid] = [name]
                break

    for name in reversed(type_names):
        squad = squads.get(name)
        if squad is None:
            continue
        if not squad.get("members"):
            del squads[name]
        else:
            break


def consolidate_all_player_squads(event: dict, user_assignments: dict) -> int:
    """Compact every player-mode squad type: pack members into the fewest
    squads of each type and drop emptied ones. Reuses `_compact_player_squads`,
    which also keeps `user_assignments` in sync for moved members.

    Returns the number of squads removed (0 ⇒ already compact / nothing to do).
    Idempotent: a second call on a compact layout is a no-op returning 0.
    """
    squads = event.get("squads", {})
    before = len(squads)
    for squad_type in _SQUAD_TYPES:
        _compact_player_squads(event, user_assignments, squad_type, replan=True)
    return before - len(event.get("squads", {}))


def _promote_player_waitlist(event: dict, user_assignments: dict, squad_type: str) -> list:
    """Pull entries off the waitlist and place them into squads while capacity
    allows. Uses the side-effect-free placement helper so failed placements
    don't re-queue the entry (which would duplicate it).

    Returns a list of (uid, display_name, squad_name) for every player that
    was promoted, so the async caller can DM them and log to the log channel.
    """
    promoted: list = []
    waitlist = event.get(_waitlist_key(squad_type), [])
    while waitlist:
        entry = waitlist[0]
        if not isinstance(entry, (tuple, list)) or len(entry) < 6:
            waitlist.pop(0)
            continue
        uid = str(entry[4])
        name = entry[5]
        role_data = entry[6] if len(entry) > 6 else None
        if isinstance(role_data, list):
            roles = role_data
        elif isinstance(role_data, str) and role_data:
            roles = [role_data]
        else:
            roles = []
        if uid in user_assignments:
            # Stale waitlist entry for someone already placed — drop and keep going.
            waitlist.pop(0)
            continue
        placed = _try_place_player(event, user_assignments, uid, name, squad_type, roles)
        if placed is None:
            break
        waitlist.pop(0)
        promoted.append((uid, name, placed))
    return promoted


def _player_remove_from_waitlist(event: dict, user_id) -> Optional[str]:
    """Remove a user's waitlist entry across all per-type waitlists.
    Returns the squad_type that held them, or None if no entry found.

    Useful for admin-removing a waitlisted player (who isn't in user_assignments).
    """
    uid = str(user_id)
    for st in _SQUAD_TYPES:
        wl = event.get(_waitlist_key(st), [])
        for i, entry in enumerate(wl):
            if not isinstance(entry, (tuple, list)) or len(entry) <= 4:
                continue
            if str(entry[4]) == uid:
                wl.pop(i)
                return st
    return None


def _player_unregister(event: dict, user_assignments: dict, user_id) -> tuple:
    """Remove a player, compact their squad-type, and promote from waitlist.

    Returns (success, squad_name_or_None, promoted_list) where promoted_list is
    [(uid, display_name, squad_name), ...] for any players that moved off the
    waitlist into a squad as a result of this unregister. Callers use the list
    to DM those users and log their promotion.
    """
    uid = str(user_id)
    if uid not in user_assignments:
        return False, None, []

    squad_names = list(user_assignments.get(uid, []))
    user_assignments.pop(uid, None)
    if not squad_names:
        return False, None, []

    squad_name = squad_names[0]
    squad = event.get("squads", {}).get(squad_name)
    if not squad:
        return False, None, []

    squad_type = squad.get("type")
    before = len(squad.get("members", []))
    squad["members"] = [m for m in squad.get("members", []) if m.get("user_id") != uid]
    after = len(squad["members"])
    event["player_slots_used"] = max(0, event.get("player_slots_used", 0) - (before - after))

    promoted: list = []
    if squad_type:
        _compact_player_squads(event, user_assignments, squad_type)
        promoted = _promote_player_waitlist(event, user_assignments, squad_type)

    _rebalance_squad_leaders(event, user_assignments)
    return True, squad_name, promoted


def _rebalance_squad_leaders(event: dict, user_assignments: dict) -> list:
    """Move a spare Squad Leader into any infantry squad left without one.

    For each infantry squad with 0 SLs, pull one SL from a squad that has a
    surplus (2+). If the receiver is full, one of its non-SL members swaps back
    into the donor (which just freed a seat) so both stay within `size`. Squads
    with no spare SL available are left leaderless — the embed flags them with ⚠️.

    Returns [(uid, name, target_squad), ...] for each moved leader (for logging).
    ponytail: infantry-only — "Squad Leader" is an infantry-only role (ROLES_BY_TYPE).
    """
    squads = event.get("squads", {})
    inf = [(n, s) for n, s in squads.items() if s.get("type") == "infantry"]
    moved: list = []
    for name, squad in inf:
        if _squad_has_sl(squad):
            continue
        donor_name = donor = sl = None
        for dn, ds in inf:
            if dn == name:
                continue
            sls = [m for m in ds.get("members", []) if "Squad Leader" in _get_member_roles(m)]
            if len(sls) >= 2:
                donor_name, donor, sl = dn, ds, sls[-1]
                break
        if sl is None:
            continue  # no spare SL anywhere → leave leaderless (embed warns)
        donor["members"].remove(sl)
        members = squad.setdefault("members", [])
        if len(members) >= squad.get("size", 0):  # receiver full → swap a non-SL out
            spare = next((m for m in members
                          if "Squad Leader" not in _get_member_roles(m)), None)
            if spare is not None:
                members.remove(spare)
                donor.setdefault("members", []).append(spare)
                if spare.get("user_id"):
                    user_assignments[spare["user_id"]] = [donor_name]
        members.append(sl)
        if sl.get("user_id"):
            user_assignments[sl["user_id"]] = [name]
        moved.append((sl.get("user_id"), sl.get("name"), name))
    return moved


def _player_waitlist_type(event: dict, user_id) -> Optional[str]:
    """Return the squad_type a user is currently waitlisted under, or None.

    Non-destructive lookup mirroring _player_remove_from_waitlist's matching —
    used to decide whether a waitlisted player may open the self-unregister
    confirmation dialog.
    """
    uid = str(user_id)
    for st in _SQUAD_TYPES:
        for entry in event.get(_waitlist_key(st), []):
            if isinstance(entry, (tuple, list)) and len(entry) > 4 and str(entry[4]) == uid:
                return st
    return None


# ---------------------------------------------------------------------------
# Player-mode "tentative" (Vorläufig) sign-ups
# ---------------------------------------------------------------------------
# A tentative player signals "maybe" — they pick a squad type (+ optional role)
# but occupy NO real squad seat. Stored in event["tentative"] as dicts mirroring
# the member schema plus a "type": {"user_id","name","type","roles":[...]}.
# Mutually exclusive with a firm seat / waitlist spot (enforced by the callers).


def _player_tentative_entry(event: dict, user_id) -> Optional[dict]:
    """Return the user's tentative entry, or None. Non-destructive."""
    uid = str(user_id)
    for entry in event.get("tentative", []):
        if str(entry.get("user_id")) == uid:
            return entry
    return None


def _player_tentative_type(event: dict, user_id) -> Optional[str]:
    """Return the squad_type a user is tentatively signed up for, or None."""
    entry = _player_tentative_entry(event, user_id)
    return entry.get("type") if entry else None


def _add_tentative(event: dict, user_id, display_name: str, squad_type: str,
                   roles: Optional[list] = None) -> str:
    """Add (or replace) a user's tentative sign-up. One entry per user.

    Returns "tentative" on success, "invalid_type" for an unknown squad type.
    Touches neither squads, player_slots_used nor the waitlists.
    """
    if squad_type not in _SQUAD_TYPES:
        return "invalid_type"
    uid = str(user_id)
    tentative = event.setdefault("tentative", [])
    tentative[:] = [e for e in tentative if str(e.get("user_id")) != uid]
    tentative.append({
        "user_id": uid, "name": display_name,
        "type": squad_type, "roles": list(roles or []),
    })
    _remove_declined(event, uid)  # going tentative supersedes a "declined" mark
    return "tentative"


def _remove_tentative(event: dict, user_id) -> Optional[dict]:
    """Remove and return the user's tentative entry, or None if absent."""
    uid = str(user_id)
    tentative = event.get("tentative", [])
    for i, entry in enumerate(tentative):
        if str(entry.get("user_id")) == uid:
            return tentative.pop(i)
    return None


# ---------------------------------------------------------------------------
# Player-mode "declined" (Abgemeldet) — explicit "not attending"
# ---------------------------------------------------------------------------
# A declined player actively signals "I'm not coming". They pick nothing and
# hold no seat/waitlist/tentative spot, so entries are minimal: {"user_id","name"}.
# Toggled via the Unregister button when the user holds no other status; gaining
# any real/tentative status clears the mark (see _player_register / _add_tentative).


def _player_declined_entry(event: dict, user_id) -> Optional[dict]:
    """Return the user's declined entry, or None. Non-destructive."""
    uid = str(user_id)
    for entry in event.get("declined", []):
        if str(entry.get("user_id")) == uid:
            return entry
    return None


def _add_declined(event: dict, user_id, display_name: str) -> None:
    """Mark a user as declined ("not attending"). One entry per user; touches no
    squads, slots, waitlists nor the tentative list."""
    uid = str(user_id)
    declined = event.setdefault("declined", [])
    declined[:] = [e for e in declined if str(e.get("user_id")) != uid]
    declined.append({"user_id": uid, "name": display_name})


def _remove_declined(event: dict, user_id) -> Optional[dict]:
    """Remove and return the user's declined entry, or None if absent."""
    uid = str(user_id)
    declined = event.get("declined", [])
    for i, entry in enumerate(declined):
        if str(entry.get("user_id")) == uid:
            return declined.pop(i)
    return None


def _select_tentative(entries, recipient_ids) -> list:
    """Filter tentative entries to a chosen recipient set.

    `recipient_ids is None` means "everyone" (returns a copy of all entries);
    otherwise only entries whose user_id is in the set are kept. IDs are matched
    as strings, so int/str ids interoperate. Unknown ids are ignored.
    """
    if recipient_ids is None:
        return list(entries)
    wanted = {str(x) for x in recipient_ids}
    return [e for e in entries if str(e.get("user_id")) in wanted]


def _player_current_assignment(event: dict, user_assignments: dict, user_id) -> tuple:
    """Return (squad_type, roles) for a seated or waitlisted player, else
    (None, []). Used to carry a player's selection over when switching their
    firm/waitlist sign-up to tentative."""
    uid = str(user_id)
    squad_names = (user_assignments or {}).get(uid, [])
    if squad_names:
        squad = event.get("squads", {}).get(squad_names[0])
        if squad:
            for m in squad.get("members", []):
                if str(m.get("user_id")) == uid:
                    return squad.get("type"), list(_get_member_roles(m))
            return squad.get("type"), []
    for st in _SQUAD_TYPES:
        for entry in event.get(_waitlist_key(st), []):
            if isinstance(entry, (tuple, list)) and len(entry) > 4 and str(entry[4]) == uid:
                role_data = entry[6] if len(entry) > 6 else None
                if isinstance(role_data, list):
                    return st, list(role_data)
                if isinstance(role_data, str) and role_data:
                    return st, [role_data]
                return st, []
    return None, []


def _player_self_unregister(event: dict, user_assignments: dict, user_id) -> tuple:
    """Self-service player removal: drop from a squad if seated, otherwise from
    the waitlist, otherwise from the tentative list.

    Returns (status, name_or_type, promoted):
      - ("squad", squad_name, promoted_list) when removed from a squad,
      - ("waitlist", squad_type, []) when removed from a waitlist,
      - ("tentative", squad_type, []) when removed from the tentative list,
      - (None, None, []) when the user held none of the above.
    """
    ok, squad_name, promoted = _player_unregister(event, user_assignments, user_id)
    if ok:
        return "squad", squad_name, promoted
    wl_type = _player_remove_from_waitlist(event, user_id)
    if wl_type is not None:
        return "waitlist", wl_type, []
    tent = _remove_tentative(event, user_id)
    if tent is not None:
        return "tentative", tent.get("type"), []
    return None, None, []


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
        playstyle_enabled = event.get("playstyle_enabled", True)
        for squad_id, data in squads.items():
            type_map = {"infantry": "Inf.", "vehicle": "Veh.", "heli": "Heli"}
            tl = type_map.get(data.get("type", ""), "?")
            rep = data.get("rep_name", "")
            rep_suffix = f" — {rep}" if rep else ""
            ps_prefix = f"[{data.get('playstyle', 'Normal')}] " if playstyle_enabled else ""
            lines.append(f"{ps_prefix}**{data.get('name', squad_id)}** ({tl}, {data.get('size', 0)}){rep_suffix}")
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
    # Squad count is always even so both teams get the same number of squads.
    max_inf_squads = _even_infantry_max(max_inf_squads)
    unused = server_cap - max_casters - (max_inf_squads * inf_size) - vehicle_player_slots - heli_player_slots

    is_player_mode = event.get("mode") == "player"
    playstyle_enabled = event.get("playstyle_enabled", True)
    # Player-mode in-squad roles are opt-out per event: when disabled, roles are
    # never shown (even if stored on a member from before the toggle was flipped).
    roles_enabled = event.get("player_roles_enabled", True)

    # Slot overview — compact inline grid (row 1: server, caster, max/player)
    overview_name_key = "embed.seats_overview" if is_player_mode else "embed.server_overview"
    if dont_waste_slots_active(event):
        # Only the residual that no oversized squad can absorb anymore counts
        # as unused while the mode is active.
        unused = infantry_wasted_seats(event)
    if unused > 0:
        overview_value = t("embed.server_overview_value", lang,
                           cap=server_cap, free=available, unused=unused)
    else:
        overview_value = t("embed.server_overview_value_no_unused", lang,
                           cap=server_cap, free=available)
    embed.add_field(name=t(overview_name_key, lang), value=overview_value, inline=True)
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
        if type_key != "infantry" and max_count == 0:
            continue
        size_label = "Größe" if lang == "de" else "Size"
        size_info = f"{size_label}: {size}"
        if type_key == "infantry":
            # Oversized sizes (don't-waste mode) stay permanently visible in
            # the header, shown like the squad counts: (registered/possible).
            oversized_counts = {}
            base_count = 0
            for d in squad_group.values():
                sq_size = d.get("size", size)
                if sq_size > size:
                    oversized_counts[sq_size] = oversized_counts.get(sq_size, 0) + 1
                else:
                    base_count += 1
            totals = {}
            base_remaining = 0
            if is_player_mode and dont_waste_slots_active(event):
                # Player mode: capacities are pre-planned by the bot, so the
                # header shows the planned layout instead of registrant choices.
                layout = planned_infantry_capacities(event)
                base_remaining = max(0, layout.count(size) - base_count)
                for cap_size in layout:
                    if cap_size > size:
                        totals[cap_size] = totals.get(cap_size, 0) + 1
            else:
                for opt_size, remaining in infantry_size_options(event):
                    if opt_size == size:
                        base_remaining = remaining
                    else:
                        totals[opt_size] = oversized_counts.get(opt_size, 0) + remaining
            for opt_size, n in oversized_counts.items():
                # Exhausted sizes (or leftovers after disabling the mode) stay visible.
                totals.setdefault(opt_size, n)
            if totals:
                # With mixed sizes, the base size gets the same counter as the
                # oversized entries; without them it would just repeat count/max.
                size_info = (f"({base_count}/{base_count + base_remaining}) "
                             f"{size_label}: {size}")
            for opt_size in sorted(totals):
                size_info += (f" | ({oversized_counts.get(opt_size, 0)}/{totals[opt_size]}) "
                              f"{size_label}: {opt_size}")
        name = t("embed.type_" + type_key, lang) + f" ({count}/{max_count}) [{size_info}]"
        if squad_group:
            text = ""
            for squad_id, data in squad_group.items():
                if is_player_mode:
                    members = data.get("members", [])
                    filled = len(members)
                    sorted_members = sorted(
                        members,
                        key=lambda m: 0 if "Squad Leader" in _get_member_roles(m) else 1)
                    parts = []
                    for m in sorted_members:
                        rls = _get_member_roles(m) if roles_enabled else []
                        parts.append(f"**{m.get('name', '?')}**{_format_role_suffix(rls, lang)}")
                    # One registered player per line for readability; roles of a
                    # single player stay comma-joined on that player's line.
                    names = "\n".join(parts) or "—"
                    # Auto squad names are stored canonically ("Infantry 1");
                    # localize the label using the known type for display.
                    raw_name = data.get('name', squad_id)
                    number = raw_name.rsplit(" ", 1)[-1]
                    squad_label = (f"{t('squad.label_' + type_key, lang)} {number}"
                                   if number.isdigit() else raw_name)
                    # Header on its own line, members listed below it; blank
                    # line between squads keeps the overview easy to scan.
                    header = f"**{squad_label}** (👥 {filled}/{data.get('size', 0)})"
                    if type_key == "infantry" and roles_enabled and filled > 0 and not _squad_has_sl(data):
                        header += f" ⚠️ {t('embed.no_squad_leader', lang)}"
                    text += f"{header}:\n{names}\n\n"
                else:
                    playstyle = data.get("playstyle", "Normal")
                    sq_size = data.get("size", 0)
                    rep = data.get("rep_name")
                    rep_suffix = f" — {rep}" if rep else ""
                    ps_prefix = f"[{playstyle}] " if playstyle_enabled else ""
                    text += f"{ps_prefix}**{data.get('name', squad_id)}** (👥 {sq_size}){rep_suffix}\n"
            embed.add_field(name=name, value=text.rstrip("\n"), inline=False)
        else:
            embed.add_field(name=name, value=t("embed.no_entries", lang), inline=False)

        # Type waitlist — directly below its registered entries
        wl = event.get(f"{type_key}_waitlist", [])
        if wl:
            wl_text = ""
            for i, entry in enumerate(wl):
                if is_player_mode:
                    # (display_name, type, None, 1, user_id, display_name, roles)
                    player_name = entry[5] if len(entry) > 5 else entry[0]
                    role_data = entry[6] if len(entry) > 6 else None
                    if isinstance(role_data, list):
                        wl_roles = role_data
                    elif isinstance(role_data, str) and role_data:
                        wl_roles = [role_data]
                    else:
                        wl_roles = []
                    wl_text += f"{i+1}. **{player_name}**{_format_role_suffix(wl_roles if roles_enabled else [], lang)}\n"
                else:
                    squad_name, _squad_type, playstyle, sq_size, _squad_id, *_rest = entry
                    rep_name = _rest[0] if _rest else None
                    rep_suffix = f" — {rep_name}" if rep_name else ""
                    ps_prefix = f"[{playstyle}] " if playstyle_enabled else ""
                    wl_text += f"{i+1}. {ps_prefix}**{squad_name}** (👥 {sq_size}){rep_suffix}\n"
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

    # Tentative ("Vorläufig") players — one field per squad type at the very
    # bottom. They hold no real seat, so they live below the full roster and
    # waitlists; grouping by type keeps each field well under the 1024-char cap.
    tentative = event.get("tentative", [])
    if is_player_mode and tentative:
        for type_key in _SQUAD_TYPES:
            entries = [e for e in tentative if e.get("type") == type_key]
            if not entries:
                continue
            lines = [f"**{e.get('name', '?')}**{_format_role_suffix(_get_member_roles(e) if roles_enabled else [], lang)}"
                     for e in entries]
            embed.add_field(
                name=t("embed.tentative_label", lang,
                       type=t(f"embed.type_{type_key}", lang), count=len(entries)),
                value="\n".join(lines), inline=False)

    # Declined ("Abgemeldet") players — an explicit "not attending", rendered as
    # the very last field. Flat list (a decliner picks no type), so it has no
    # natural per-type split; cap the value to stay under Discord's 1024-char
    # field limit, else the whole embed edit would be rejected.
    declined = event.get("declined", [])
    if is_player_mode and declined:
        names = [f"**{d.get('name', '?')}**" for d in declined]
        value, shown = "", 0
        for n in names:  # ponytail: 1024-char field cap; overflow collapses to "+X weitere"
            if len(value) + len(n) + 1 > 950:
                break
            value += ("\n" if value else "") + n
            shown += 1
        if shown < len(names):
            value += "\n*" + t("embed.declined_more", lang, count=len(names) - shown) + "*"
        embed.add_field(
            name=t("embed.declined_label", lang, count=len(declined)),
            value=value, inline=False)

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


# ---------------------------------------------------------------------------
# ICS (iCalendar) export
# ---------------------------------------------------------------------------

try:
    _ICS_TZ = ZoneInfo(EVENT_TIMEZONE)
except Exception:
    logger.warning("Invalid EVENT_TIMEZONE %r; falling back to Europe/Berlin", EVENT_TIMEZONE)
    _ICS_TZ = ZoneInfo("Europe/Berlin")
_ICS_DATE_FMT = "%d.%m.%Y %H:%M"


def _ics_escape(value: str) -> str:
    """Escape per RFC 5545 §3.3.11. Colons are intentionally left untouched."""
    if not value:
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        value
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ics_fold(line: str) -> str:
    """Fold a content line at 75 octets per RFC 5545, respecting UTF-8 boundaries."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    pieces: list[bytes] = []
    pos = 0
    limit = 75
    while pos < len(encoded):
        end = min(pos + limit, len(encoded))
        if end < len(encoded):
            while end > pos and (encoded[end] & 0xC0) == 0x80:
                end -= 1
        pieces.append(encoded[pos:end])
        pos = end
        limit = 74  # subsequent lines are prefixed with one space
    return "\r\n ".join(p.decode("utf-8") for p in pieces)


def _ics_dt(dt: datetime) -> str:
    """Format a UTC datetime as YYYYMMDDTHHMMSSZ."""
    if dt.tzinfo is None:
        raise ValueError("_ics_dt requires a timezone-aware datetime")
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_slug(name: str) -> str:
    """Filesystem-safe slug for the ICS filename. ASCII only, max 40 chars."""
    if not name:
        return ""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return slug[:40]


def build_event_ics(
    event: dict,
    guild_id: int,
    channel_id: int,
    jump_url: Optional[str],
) -> bytes:
    """Build the ICS file for an event.

    Returns UTF-8 encoded bytes with CRLF line endings. Times are converted
    from the configured timezone (EVENT_TIMEZONE, default Europe/Berlin) to UTC.
    """
    date_str = event.get("date", "")
    time_str = event.get("time", "20:00")
    naive = datetime.strptime(f"{date_str} {time_str}", _ICS_DATE_FMT)
    start_local = naive.replace(tzinfo=_ICS_TZ)
    duration = int(event.get("duration_minutes") or 120)
    end_local = start_local + timedelta(minutes=duration)

    msg_id = event.get("event_message_id")
    uid_suffix = str(msg_id) if msg_id else "no-msg"
    uid = f"{guild_id}-{channel_id}-{uid_suffix}@squad-event-bot"

    name = event.get("name") or "Event"
    description_text = event.get("description") or ""
    description_parts = []
    if description_text:
        description_parts.append(description_text)
    if jump_url:
        description_parts.append(jump_url)
    description = "\n\n".join(description_parts)

    now_utc = datetime.now(timezone.utc)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//squad-event-discord-bot//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        _ics_fold(f"UID:{uid}"),
        f"DTSTAMP:{_ics_dt(now_utc)}",
        f"DTSTART:{_ics_dt(start_local)}",
        f"DTEND:{_ics_dt(end_local)}",
        _ics_fold(f"SUMMARY:{_ics_escape(name)}"),
    ]
    if description:
        lines.append(_ics_fold(f"DESCRIPTION:{_ics_escape(description)}"))
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    return ("\r\n".join(lines) + "\r\n").encode("utf-8")
