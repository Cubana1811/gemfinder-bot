"""
DCA Bot — splits your entry into 3 levels for a better average price.

Instead of going all-in at one price, you enter in thirds:
  Entry 1 (40%) — at signal price (immediate)
  Entry 2 (35%) — pullback level  (-1.5% for LONG, +1.5% for SHORT)
  Entry 3 (25%) — deep pullback   (-3.0% for LONG, +3.0% for SHORT)

Commands:
  /dca SYMBOL DIRECTION ENTRY SL TP1 [ACCOUNT]
      Generate a 3-level DCA plan
      e.g. /dca BTCUSDT LONG 65000 63000 70000 1000

  /dcawatch SYMBOL DIRECTION ENTRY SL TP1 [ACCOUNT]
      Same as /dca but also monitors prices and alerts when
      each entry level is hit

  /dcalist
      Show all active DCA plans being watched

  /dcaclose SYMBOL
      Stop watching a DCA plan

  /help

Auto-monitors price every 2 minutes. Alerts when entry levels are hit.
Recalculates the average entry after each fill.
"""

import os
import json
import time
import logging
import requests
import asyncio
from datetime import datetime, timezone
from telegram import Bot

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID          = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
BINANCE_BASE     = "https://fapi.binance.com"
DCA_FILE         = "dca_plans.json"
POLL_INTERVAL    = 2
MONITOR_INTERVAL = 120   # check prices every 2 minutes
DEFAULT_RISK_PCT = 2.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def fp(n):
    if n >= 1000: return "%.2f" % n
    if n >= 1:    return "%.4f" % n
    if n >= 0.01: return "%.6f" % n
    return "%.8f" % n

def get_price(symbol):
    try:
        r = requests.get(
            "%s/fapi/v1/ticker/price?symbol=%s" % (BINANCE_BASE, symbol.upper()),
            timeout=8)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception:
        pass
    return 0.0

def load_plans():
    if not os.path.exists(DCA_FILE):
        return {}
    try:
        with open(DCA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_plans(p):
    with open(DCA_FILE, "w") as f:
        json.dump(p, f, indent=2)

# ── DCA calculator ────────────────────────────────────────────────────────────

def build_dca_plan(symbol, direction, entry, sl, tp1, account=0.0):
    risk_usd = account * DEFAULT_RISK_PCT / 100 if account > 0 else 0

    if direction == "LONG":
        e1 = entry
        e2 = entry * 0.985   # -1.5%
        e3 = entry * 0.970   # -3.0%
    else:
        e1 = entry
        e2 = entry * 1.015   # +1.5%
        e3 = entry * 1.030   # +3.0%

    # Weights
    w1, w2, w3 = 0.40, 0.35, 0.25
    avg_entry = e1 * w1 + e2 * w2 + e3 * w3

    # Per-level sizing (if account known)
    if risk_usd > 0:
        sl_dist = abs(avg_entry - sl) / avg_entry
        total_pos = risk_usd / sl_dist if sl_dist > 0 else 0
        size1 = total_pos * w1
        size2 = total_pos * w2
        size3 = total_pos * w3
    else:
        size1 = size2 = size3 = 0

    tp1_pct = abs(tp1 - avg_entry) / avg_entry * 100
    sl_pct  = abs(avg_entry - sl)  / avg_entry * 100
    rr      = tp1_pct / sl_pct if sl_pct > 0 else 0

    return {
        "symbol":    symbol,
        "direction": direction,
        "sl":        sl,
        "tp1":       tp1,
        "account":   account,
        "entries": [
            {"level": 1, "price": e1, "weight": w1, "size_usd": size1, "filled": False, "alerted": False},
            {"level": 2, "price": e2, "weight": w2, "size_usd": size2, "filled": False, "alerted": False},
            {"level": 3, "price": e3, "weight": w3, "size_usd": size3, "filled": False, "alerted": False},
        ],
        "avg_entry":  avg_entry,
        "tp1_pct":    tp1_pct,
        "sl_pct":     sl_pct,
        "rr":         rr,
        "created_at": time.time(),
        "watching":   False,
    }

def build_plan_msg(plan, show_sizes=True):
    d       = plan["direction"]
    symbol  = plan["symbol"].replace("USDT", "")
    e       = plan["entries"]
    acc     = plan["account"]
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    def size_str(entry):
        if show_sizes and entry["size_usd"] > 0:
            return "  ($%.0f)" % entry["size_usd"]
        return ""

    e1_status = "FILLED" if e[0]["filled"] else "ENTRY 1 — act now"
    e2_status = "FILLED" if e[1]["filled"] else "ENTRY 2 — limit order"
    e3_status = "FILLED" if e[2]["filled"] else "ENTRY 3 — limit order"

    account_line = ""
    if acc > 0:
        account_line = "Account:  $%.2f  (risk 2%% = $%.2f)\n" % (acc, acc * 0.02)

    return (
        "DCA PLAN — %s %s\n"
        "\n"
        "%s"
        "\n"
        "=== ENTRY LEVELS ===\n"
        "Entry 1 (40%%): $%s  [%s]%s\n"
        "Entry 2 (35%%): $%s  [%s]%s\n"
        "Entry 3 (25%%): $%s  [%s]%s\n"
        "\n"
        "=== RESULT ===\n"
        "Avg Entry: $%s\n"
        "SL:        $%s  (-%.2f%%)\n"
        "TP1:       $%s  (+%.2f%%)\n"
        "R/R:       %.2fx\n"
        "\n"
        "=== HOW TO USE ===\n"
        "1. Place MARKET order at Entry 1 now\n"
        "2. Set LIMIT orders at Entry 2 and 3\n"
        "3. Your SL and TP1 are based on avg entry\n"
        "\n"
        "If only Entry 1 fills: SL = $%s still valid.\n"
        "If all 3 fill: avg entry = $%s\n"
        "\n"
        "Time: %s UTC"
    ) % (
        d, symbol,
        account_line,
        fp(e[0]["price"]), e1_status, size_str(e[0]),
        fp(e[1]["price"]), e2_status, size_str(e[1]),
        fp(e[2]["price"]), e3_status, size_str(e[2]),
        fp(plan["avg_entry"]),
        fp(plan["sl"]),  plan["sl_pct"],
        fp(plan["tp1"]), plan["tp1_pct"],
        plan["rr"],
        fp(plan["sl"]),
        fp(plan["avg_entry"]),
        now,
    )

# ── Command handlers ──────────────────────────────────────────────────────────

async def handle_help(bot, chat_id):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "DCA BOT — COMMANDS\n\n"
            "/dca SYMBOL DIRECTION ENTRY SL TP1 [ACCOUNT]\n"
            "  Show a 3-level DCA plan\n"
            "  Example:\n"
            "  /dca BTCUSDT LONG 65000 63000 70000 1000\n\n"
            "/dcawatch SYMBOL DIRECTION ENTRY SL TP1 [ACCOUNT]\n"
            "  Same + alerts when each level is hit\n\n"
            "/dcalist\n"
            "  Show active watched plans\n\n"
            "/dcaclose SYMBOL\n"
            "  Stop watching a plan\n\n"
            "DCA splits your entry 40%% / 35%% / 25%%\n"
            "at signal price / -1.5%% / -3.0%% (LONG)\n"
            "Result: better average entry price."
        )
    )

