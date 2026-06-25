"""
TP Hit Tracker — monitors every signal sent by tv_scanner and alerts
you on Telegram the moment TP1, TP2, TP3 or SL is hit.

Also sends:
- "Move SL to breakeven" reminder when TP1 is hit
- "Close remaining position" reminder when TP2 is hit
- Final trade summary with result and R earned/lost
"""

import os
import time
import json
import logging
import requests
import asyncio
from telegram import Bot
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID        = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
BINANCE_BASE   = "https://fapi.binance.com"
CHECK_INTERVAL = 30        # check prices every 30 seconds
MAX_TRADE_HOURS = 48       # auto-expire trades after 48 hours

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Shared trade store (written by tv_scanner, read by this process) ──────────
TRADES_FILE = "active_trades.json"

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return {}
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def get_price(symbol):
    try:
        r = requests.get(
            "%s/fapi/v1/ticker/price?symbol=%s" % (BINANCE_BASE, symbol),
            timeout=8)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception as e:
        log.warning("Price fetch error %s: %s" % (symbol, e))
    return 0.0

def fp(n):
    if n >= 1000: return "%.2f" % n
    if n >= 1:    return "%.4f" % n
    if n >= 0.01: return "%.6f" % n
    return "%.8f" % n

# ── Alert builders ────────────────────────────────────────────────────────────

