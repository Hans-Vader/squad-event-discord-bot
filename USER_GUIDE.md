# Squad-Event-Registration Bot — User Guide

The Squad-Event-Registration Bot organizes squad-based events on Discord. Players register via buttons or slash commands, and the bot automatically distributes server slots, manages the waitlist, handles recurrence, and keeps everything in sync. Organizers create events through a wizard, edit settings via DM, and manage roles and reminders — all directly in Discord.

## Table of Contents

- [Event Modes](#event-modes)
- [For Players](#for-players)
- [For Organizers](#for-organizers)
- [Interactive Buttons](#interactive-buttons)
- [Waitlist System](#waitlist-system)
- [FAQ](#faq)

---

## Event Modes

Events are created in one of two modes, picked at creation time. The mode is locked once the event exists; it can't be switched on a running event.

### Representative Mode (default)

The classic behavior. Each registration is a **squad** with a name, type, playstyle, and a Discord user acting as its representative. One registration occupies `squad_size` seats (e.g. 6 for Infantry, 2 for Vehicle, 1 for Heli). A user can register **multiple squads** (up to the configured per-user limit). Casters register separately.

Use this mode when squad leads coordinate their own teams and the organizer needs per-squad metadata (playstyle, rep name).

### Player Mode

Each registration is a **single player** — just the user themselves. The bot auto-assigns individuals to squads in arrival order: the first 6 Infantry sign-ups form "Infantry 1", the next 6 form "Infantry 2", and so on. When the event starts — or at any time manually via the admin panel — the bot merges partially-filled squads and removes empty ones so the overview stays compact. Each player can also pick an **optional in-squad role** (Squad Leader, Medic, Pilot, …) — the role appears next to their name in the event embed, and Squad Leaders sort to the top of their squad. No playstyle, no squad name, no caster role. **One user = one registration.**

Use this mode for pick-up matches or community seat-filling events where individuals sign up and organizers don't care about squad composition.

### Quick comparison

| Aspect | Representative mode | Player mode |
|---|---|---|
| What's registered | A squad (name + type + playstyle) | A single player |
| Who registers | A squad rep on behalf of their squad | Each player for themselves |
| Slots per registration | `squad_size` (e.g. 6) | 1 |
| Multiple registrations per user | Up to configured limit | Always 1 |
| Playstyle selection | Yes | No |
| In-squad role picker | No | Optional multi-select (Squad Leader, Medic, Pilot, …) |
| Casters | Configurable | Disabled |
| Registration UI | Squad name modal + playstyle picker | Type + optional role picker; Discord display name used |
| Slot overview label | "🖥️ Server — 100 slots" | "📋 Seats — 17 slots" |
| Admin-add | Add Squad (name + rep + playstyle) | Add Player (multi-select users + type + optional roles) |

---

## For Players

### Registering — Representative Mode

There are two ways to register a squad:

**Via button (recommended):**
1. Click **Squad** (🪖) in the event display
2. Select the squad type from the dropdown: Infantry, Vehicle, or Heli
3. Select the playstyle: Casual, Normal, or Focused
4. Enter the squad name in the modal
5. The bot confirms the registration or places the squad on the waitlist

### Registering — Player Mode

The button is labeled **Join** (🪖) instead of **Squad**. The flow:

1. Click **Join** (🪖) in the event display
2. Select your squad type from the dropdown: Infantry, Vehicle, or Heli
3. **Optionally** pick one or more in-squad roles — *only if the event creator enabled role selection* (see creation Step 7; when disabled there is no role dropdown and no roles are shown). The dropdown is marked "(optional)", adapts to your type and supports multi-select:
   - **Infantry**: Squad Leader, Medic, Rifleman, Automatic Rifleman, Machine Gunner, Combat Engineer, Light Anti Tank, Heavy Anti Tank, Grenadier, Marksman, Scout, Logi driver, Mortar
   - **Vehicle**: Driver, Gunner, Commander
   - **Heli**: Pilot, Spotter, Gunner

   The role selection is optional — pick nothing and only your name is shown (no parenthetical tag).
4. Click **Continue** — the bot auto-assigns you to the first non-full squad of that type (creating a new squad if none has free slots), or places you on the waitlist if all slots are full. Your Discord display name is used; there's no name modal to fill in.

Your role(s) are shown in parentheses next to your name in the event embed; with no role only your name is shown, e.g. `Infantry 1 (3/6): Alice (Squad Leader, Medic), Bob (Rifleman), Carol`. **Squad Leaders always sort to the top of their squad.** Picking **Squad Leader** (alone or alongside other kits) also influences placement: the bot prefers squads without an existing SL and opens a new squad if every current squad already has one.

**One user, one registration.** If you try to register again while already registered, the bot reports that you're already signed up.

### Tentative Sign-up — Player Mode

Not sure yet whether you'll play? The **Tentative** (🤔) button lets you signal that you *might* join.

1. Click **Tentative** (🤔) in the event display
2. Pick your **squad type** and – optionally – your role (same picker as Join)
3. Click **Continue**

Tentative players **do not occupy a real squad seat**. They are listed at the very bottom of the event embed in their own field per squad type (e.g. "🤔 Tentative – Infantry"), with the optionally chosen role.

**Switching:**
- If you are already **firmly** registered and click **Tentative**, a confirmation dialog appears — on confirm your squad seat is freed (waitlisted players are promoted into it) and your squad type and role are **carried over**.
- If you are **tentative** and click **Join** (🪖), the picker opens pre-filled with your type and role; after **Continue** you are firmly registered and the tentative sign-up is dropped.
- **Abmelden** (❌) also removes a tentative-only sign-up (with a confirmation dialog).

### Registering as Caster

Only available in **representative mode** (caster is disabled in player mode).

- Click **Caster** (🎙️) in the event display

Players can be registered as a caster **and** with squads at the same time.

### Unregistering

- Click **Abmelden** (❌) in the event display

A confirmation dialog is shown before the unregistration is processed in **both modes** — you'll see "Do you really want to unregister? You will lose your spot." and must click Unregister to confirm. You receive a confirmation message once complete.

### All Player Commands

| Command | Description |
|---|---|
| `/help` | Show available commands |

---

## For Organizers

### Initial Server Setup

Before creating events, an admin must run `/setup` to configure:
- **Organizer role** — which role can manage events
- **Log channel** — where the bot logs all actions
- **Language** — German (de) or English (en)

Use `/config_defaults` to edit server-wide default values for event creation via an interactive DM dialog. The overview shows current values for all 10 editable defaults; pick a property from the dropdown to change it. Changes take effect for newly created events.

### Creating an Event

Use `/create_event` to start event creation. The bot replies with a message that explains both modes side by side; pick one with a button:

- **🪖 Representative mode** — runs the full wizard below.
- **🎮 Player mode** — skips the caster-roles step and the max-squads-per-user step, forces `max_caster_slots = 0`, and relabels "Server max players" to "Total seats".

After you pick a mode, a multi-step wizard guides you through:

**Step 1 — Basic Info (Modal):**
- Event name, date, time, description
- Registration start time (date/time or "now"/"sofort" for immediately)

**Step 2 — Server Configuration (Modal):**
- Server max players (rep mode) or Total seats (player mode), max caster slots (0 = casters disabled, and forced to 0 in player mode — the field is hidden), squad sizes (Infantry / Vehicle / Heli), max vehicle squads, max heli squads
- All pre-filled from server defaults (`/config_defaults`)

**Step 3 — Registration Roles:**
- Roles allowed to register — roles whose members may register squads / join (role gate, enforced during registration)
- Roles with early access — roles whose members may register **before** registration opens
- Notify on open — whether to @-mention these roles when registration opens (only asked when registration isn't opening immediately)

> These two are **roles only** — individual users can't be selected here (casters, in Step 5, still allow users).

**Step 4 — Slot Limits (only shown when a registration role is configured):**

Optionally cap how much each registration group may take. Casters never count, and percentages are of the player slots only. Members who exceed their group's cap are rejected with a message.
- Early-access roles — max **% of player slots** (all early-access roles share this quota)
- Early-access roles — max **squads per role** (rep mode only)
- Regular roles — max **squads per user** (rep mode only — this is the per-user squad limit; in player mode it's always 1)

The two early-access caps (% and squads per role) apply **only until registration opens** — once registration is open to everyone, early-access members register without them. While registration is closed, early-access members are bound by the per-role squad cap and are **not** subject to the per-user squad limit; once registration opens, the per-user limit applies to them too. Regular registrants are always bound by the per-user squad limit.

Player mode shows only the early-access % cap.

**Step 5 — Caster Roles (rep mode only — skipped in player mode):**
- Caster roles/users — Who can register as caster (role gate)
- Caster early-access roles/users — Who can register as caster **before** registration opens
- Ping on open toggle

**Step 6 — Timing:**
- Event reminder — Notification X minutes before event start (0 = disabled)
- Registration countdown — Message sent X seconds before registration opens (auto-deleted when registration starts)

**Step 7 — Playstyle & Squad Limit (rep mode) / Role selection (player mode):**
- *Rep mode:* Playstyle selection — whether squads pick a playstyle when registering. Plus max squads per user (1–20) — only asked here when **no** registration-role gate is set; when a gate is configured, this is set in Step 4 (Slot Limits) instead.
- *Player mode:* Role selection — whether players may pick an in-squad role (Squad Leader, Medic, Pilot, …) when registering. **When disabled, there is no role dropdown and roles are not shown in the embed.** Default: enabled. Can also be changed later via the DM editor.

**Step 8 — Confirmation:**
- Summary embed showing all configured settings including unused slots — confirm or cancel

Each step can be skipped — if skipped, server defaults are used. Roles can also be configured later with `/set_event_roles`.

**Slot calculation example:**
```
Server: 100 slots
- Casters: 2 slots
- Vehicle: 5 squads × 2 = 10 slots
- Heli: 2 squads × 1 = 2 slots
- Infantry: (100 − 2 − 10 − 2) / 6 = 14 squads (84 slots)
- Unused: 2 slots
```

### Editing an Event via DM

Organizers can edit a running event via DM: Click **Edit Event** in the admin panel. The bot sends you a single DM with an overview of all properties and their current values, a **dropdown** to pick the property to change, and a **Fertig / Done** button. Pick a property → a small editor appears (a text input, a Yes/No toggle, or a value dropdown) → your change is **saved immediately** and the overview refreshes. Press **Done** when you're finished. The event display in the channel updates automatically after each change.

**General:**
1. Event name
2. Date
3. Time
4. Description

**Squad Config:**
5. Server max players
6. Max caster slots
7. Max vehicle squads
8. Max heli squads
9. Infantry squad size
10. Vehicle squad size
11. Heli squad size
12. Max squads per user

**Extras:**
13. Event reminder (minutes, 0 = disable)
14. Registration start time
15. Event image (upload an image or paste an HTTPS URL)
16. Recurrence (how the event repeats — see below)
17. Duration (event length; defaults to 2h)
18. Recreate next event after (for recurring events: delay after the current event ends before the follow-up is created)
19. Playstyle selection at registration (on/off)
20. Slot limit: early access (% of player slots)
21. Max squads per early-access role

There's no separate confirm step — each edit applies as soon as you make it.

If your change would cause the next recurrence to fire during the current event (before `start + duration + spawn delay`), the edit is rejected with an explanation — shorten the event, increase the spawn delay, or pick a longer recurrence interval.

### Recurring Events

You can configure an event to automatically spawn a follow-up. Set this up via DM edit properties 16 (Recurrence), 17 (Duration), and 18 (Recreate next event after).

**Recurrence options (12):**

1. Never — default; the event is archived at end and nothing is created afterwards
2. Every X minutes
3. Every X hours
4. Every X days
5. Every X weeks (1 = weekly, 2 = biweekly, …)
6. Every month
7. First `{weekday}` of next month — weekday is derived from your event's start date
8. Fourth `{weekday}` of next month
9. Last `{weekday}` of next month
10. Specific date (+ optional time) — one-shot
11. Specific weekdays (e.g. Mon, Wed, Fri)
12. Specific days of month (e.g. 1st and 15th)

**Duration presets:** 30min, 1h, 2h (default), 4h, 6h, 8h, 12h, 24h.

**Recreate-next-event-after presets:** 1min, 5min (default), 10min, 30min, 1h, 6h, 1d, 1w.

**How the lifecycle works:**

- At `start` — registration automatically closes. New signups / unregistrations / squad swaps are rejected. In player mode, partially-filled squads are automatically consolidated at this point.
- At `start + duration` — for **non-recurring** events, the summary is logged to the log channel and the embed is deleted. Done.
- At `start + duration` — for **recurring** events, nothing visible happens yet. The embed stays in the channel as a read-only snapshot of the final state.
- At `start + duration + spawn delay` — for **recurring** events, the old summary is logged, the embed is deleted, and a fresh event is created and posted automatically. The new event inherits all configuration (name, slot sizes, role pings, recurrence, duration, spawn delay) and resets runtime state.

### Admin Panel — Representative Mode

Click the **Admin** (⚙️) button on the event embed to open the admin panel. In rep mode it contains 8 buttons in 4 rows:

| Row | Button | Description |
|---|---|---|
| Squad | **Add Squad** | Select type, playstyle, representative user, then enter squad name |
| Squad | **Remove Squad** | Select a squad to remove (includes waitlisted squads) |
| Caster | **Add Caster** | Select a Discord user to add as caster |
| Caster | **Remove Caster** | Select a caster to remove (includes waitlisted casters) |
| Registration | **Open Registration** | Open registration manually — gated behind a confirmation prompt (opening may send a ping to the configured roles) |
| Registration | **Close Registration** | Close registration manually — gated behind a confirmation prompt. For rep/caster events this reverts the event to its early-access state (only early-access roles can register) |
| Event | **Edit Event** | Opens DM-based editing session (see above) |
| Event | **Delete Event** | Delete the event with confirmation |

When adding a squad as admin, the selected representative user counts toward their max squads limit, but the limit is not enforced — admins can always add regardless.

### Admin Panel — Player Mode

In player mode the admin panel has 8 buttons in 3 rows — the Squad and Caster rows are replaced with a single Player row:

| Row | Button | Description |
|---|---|---|
| Player | **Add Player** | Pick one or more Discord users (multi-select), a squad type, and (optionally) one or more in-squad roles applied to all picked users; then confirm. All picked users are registered in a single submit. If capacity is hit mid-batch, remaining users go to the waitlist. The chosen roles are stored for each user and shown next to their name in the event embed (no role → just the name). |
| Player | **Remove Player** | Pick one or more players (multi-select) — from current squad members, from any waitlist (prefixed `[WL-Inf]` / `[WL-Veh]` / `[WL-Heli]`), **and** from the tentative list (prefixed `[Vorl-Inf]` / `[Vorl-Veh]` / `[Vorl-Heli]`). The action is gated behind a red "Unregister" confirm button. |
| Player | **Ask tentatives** (📨) | Ask the tentative players whether they'll join. You first pick **which** tentatives to ask (a multi-select dropdown) or press **Ask all**. Then you choose **thread** or **DM**; for a thread you then choose **public** (created directly on the event message) or **private** (a private thread that also adds you, the organizer). The message pings/links the chosen tentatives so they confirm via the existing **Join** / **Abmelden** buttons. Only shown when there are tentative players. |
| Registration | **Open Registration** | Open registration manually — gated behind a confirmation prompt (opening may send a ping to the configured roles) |
| Registration | **Close Registration** | Close registration manually — gated behind a confirmation prompt |
| Registration | **Consolidate Squads** | Merge partially-filled squads and drop empty ones — gated behind a confirmation prompt. Also happens automatically when the event starts. Player mode only. |
| Event | **Edit Event** | Opens DM-based editing session |
| Event | **Delete Event** | Delete the event with confirmation |

Players removed from a squad trigger the waitlist promotion (DM + log channel notification for anyone moved up). Players removed from the waitlist just disappear from the queue. The tentative list is kept (not cleared) when the event starts, so **Ask tentatives** remains useful for filling open seats right before start.

### Role Configuration

| Command | Description |
|---|---|
| `/set_event_roles` | Add roles to the event (ping, squad-rep, community-rep, caster, caster early-access) |
| `/clear_event_roles` | Clear event roles — all at once or by category |

### Event Management

| Command | Description |
|---|---|
| `/create_event` | Create a new event (guided wizard) |
| `/delete_event` | Delete the event |
| `/update` | Refresh the event display |

Open and close registration manually via the **⚙️ Admin** button on the event embed.


### Admin Tools

| Command | Description |
|---|---|
| `/admin_edit_squad` | Edit a squad's player size |
| `/admin_waitlist` | Show the complete waitlist |
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
| `/config_defaults` | Edit server-wide default parameters via DM dialog |
| `/sync` | Sync slash commands with Discord |

---

## Interactive Buttons

The event display contains the following buttons. All buttons are visible to everyone — permissions are checked on click.

| Button | Function |
|---|---|
| **Squad** (🪖) | Rep mode: starts the guided registration (type → playstyle → name) |
| **Join** (🪖) | Player mode: pick type and optional in-squad role, then auto-assigned to a squad |
| **Caster** (🎙️) | Direct caster registration |
| **Abmelden** (❌) | Unregister squad/caster with confirmation |
| **Admin** (⚙️) | Opens admin panel (organizer only) |
| **Calendar** (📅) | Download an `.ics` file to import the event into your calendar app |

---

## Waitlist System

Waitlist semantics are the same in both modes — only the unit differs (a full squad in rep mode, a single player in player mode).

- **Automatic placement** — When all slots for a type are taken, the new sign-up goes on the waitlist. In rep mode this is a whole squad; in player mode this is one player. Casters have their own waitlist in rep mode (not applicable in player mode).
- **Automatic promotion** — When a slot opens up (someone unregisters), the next entry on the waitlist is automatically moved into the event. In rep mode this moves a whole squad if it fits; in player mode this moves one player into the first squad with capacity (creating a new squad if needed).
- **Order** — First come, first served. The waitlist is processed strictly front-to-back.
- **DM notification** — When you're promoted from the waitlist into the event, you receive an automatic DM. Rep mode DMs the squad rep; player mode DMs the individual player.
- **Log channel line** — The bot writes a line to the guild log channel per promotion so organizers have an audit trail.
- **Viewing the waitlist** — Organizers can see the full waitlist with `/admin_waitlist`.
- **Removing from the waitlist** — A waitlisted user can unregister themselves (confirmation dialog). Organizers can remove waitlist entries via **Admin → Remove Squad** (rep) or **Admin → Remove Player** (player) — the picker lists both registered and waitlisted entries.

---

## FAQ

**Q: What's the difference between representative mode and player mode?**
A: Rep mode has you register a whole squad (with a name, playstyle, and a user as its lead). Player mode has you register as a single individual, and the bot groups individuals into squads automatically (first 6 Infantry sign-ups form "Infantry 1", next 6 form "Infantry 2", etc.). Casters are disabled in player mode. Organizers pick the mode at event creation; it can't be changed later.

**Q: Why does my event have a "Join" button instead of a "Squad" button?**
A: The event was created in player mode. You register yourself individually — the bot handles squad assignment. You pick a squad type, optionally an in-squad role (Squad Leader, Medic, …), then click Continue; your Discord display name is used automatically.

**Q: How do I register my squad?**
A: Click **Squad** (🪖) in the event display. You'll be guided through type, playstyle, and name selection. (This is rep mode — player mode's **Join** flow picks type and an optional in-squad role.)

**Q: What does the in-squad role picker in player mode do?**
A: Roles let you signal what you'd like to play (Squad Leader, Medic, Pilot, …) so others know who's filling which kits. You can pick **multiple roles** in one registration — for example "Squad Leader + Medic" if you can run either. The list adapts to the squad type you picked. Roles are visible to everyone in the squad list as `Name (Role)` or `Name (Role1, Role2)`. Squad Leaders sort to the top of their squad, and a new SL is routed into a squad without an existing one whenever capacity allows. Select nothing to register as **I don't care**.

**Q: Can I be a caster and a squad member at the same time?**
A: Yes. You can register as a caster and register squads in parallel.

**Q: What happens when the event is full?**
A: Your squad is automatically placed on the waitlist. You'll be promoted when a slot opens up and notified via DM.

**Q: How many squads can I register?**
A: In rep mode, it depends on the event's max-squads-per-user setting (default: 1, max: 20). In player mode it's always **exactly 1** — one user, one registration.

**Q: How do admins register a group of players in player mode?**
A: Admin → Add Player. The picker lets you select multiple Discord users at once along with a single squad type and (optionally) one or more in-squad roles that are applied to every user in the batch. All selected users are registered in one confirm click. If capacity runs out mid-batch, the rest go to the waitlist automatically. If you need a different role set for different players, run the picker once per role set.

**Q: What is the difference between Infantry, Vehicle, and Heli?**
A: The three squad types have different sizes and separate slot pools. Infantry squads are typically the largest (e.g. 6 players), vehicle squads smaller (e.g. 2), and heli squads the smallest (e.g. 1).

**Q: What does "early access" mean?**
A: Members of an early-access role (or a caster early-access role) can register **before** the official registration start time.

**Q: I can't register — what should I do?**
A: Check whether you have a required role (when "roles allowed to register" are configured) and whether registration is already open. You may also have hit a slot cap for your role group. If no roles are configured, anyone can register.

**Q: How do I edit a running event?**
A: Click **Admin** → **Edit Event**. The bot DMs you an overview with a dropdown — pick the property you want to change (21 in total), edit it (the change saves immediately), and press **Done** when finished.

**Q: How do I make an event repeat?**
A: Edit the event via DM and open property 16 (Recurrence). Pick one of 12 types — for example "Every X weeks" for a weekly cycle, or "Last Sunday of next month" for a monthly pattern that follows your event's weekday. The follow-up event is created automatically when the current one ends.

**Q: How long does the old event stay visible after it ends?**
A: For non-recurring events, it's archived immediately at `end`. For recurring events, it stays until the follow-up is due (controlled by property 18, Recreate next event after — default 5 minutes).

**Q: Why was my recurrence edit rejected?**
A: The next occurrence would fire during the current event (or during the spawn delay window). Shorten the event duration, shorten the spawn delay, or pick a longer recurrence interval.

**Q: How do I set up the bot for the first time?**
A: An admin runs `/setup` to configure the organizer role, log channel, and language. Then use `/config_defaults` to set server capacity and squad sizes via the DM editor. After that, organizers can create events with `/create_event`.

**Q: Why aren't my slash commands showing up?**
A: An administrator needs to run `/sync` to synchronize the commands with Discord.

**Q: How do I set an event image?**
A: Edit the event via DM (property 15). You can upload an image or paste an HTTPS URL.

---

For further help, contact a server administrator.