async def _parse_and_plan(args, watching):
    if len(args) < 5:
        return None, "Need: SYMBOL DIRECTION ENTRY SL TP1 [ACCOUNT]"
    try:
        symbol    = args[0].upper()
        direction = args[1].upper()
        entry     = float(args[2])
        sl        = float(args[3])
        tp1       = float(args[4])
        account   = float(args[5]) if len(args) > 5 else 0.0

        if direction not in ("LONG", "SHORT"):
            return None, "Direction must be LONG or SHORT."
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        plan = build_dca_plan(symbol, direction, entry, sl, tp1, account)
        plan["watching"] = watching
        return plan, None
    except (ValueError, IndexError):
        return None, "Invalid numbers. Example: /dca BTCUSDT LONG 65000 63000 70000"

async def handle_dca(bot, chat_id, args):
    plan, err = await _parse_and_plan(args, watching=False)
    if err:
        await bot.send_message(chat_id=chat_id, text=err)
        return
    msg = build_plan_msg(plan)
    await bot.send_message(chat_id=chat_id, text=msg)

async def handle_dcawatch(bot, chat_id, args):
    plan, err = await _parse_and_plan(args, watching=True)
    if err:
        await bot.send_message(chat_id=chat_id, text=err)
        return

    plans = load_plans()
    plans[plan["symbol"]] = plan
    save_plans(plans)

    msg = build_plan_msg(plan)
    await bot.send_message(
        chat_id=chat_id,
        text=msg + "\n\nWatching price — I will alert you when each entry level is hit."
    )
    log.info("DCA watch added: %s %s" % (plan["direction"], plan["symbol"]))

async def handle_dcalist(bot, chat_id):
    plans = load_plans()
    watching = {k: v for k, v in plans.items() if v.get("watching")}
    if not watching:
        await bot.send_message(chat_id=chat_id,
                               text="No active DCA plans.\nUse /dcawatch to add one.")
        return
    lines = ["ACTIVE DCA PLANS\n"]
    for sym, p in watching.items():
        filled = sum(1 for e in p["entries"] if e["filled"])
        coin   = sym.replace("USDT", "")
        lines.append("%s %s — %d/3 entries filled\n  Avg entry: $%s\n  SL: $%s  TP1: $%s" % (
            p["direction"], coin, filled,
            fp(p["avg_entry"]), fp(p["sl"]), fp(p["tp1"])))
    await bot.send_message(chat_id=chat_id, text="\n\n".join(lines))