def tp1_message(t, price):
    risk  = abs(t["entry"] - t["sl"])
    r_val = abs(t["tp1"] - t["entry"]) / risk if risk > 0 else 0
    return (
        "TP1 HIT — %s %s\n"
        "\n"
        "Pair:    %s/USDT\n"
        "TP1:     $%s\n"
        "Current: $%s\n"
        "R Earned: +%.2fR\n"
        "\n"
        "ACTION REQUIRED:\n"
        "1. Take 40%% of your position OFF now\n"
        "2. Move Stop Loss to BREAKEVEN ($%s)\n"
        "3. Let remaining 60%% run to TP2\n"
        "\n"
        "Time: %s UTC"
    ) % (
        t["direction"], t["symbol"].replace("USDT", ""),
        t["symbol"].replace("USDT", ""),
        fp(t["tp1"]), fp(price), r_val,
        fp(t["entry"]),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def tp2_message(t, price):
    risk  = abs(t["entry"] - t["sl"])
    r_val = abs(t["tp2"] - t["entry"]) / risk if risk > 0 else 0
    return (
        "TP2 HIT — %s %s\n"
        "\n"
        "Pair:     %s/USDT\n"
        "TP2:      $%s\n"
        "Current:  $%s\n"
        "R Earned: +%.2fR\n"
        "\n"
        "ACTION REQUIRED:\n"
        "1. Take 35%% more OFF now (75%% total closed)\n"
        "2. Move SL to just below TP1 ($%s)\n"
        "3. Let last 25%% run to TP3 ($%s)\n"
        "\n"
        "Time: %s UTC"
    ) % (
        t["direction"], t["symbol"].replace("USDT", ""),
        t["symbol"].replace("USDT", ""),
        fp(t["tp2"]), fp(price), r_val,
        fp(t["tp1"]),
        fp(t["tp3"]),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def tp3_message(t, price):
    risk  = abs(t["entry"] - t["sl"])
    r_val = abs(t["tp3"] - t["entry"]) / risk if risk > 0 else 0
    return (
        "TP3 HIT — FULL TARGET REACHED! %s %s\n"
        "\n"
        "Pair:     %s/USDT\n"
        "TP3:      $%s\n"
        "Current:  $%s\n"
        "R Earned: +%.2fR on final 25%%\n"
        "\n"
        "Close your remaining position now.\n"
        "Excellent trade — full target hit!\n"
        "\n"
        "Time: %s UTC"
    ) % (
        t["direction"], t["symbol"].replace("USDT", ""),
        t["symbol"].replace("USDT", ""),
        fp(t["tp3"]), fp(price), r_val,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def sl_message(t, price):
    return (
        "STOP LOSS HIT — %s %s\n"
        "\n"
        "Pair:    %s/USDT\n"
        "SL:      $%s\n"
        "Current: $%s\n"
        "Result:  -1R (controlled loss)\n"
        "\n"
        "This is normal — even a 75%% win rate\n"
        "means 1 in 4 trades hits SL.\n"
        "The system stays profitable long term.\n"
        "\n"
        "Do NOT revenge trade. Wait for the\n"
        "next signal from the scanner.\n"
        "\n"
        "Time: %s UTC"
    ) % (
        t["direction"], t["symbol"].replace("USDT", ""),
        t["symbol"].replace("USDT", ""),
        fp(t["sl"]), fp(price),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def expired_message(t, price):
    risk   = abs(t["entry"] - t["sl"])
    pnl    = (price - t["entry"]) if t["direction"] == "LONG" else (t["entry"] - price)
    r_val  = pnl / risk if risk > 0 else 0
    return (
        "TRADE EXPIRED — %s %s\n"
        "\n"
        "Pair:     %s/USDT\n"
        "Entry:    $%s\n"
        "Current:  $%s\n"
        "P&L:      %+.2fR\n"
        "\n"
        "Trade open for 48 hours — consider\n"
        "closing if thesis no longer valid.\n"
        "\n"
        "Time: %s UTC"
    ) % (
        t["direction"], t["symbol"].replace("USDT", ""),
        t["symbol"].replace("USDT", ""),
        fp(t["entry"]), fp(price), r_val,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

# ── Main monitoring loop ──────────────────────────────────────────────────────

async def monitor():
    log.info("TP Tracker starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "TP Hit Tracker Online!\n\n"
            "I will watch every signal and alert you the moment:\n"
            "  - TP1 is hit → take 40%%, move SL to breakeven\n"
            "  - TP2 is hit → take 35%%, trail SL\n"
            "  - TP3 is hit → close remaining 25%%\n"
            "  - SL is hit  → controlled loss alert\n\n"
            "Checking prices every 30 seconds.\n"
            "Trades auto-expire after 48 hours."
        )
    )

    while True:
        trades = load_trades()
        now    = time.time()
        updated = False

        for key, t in list(trades.items()):
            if t.get("closed"):
                continue

            price = get_price(t["symbol"])
            if price == 0:
                continue

            direction = t["direction"]
            hit       = None

            # Check levels in priority order
            if direction == "LONG":
                if price <= t["sl"] and not t.get("sl_hit"):
                    hit = "SL"
                elif price >= t["tp3"] and not t.get("tp3_hit"):
                    hit = "TP3"
                elif price >= t["tp2"] and not t.get("tp2_hit"):
                    hit = "TP2"
                elif price >= t["tp1"] and not t.get("tp1_hit"):
                    hit = "TP1"
            else:
                if price >= t["sl"] and not t.get("sl_hit"):
                    hit = "SL"
                elif price <= t["tp3"] and not t.get("tp3_hit"):
                    hit = "TP3"
                elif price <= t["tp2"] and not t.get("tp2_hit"):
                    hit = "TP2"
                elif price <= t["tp1"] and not t.get("tp1_hit"):
                    hit = "TP1"

            # Check expiry
            age_hours = (now - t["opened_at"]) / 3600
            if age_hours >= MAX_TRADE_HOURS and not t.get("expired_alerted"):
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=expired_message(t, price)
                    )
                    trades[key]["expired_alerted"] = True
                    updated = True
                    log.info("Expired alert: %s" % t["symbol"])
                except Exception as e:
                    log.error("Expired alert error: %s" % e)

            if not hit:
                continue

            try:
                if hit == "TP1":
                    await bot.send_message(chat_id=CHAT_ID, text=tp1_message(t, price))
                    trades[key]["tp1_hit"] = True
                elif hit == "TP2":
                    await bot.send_message(chat_id=CHAT_ID, text=tp2_message(t, price))
                    trades[key]["tp2_hit"] = True
                elif hit == "TP3":
                    await bot.send_message(chat_id=CHAT_ID, text=tp3_message(t, price))
                    trades[key]["tp3_hit"] = True
                    trades[key]["closed"]  = True
                elif hit == "SL":
                    await bot.send_message(chat_id=CHAT_ID, text=sl_message(t, price))
                    trades[key]["sl_hit"] = True
                    trades[key]["closed"] = True

                log.info("%s alert sent: %s %s" % (hit, t["symbol"], t["direction"]))
                updated = True
                await asyncio.sleep(1)

            except Exception as e:
                log.error("Alert send error %s: %s" % (t["symbol"], e))

        if updated:
            save_trades(trades)

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(monitor())
