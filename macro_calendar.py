"""
Macro Calendar Alerts — warns you before major market-moving events.

Sends alerts at 60 minutes and 10 minutes before each event.
Sends an "all clear" message after the event passes.

Events tracked automatically:
  - FOMC rate decisions (Fed)
  - NFP (Non-Farm Payrolls) — first Friday of each month at 13:30 UTC
  - CPI — hardcoded + manually added
  - PPI, GDP, and any custom events

Commands:
  /events          — show all upcoming events (next 30 days)
  /addevent DATE TIME NAME
                   — add a custom event
                   — e.g. /addevent 2026-07-15 13:30 US CPI Report
  /delevent ID     — delete an event by its ID number (shown in /events)
  /help

Tip: Verify FOMC dates at federalreserve.gov each year and add any
missing dates with /addevent.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from telegram import Bot

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID         = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
EVENTS_FILE     = "macro_events.json"
CHECK_INTERVAL  = 60      # check every 60 seconds
WARN_60_MIN     = 3600
WARN_10_MIN     = 600

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Built-in 2026 event list ──────────────────────────────────────────────────
# All times in UTC. Verify FOMC at federalreserve.gov each year.

BUILTIN_EVENTS = [
    # FOMC Rate Decisions 2026 (announcement day, 19:00 UTC = 2pm ET)
    {"date": "2026-07-30", "time": "19:00", "name": "FOMC Rate Decision",     "impact": "HIGH"},
    {"date": "2026-09-17", "time": "19:00", "name": "FOMC Rate Decision",     "impact": "HIGH"},
    {"date": "2026-10-29", "time": "19:00", "name": "FOMC Rate Decision",     "impact": "HIGH"},
    {"date": "2026-12-10", "time": "19:00", "name": "FOMC Rate Decision",     "impact": "HIGH"},

    # US CPI 2026 (approx — verify at bls.gov, 13:30 UTC = 8:30am ET)
    {"date": "2026-07-14", "time": "13:30", "name": "US CPI Inflation Report","impact": "HIGH"},
    {"date": "2026-08-12", "time": "13:30", "name": "US CPI Inflation Report","impact": "HIGH"},
    {"date": "2026-09-11", "time": "13:30", "name": "US CPI Inflation Report","impact": "HIGH"},
    {"date": "2026-10-13", "time": "13:30", "name": "US CPI Inflation Report","impact": "HIGH"},
    {"date": "2026-11-12", "time": "13:30", "name": "US CPI Inflation Report","impact": "HIGH"},
    {"date": "2026-12-10", "time": "13:30", "name": "US CPI Inflation Report","impact": "HIGH"},

    # US PPI 2026 (usually 1 day after CPI, 13:30 UTC)
    {"date": "2026-07-15", "time": "13:30", "name": "US PPI Report",          "impact": "MEDIUM"},
    {"date": "2026-08-13", "time": "13:30", "name": "US PPI Report",          "impact": "MEDIUM"},
    {"date": "2026-09-12", "time": "13:30", "name": "US PPI Report",          "impact": "MEDIUM"},
    {"date": "2026-10-14", "time": "13:30", "name": "US PPI Report",          "impact": "MEDIUM"},
    {"date": "2026-11-13", "time": "13:30", "name": "US PPI Report",          "impact": "MEDIUM"},
]

# ── NFP calculator — first Friday of each month, 13:30 UTC ───────────────────

def first_friday(year, month):
    d = datetime(year, month, 1, 13, 30, tzinfo=timezone.utc)
    # weekday(): Monday=0, Friday=4
    offset = (4 - d.weekday()) % 7
    return d + timedelta(days=offset)

def generate_nfp_events(months_ahead=6):
    now    = datetime.now(timezone.utc)
    events = []
    for i in range(months_ahead + 1):
        month  = (now.month - 1 + i) % 12 + 1
        year   = now.year + (now.month - 1 + i) // 12
        dt     = first_friday(year, month)
        if dt > now:
            events.append({
                "date":   dt.strftime("%Y-%m-%d"),
                "time":   "13:30",
                "name":   "US NFP (Non-Farm Payrolls)",
                "impact": "HIGH",
                "auto":   True,
            })
    return events

# ── Event store ───────────────────────────────────────────────────────────────

def load_events():
    if not os.path.exists(EVENTS_FILE):
        return []
    try:
        with open(EVENTS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_events(events):
    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f, indent=2)

def init_events():
    """Seed the events file with built-ins if it doesn't exist yet."""
    if not os.path.exists(EVENTS_FILE):
        save_events(BUILTIN_EVENTS)
        return
    # Merge in any built-in events not already present
    existing = load_events()
    existing_keys = {(e["date"], e["name"]) for e in existing}
    added = False
    for e in BUILTIN_EVENTS:
        if (e["date"], e["name"]) not in existing_keys:
            existing.append(e)
            added = True
    if added:
        save_events(existing)

