# Squad-Event-Registration Bot — User Guide

The Squad-Event-Registration Bot organizes squad-based events on Discord. Players register their squads via buttons or slash commands, choose a squad type (Infantry/Vehicle/Heli) and playstyle, and the bot automatically distributes server slots. Organizers create events through a wizard, edit settings via DM, and manage the waitlist, roles, and reminders — all directly in Discord.

## Table of Contents

- [For Players](#for-players)
- [For Organizers](#for-organizers)
- [Interactive Buttons](#interactive-buttons)
- [Waitlist System](#waitlist-system)
- [FAQ](#faq)

---

## For Players

### Registering a Squad

There are two ways to register a squad:

**Via button (recommended):**
1. Click **Squad anmelden** in the event display
2. Select the squad type from the dropdown: Infantry, Vehicle, or Heli
3. Select the playstyle: Casual, Normal, or Focused
4. Enter the squad name in the modal
5. The bot confirms the registration or places the squad on the waitlist

**Via slash command:**
- `/register` — Starts the same guided flow (type → playstyle → name)
- `/register_squad [name]` — Registers a squad with a predefined name

### Registering as Caster

- Click **Als Caster anmelden** in the event display, or
- Use `/register_caster`

Players can be registered as a caster **and** with squads at the same time.

### Viewing Status

- **Mein Squad/Caster** button — Shows your assignments and waitlist position
- `/squad_list` — Shows all registered squads
- `/find [name]` — Search for a squad or player
### Unregistering

- Click **Abmelden** in the event display, or
- Use `/unregister`

A confirmation dialog is shown before the unregistration is processed.

### All Player Commands

| Command | Description |
|---|---|
| `/register` | Guided squad registration (type → playstyle → name) |
| `/register_squad [name]` | Register a squad with a predefined name |
| `/register_caster` | Register as caster |
| `/unregister` | Unregister from the event |
| `/squad_list` | Show all registered squads |
| `/find [name]` | Search for a squad or player |
| `/help` | Show available commands |

---

## For Organizers

### Creating an Event

Use `/event` to start event creation. A modal collects the basic info, then an optional role wizard follows:

**Modal — Basic Info:**
- Event name, date, time, description
- Registration start time (date/time or "now"/"sofort" for immediately)

The event is created and displayed immediately after the modal is submitted. Server configuration (capacity, squad sizes, limits) uses guild defaults set via `/set_defaults`. Event reminders can be added afterwards with `/set_event_reminder`.

**Post-Creation Role Wizard (optional, 2 steps):**

After the event is created, an ephemeral role wizard appears automatically:

*Step 1 — Squad Roles:*
- Squad-Rep roles/users — Who can register squads (role gate, enforced during registration)
- Community-Rep roles/users — Who can register squads **before** registration opens (early access)

*Step 2 — Caster Roles:*
- Caster roles/users — Who can register as caster (role gate, enforced during registration)
- Caster early-access roles/users — Who can register as caster **before** registration opens

Each step uses mentionable select menus that support both roles and individual users. Each step can be skipped — if skipped or timed out, no gate is set and anyone can register. Roles can also be configured later with `/set_event_roles`.

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

Organizers can edit a running event via DM: Click **Event bearbeiten** in the admin menu. The bot sends a numbered list of 15 editable properties:

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

Each edit shows the old → new value with a confirmation step. The event display in the channel updates automatically after each change.

### Role Configuration

All role commands work as toggles — run once to add, run again to remove. Each role supports multi-select (multiple Discord roles and individual users).

| Command | Description |
|---|---|
| `/set_squad_rep_role [role] [user]` | Add/remove squad-rep role or user |
| `/set_community_rep_role [role] [user]` | Add/remove community-rep role or user (early access) |
| `/set_caster_role [role] [user]` | Add/remove caster role or user |
| `/set_streamer_role [role] [user]` | Add/remove streamer role or user |
| `/set_ping_role [roles]` | Set roles to ping when registration opens (up to 3) |

### Event Management

| Command | Description |
|---|---|
| `/event` | Create a new event (guided wizard) |
| `/open` | Open registration immediately |
| `/close` | Close registration |
| `/delete_event` | Delete the event |
| `/set_channel` | Set the channel for event updates |
| `/set_event_reminder [minutes]` | Set a reminder X minutes before event start (0 = disable) |
| `/set_max_squads [count]` | Set max squads per player |
| `/show_event` | Show the event with interactive buttons |
| `/update` | Refresh the event display |

### Admin Tools

| Command | Description |
|---|---|
| `/admin_add_squad` | Add a squad (guided flow with dropdown) |
| `/admin_add_caster [user]` | Add a user as caster (bypasses time/role restrictions) |
| `/admin_remove_caster` | Remove a caster (dropdown selection) |
| `/admin_squad_remove` | Remove a squad (dropdown selection) |
| `/admin_waitlist` | Show the complete waitlist |
| `/admin_user_assignments` | Show all user assignments |
| `/admin_user_info [user]` | Show Discord ID, username, and squad/caster assignment |
| `/reset_team_assignment [user]` | Reset a user's assignment |
| `/export_csv` | Export squad list as CSV |
| `/admin_help` | Show admin help |

### System Commands

| Command | Description |
|---|---|
| `/sync` | Sync slash commands |
| `/export_log` | Export the log file |
| `/clear_log` | Clear the log file |
| `/clear_messages [count]` | Delete messages in the channel |

---

## Interactive Buttons

The event display contains the following buttons. All buttons are visible to everyone — permissions are checked on click.

| Button | Function |
|---|---|
| **Squad anmelden** | Starts the guided registration (type → playstyle → name) |
| **Als Caster anmelden** | Direct caster registration |
| **Mein Squad/Caster** | Shows your assignments and waitlist position |
| **Abmelden** | Unregister squad/caster with confirmation |
| **Admin** | Opens admin actions (add/remove squad, edit event via DM, delete event) |

---

## Waitlist System

- **Automatic placement** — When all slots for a squad type are taken, the squad is automatically placed on the waitlist. The same applies to casters.
- **Automatic promotion** — When a slot opens up (e.g. through unregistration), the next squad on the waitlist is automatically promoted.
- **Order** — Squads on the waitlist are sorted by registration time (first come, first served).
- **DM notification** — When a squad is promoted from the waitlist into the event, the player receives an automatic DM notification.
- **Viewing the waitlist** — Players can see their position via the **Mein Squad/Caster** button. Organizers can see the full waitlist with `/admin_waitlist`.

---

## FAQ

**Q: How do I register my squad?**
A: Click **Squad anmelden** in the event display or use `/register`. You'll be guided through type, playstyle, and name selection.

**Q: Can I be a caster and a squad member at the same time?**
A: Yes. You can register as a caster and register squads in parallel.

**Q: What happens when the event is full?**
A: Your squad is automatically placed on the waitlist. You'll be promoted when a slot opens up and notified via DM.

**Q: How many squads can I register?**
A: This depends on the event configuration. The organizer sets the maximum number of squads per player (default: 1).

**Q: What is the difference between Infantry, Vehicle, and Heli?**
A: The three squad types have different sizes and separate slot pools. Infantry squads are typically the largest (e.g. 6 players), vehicle squads smaller (e.g. 2), and heli squads the smallest (e.g. 1).

**Q: What does "early access" mean?**
A: Players with a Community-Rep or Caster early-access role can register **before** the official registration start time.

**Q: I can't register — what should I do?**
A: Check whether you have the required role (e.g. Squad-Rep for squad registration) and whether registration is already open. If no roles are configured, anyone can register.

**Q: How do I edit a running event?**
A: Click **Event bearbeiten** in the admin menu. The bot sends you a DM with a numbered list of all properties. Reply with the number of the property you want to change.

**Q: Why aren't my slash commands showing up?**
A: An administrator needs to run `/sync` to synchronize the commands with Discord.

**Q: How do I set an event image?**
A: Edit the event via DM (property 15). You can upload an image or paste an HTTPS URL.

---

For further help, contact a server administrator.