async def handle_dcaclose(bot, chat_id, args):
    if not args:
        await bot.send_message(chat_id=chat_id,
                               text="Usage: /dcaclose SYMBOL\nExample: /dcaclose BTCUSDT")
        return
    symbol = args[0].upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    plans = load_plans()
    if symbol not in plans:
        await bot.send_message(chat_id=chat_id,
                               text="%s not found in DCA plans." % symbol)
        return
    del plans[symbol]
    save_plans(plans)
    await bot.send_message(chat_id=chat_id,
                           text="DCA plan closed: %s" % symbol.replace("USDT", ""))

# ── Price monitor ─────────────────────────────────────────────────────────────

async def price_monitor(bot):
    while True:
        await asyncio.sleep(MONITOR_INTERVAL)
        plans = load_plans()
        changed = False

        for symbol, plan in plans.items():
            if not plan.get("watching"):
                continue

            price = get_price(symbol)
            if price == 0:
                continue

            direction = plan["direction"]
            coin      = symbol.replace("USDT", "")

            for i, entry in enumerate(plan["entries"]):
                if entry["filled"] or entry["alerted"]:
                    continue

                ep = entry["price"]
                # Trigger: price within 0.3% of entry level
                near = abs(price - ep) / ep * 100 < 0.3

                # For LONG: price dropped to or below entry level
                # For SHORT: price rose to or above entry level
                hit = (
                    (direction == "LONG"  and price <= ep * 1.003) or
                    (direction == "SHORT" and price >= ep * 0.997)
                )

                if hit or near:
                    level_num = entry["level"]
                    pct_str   = ["", "40%", "35%", "25%"][level_num]
                    size_str  = ("  — $%.0f" % entry["size_usd"]) if entry["size_usd"] > 0 else ""

                    try:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=(
                                "DCA ENTRY %d HIT — %s %s\n"
                                "\n"
                                "Level:   Entry %d of 3  (%s of position)%s\n"
                                "Price:   $%s\n"
                                "Target:  $%s\n"
                                "\n"
                                "ACTION: Place %s order now.\n"
                                "%s"
                                "\n"
                                "SL: $%s  |  TP1: $%s\n"
                                "\n"
                                "Time: %s UTC"
                            ) % (
                                level_num, direction, coin,
                                level_num, pct_str, size_str,
                                fp(price), fp(ep),
                                "MARKET" if level_num == 1 else "LIMIT",
                                ("Next level: $%s\n" % fp(plan["entries"][i+1]["price"]))
                                if i + 1 < len(plan["entries"]) else "",
                                fp(plan["sl"]), fp(plan["tp1"]),
                                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                            )
                        )
                        plan["entries"][i]["alerted"] = True
                        plan["entries"][i]["filled"]  = True
                        changed = True
                        log.info("DCA entry %d hit: %s @ %s" % (level_num, symbol, fp(price)))
                    except Exception as e:
                        log.error("DCA alert error: %s" % e)

        if changed:
            save_plans(plans)

# ── Dispatcher ────────────────────────────────────────────────────────────────

async def dispatch(bot, message):
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return
    chat_id = message["chat"]["id"]
    parts   = text.split()
    cmd     = parts[0].lower().split("@")[0]
    args    = parts[1:]

    if cmd == "/help":
        await handle_help(bot, chat_id)
    elif cmd == "/dca":
        await handle_dca(bot, chat_id, args)
    elif cmd == "/dcawatch":
        await handle_dcawatch(bot, chat_id, args)
    elif cmd == "/dcalist":
        await handle_dcalist(bot, chat_id)
    elif cmd == "/dcaclose":
        await handle_dcaclose(bot, chat_id, args)

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("DCA Bot starting...")
    bot    = Bot(token=TELEGRAM_TOKEN)
    offset = 0

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "DCA Bot Online!\n\n"
            "Split any entry into 3 levels for a\n"
            "better average price:\n\n"
            "  Entry 1 (40%%) — signal price now\n"
            "  Entry 2 (35%%) — -1.5%% pullback\n"
            "  Entry 3 (25%%) — -3.0%% pullback\n\n"
            "Commands:\n"
            "  /dca SYMBOL DIRECTION ENTRY SL TP1\n"
            "  /dcawatch — same + price alerts\n"
            "  /dcalist  — show active plans\n"
            "  /dcaclose SYMBOL — stop watching\n\n"
            "Example:\n"
            "  /dca BTCUSDT LONG 65000 63000 70000 1000\n\n"
            "Never go all-in at one price again."
        )
    )

    asyncio.create_task(price_monitor(bot))

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
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