def get_all_upcoming(days=30):
    stored = load_events()
    nfp    = generate_nfp_events(months_ahead=6)
    all_e  = stored + nfp

    now     = datetime.now(timezone.utc)
    cutoff  = now + timedelta(days=days)
    upcoming = []

    for e in all_e:
        try:
            dt = datetime.strptime("%s %s" % (e["date"], e["time"]),
                                   "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            if now <= dt <= cutoff:
                upcoming.append({**e, "dt": dt})
        except Exception:
            continue

    upcoming.sort(key=lambda x: x["dt"])
    return upcoming

# ── Alert builders ────────────────────────────────────────────────────────────

def impact_label(impact):
    return {"HIGH": "HIGH IMPACT", "MEDIUM": "MEDIUM IMPACT"}.get(impact, impact)

def build_warning(event, minutes_until):
    dt_str = event["dt"].strftime("%Y-%m-%d %H:%M")
    timing = "60 MINUTES" if minutes_until > 15 else "10 MINUTES"

    action = (
        "AVOID opening new positions now.\n"
        "These events cause violent, unpredictable moves.\n"
        "If you have open trades, check your SL is in place."
        if event.get("impact") == "HIGH" else
        "Be cautious with new entries.\n"
        "Medium-impact events can cause short sharp moves."
    )

    return (
        "MACRO EVENT IN %s\n"
        "\n"
        "Event:   %s\n"
        "Impact:  %s\n"
        "Time:    %s UTC\n"
        "\n"
        "%s\n"
        "\n"
        "Wait for price to settle AFTER the\n"
        "release before taking new entries.\n"
        "Usually 15-30 minutes after the event."
    ) % (
        timing,
        event["name"],
        impact_label(event.get("impact", "HIGH")),
        dt_str,
        action,
    )

def build_allclear(event):
    return (
        "ALL CLEAR — %s\n"
        "\n"
        "The event has passed.\n"
        "Wait 15-30 minutes for price to\n"
        "settle before entering new trades.\n"
        "\n"
        "Scanner is resuming normal analysis.\n"
        "Time: %s UTC"
    ) % (
        event["name"],
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

# ── Command handlers ──────────────────────────────────────────────────────────

async def handle_help(bot, chat_id):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "MACRO CALENDAR — COMMANDS\n\n"
            "/events\n"
            "  Show upcoming events (next 30 days)\n\n"
            "/addevent DATE TIME NAME\n"
            "  Add a custom event\n"
            "  Example:\n"
            "  /addevent 2026-07-15 13:30 US CPI Report\n\n"
            "/delevent ID\n"
            "  Delete event by ID shown in /events\n"
            "  Example: /delevent 3\n\n"
            "Automatic alerts at 60 and 10 minutes\n"
            "before every HIGH and MEDIUM event.\n\n"
            "Tip: Verify FOMC dates yearly at\n"
            "federalreserve.gov and add missing\n"
            "ones with /addevent."
        )
    )

async def handle_events(bot, chat_id):
    upcoming = get_all_upcoming(days=30)
    if not upcoming:
        await bot.send_message(chat_id=chat_id,
                               text="No events in the next 30 days.\nUse /addevent to add one.")
        return

    lines = ["UPCOMING MACRO EVENTS (30 days)\n"]
    for i, e in enumerate(upcoming, 1):
        dt_str  = e["dt"].strftime("%b %d  %H:%M UTC")
        auto    = " (auto)" if e.get("auto") else ""
        lines.append("%2d.  %s\n     %s — %s%s" % (
            i, dt_str, e["name"],
            impact_label(e.get("impact", "HIGH")), auto))

    lines.append("\nUse /delevent ID to remove an event.")
    await bot.send_message(chat_id=chat_id, text="\n".join(lines))

async def handle_addevent(bot, chat_id, args):
    if len(args) < 3:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Usage: /addevent DATE TIME NAME\n"
                "Example: /addevent 2026-07-15 13:30 US CPI Report"
            )
        )
        return
    try:
        date = args[0]
        time_str = args[1]
        name = " ".join(args[2:])
        # Validate date/time
        datetime.strptime("%s %s" % (date, time_str), "%Y-%m-%d %H:%M")
        events = load_events()
        events.append({"date": date, "time": time_str, "name": name, "impact": "HIGH"})
        save_events(events)
        await bot.send_message(
            chat_id=chat_id,
            text="Event added:\n%s on %s at %s UTC\n\nUse /events to see your calendar." % (
                name, date, time_str)
        )
    except ValueError:
        await bot.send_message(
            chat_id=chat_id,
            text="Invalid date or time format.\nUse: YYYY-MM-DD HH:MM\nExample: /addevent 2026-07-15 13:30 CPI"
        )

async def handle_delevent(bot, chat_id, args):
    if not args:
        await bot.send_message(chat_id=chat_id,
                               text="Usage: /delevent ID\nGet IDs from /events")
        return
    try:
        idx = int(args[0]) - 1
        upcoming = get_all_upcoming(days=30)
        if idx < 0 or idx >= len(upcoming):
            await bot.send_message(chat_id=chat_id,
                                   text="Invalid ID. Use /events to see the list.")
            return
        event = upcoming[idx]
        if event.get("auto"):
            await bot.send_message(
                chat_id=chat_id,
                text="Cannot delete auto-generated NFP events.\nThey are calculated automatically."
            )
            return
        # Remove from stored events
        events  = load_events()
        name    = event["name"]
        date    = event["date"]
        events  = [e for e in events if not (e["name"] == name and e["date"] == date)]
        save_events(events)
        await bot.send_message(chat_id=chat_id,
                               text="Deleted: %s on %s" % (name, date))
    except (ValueError, IndexError):
        await bot.send_message(chat_id=chat_id,
                               text="Invalid ID. Use /events to see the list.")

# ── Alert monitor ─────────────────────────────────────────────────────────────

async def alert_monitor(bot):
    alerted_60  = set()
    alerted_10  = set()
    alerted_clear = set()

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        now      = datetime.now(timezone.utc)
        upcoming = get_all_upcoming(days=7)

        for e in upcoming:
            dt      = e["dt"]
            key     = "%s|%s" % (e["date"], e["name"])
            secs    = (dt - now).total_seconds()

            # 60-minute warning
            if WARN_60_MIN >= secs > WARN_10_MIN and key not in alerted_60:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=build_warning(e, minutes_until=60)
                    )
                    alerted_60.add(key)
                    log.info("60min warning: %s" % e["name"])
                except Exception as ex:
                    log.error("60min alert error: %s" % ex)

            # 10-minute warning
            elif WARN_10_MIN >= secs > 0 and key not in alerted_10:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=build_warning(e, minutes_until=10)
                    )
                    alerted_10.add(key)
                    log.info("10min warning: %s" % e["name"])
                except Exception as ex:
                    log.error("10min alert error: %s" % ex)

            # All clear (30 minutes after event)
            elif -1800 <= secs < 0 and key not in alerted_clear:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=build_allclear(e)
                    )
                    alerted_clear.add(key)
                    log.info("All clear: %s" % e["name"])
                except Exception as ex:
                    log.error("All clear error: %s" % ex)

# ── Dispatcher ────────────────────────────────────────────────────────────────

async def dispatch(bot, message):
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return
    chat_id = message["chat"]["id"]
    if str(chat_id) != str(CHAT_ID):
        return
    parts   = text.split()
    cmd     = parts[0].lower().split("@")[0]
    args    = parts[1:]

    if cmd == "/help":
        await handle_help(bot, chat_id)
    elif cmd == "/events":
        await handle_events(bot, chat_id)
    elif cmd == "/addevent":
        await handle_addevent(bot, chat_id, args)
    elif cmd == "/delevent":
        await handle_delevent(bot, chat_id, args)

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("Macro Calendar starting...")
    init_events()
    bot    = Bot(token=TELEGRAM_TOKEN)
    offset = 0

    upcoming = get_all_upcoming(days=30)
    next_event_line = ""
    if upcoming:
        nxt = upcoming[0]
        next_event_line = "\n\nNext event:\n%s\n%s UTC" % (
            nxt["name"],
            nxt["dt"].strftime("%b %d at %H:%M"),
        )

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Macro Calendar Online!\n\n"
            "I track major market-moving events\n"
            "and warn you BEFORE they happen:\n\n"
            "  60 min warning — prepare, check SLs\n"
            "  10 min warning — avoid new entries\n"
            "  All clear — safe to trade again\n\n"
            "Events tracked:\n"
            "  FOMC rate decisions\n"
            "  US NFP (auto, first Friday monthly)\n"
            "  US CPI and PPI reports\n\n"
            "Commands:\n"
            "  /events     — upcoming 30 days\n"
            "  /addevent   — add custom event\n"
            "  /delevent   — remove an event"
            + next_event_line
        )
    )

    asyncio.create_task(alert_monitor(bot))

    while True:
        try:
            updates = await bot.get_updates(
                offset=offset, timeout=30, allowed_updates=["message"])
            for update in updates:
                offset = update.update_id + 1
                if update.message:
                    await dispatch(bot, update.message.to_dict())
        except Exception as e:
            log.error("Poll error: %s" % e)
            await asyncio.sleep(5)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
