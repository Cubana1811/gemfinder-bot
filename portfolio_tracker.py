"""
Portfolio Tracker — interactive Telegram bot for tracking open trades.

Commands (send these to your bot in Telegram):
  /add SYMBOL DIRECTION ENTRY SL TP1 [TP2] [SIZE_USD]
      e.g. /add BTCUSDT LONG 65000 63000 70000 72000 100
  /portfolio   — show all open positions with live P&L
  /close SYMBOL — remove a position
  /pnl          — quick profit/loss summary
  /help         — show all commands

Auto-alerts every 5 minutes:
  - Price within 1% of TP1 or TP2
  - Price within 1% of SL
  - Reminder to move SL to breakeven after TP1 passed
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
PORTFOLIO_FILE   = "portfolio.json"
ALERT_COOLDOWN   = 3600    # 1 hour between same alert per symbol
POLL_INTERVAL    = 2       # seconds between update polls

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Portfolio store ───────────────────────────────────────────────────────────

def load_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        return {}
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(p, f, indent=2)

# ── Price fetch ───────────────────────────────────────────────────────────────

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

def fp(n):
    if n >= 1000: return "%.2f" % n
    if n >= 1:    return "%.4f" % n
    if n >= 0.01: return "%.6f" % n
    return "%.8f" % n

# ── Command handlers ──────────────────────────────────────────────────────────

async def handle_help(bot, chat_id):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "PORTFOLIO TRACKER — COMMANDS\n\n"
            "/add SYMBOL DIRECTION ENTRY SL TP1 [TP2] [SIZE]\n"
            "  Example:\n"
            "  /add BTCUSDT LONG 65000 63000 70000 74000 100\n"
            "  (SIZE = USD amount in trade, optional)\n\n"
            "/portfolio\n"
            "  Show all open positions with live P&L\n\n"
            "/close SYMBOL\n"
            "  Remove a position\n"
            "  Example: /close BTCUSDT\n\n"
            "/pnl\n"
            "  Quick profit/loss summary\n\n"
            "Auto-alerts when price is within\n"
            "1%% of your TP or SL."
        )
    )

async def handle_add(bot, chat_id, args):
    if len(args) < 5:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Usage: /add SYMBOL DIRECTION ENTRY SL TP1 [TP2] [SIZE_USD]\n"
                "Example: /add BTCUSDT LONG 65000 63000 70000 74000 100"
            )
        )
        return

    try:
        symbol    = args[0].upper()
        direction = args[1].upper()
        entry     = float(args[2])
        sl        = float(args[3])
        tp1       = float(args[4])
        tp2       = float(args[5]) if len(args) > 5 else None
        size_usd  = float(args[6]) if len(args) > 6 else 0.0

        if direction not in ("LONG", "SHORT"):
            await bot.send_message(chat_id=chat_id,
                                   text="Direction must be LONG or SHORT.")
            return

        if not symbol.endswith("USDT"):
            symbol = symbol + "USDT"

        portfolio = load_portfolio()
        portfolio[symbol] = {
            "symbol":     symbol,
            "direction":  direction,
            "entry":      entry,
            "sl":         sl,
            "tp1":        tp1,
            "tp2":        tp2,
            "size_usd":   size_usd,
            "added_at":   time.time(),
            "sl_alerts":  {},
            "tp_alerts":  {},
            "be_alerted": False,
        }
        save_portfolio(portfolio)

        risk_pct = abs(entry - sl) / entry * 100
        tp1_pct  = abs(tp1 - entry) / entry * 100
        rr       = abs(tp1 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

        msg = (
            "Position Added!\n\n"
            "%s %s\n"
            "Entry:  $%s\n"
            "SL:     $%s  (-%.2f%%)\n"
            "TP1:    $%s  (+%.2f%%)\n"
            "%s"
            "R/R:    %.2fx\n"
            "%s"
            "\nI will alert you when price is\n"
            "within 1%% of your TP or SL."
        ) % (
            direction, symbol.replace("USDT", ""),
            fp(entry),
            fp(sl), risk_pct,
            fp(tp1), tp1_pct,
            "TP2:    $%s\n" % fp(tp2) if tp2 else "",
            rr,
            "Size:   $%.2f\n" % size_usd if size_usd > 0 else "",
        )
        await bot.send_message(chat_id=chat_id, text=msg)
        log.info("Position added: %s %s @ %s" % (direction, symbol, entry))

    except (ValueError, IndexError):
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Invalid numbers. Example:\n"
                "/add BTCUSDT LONG 65000 63000 70000"
            )
        )

async def handle_portfolio(bot, chat_id):
    portfolio = load_portfolio()
    if not portfolio:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "No open positions.\n"
                "Add one with:\n"
                "/add SYMBOL DIRECTION ENTRY SL TP1"
            )
        )
        return

    lines = ["OPEN POSITIONS\n"]

    for symbol, t in portfolio.items():
        price = get_price(symbol)
        if price == 0:
            lines.append("%s — price unavailable\n" % symbol)
            continue

        entry = t["entry"]
        pnl_pct = (
            (price - entry) / entry * 100 if t["direction"] == "LONG"
            else (entry - price) / entry * 100
        )
        pnl_usd  = (t["size_usd"] * pnl_pct / 100) if t["size_usd"] > 0 else 0
        sl_dist  = abs(price - t["sl"])  / price * 100
        tp1_dist = abs(price - t["tp1"]) / price * 100
        status   = "IN PROFIT" if pnl_pct > 0 else "IN LOSS"

        line = (
            "%s %s\n"
            "  Entry: $%s  Now: $%s\n"
            "  P&L:   %+.2f%%%s\n"
            "  SL: %.2f%% away  TP1: %.2f%% away\n"
            "  [%s]\n"
        ) % (
            t["direction"], symbol.replace("USDT", ""),
            fp(entry), fp(price),
            pnl_pct,
            "  ($%+.2f)" % pnl_usd if pnl_usd != 0 else "",
            sl_dist, tp1_dist,
            status,
        )
        lines.append(line)

    await bot.send_message(chat_id=chat_id, text="\n".join(lines))

async def handle_close(bot, chat_id, args):
    if not args:
        await bot.send_message(chat_id=chat_id,
                               text="Usage: /close SYMBOL\nExample: /close BTCUSDT")
        return

    symbol = args[0].upper()
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    portfolio = load_portfolio()
    if symbol not in portfolio:
        await bot.send_message(chat_id=chat_id,
                               text="%s not found in your portfolio." % symbol)
        return

    t     = portfolio[symbol]
    price = get_price(symbol)
    entry = t["entry"]

    if price > 0:
        pnl_pct = (
            (price - entry) / entry * 100 if t["direction"] == "LONG"
            else (entry - price) / entry * 100
        )
        pnl_usd = (t["size_usd"] * pnl_pct / 100) if t["size_usd"] > 0 else 0
        result  = "Closed at $%s  P&L: %+.2f%%%s" % (
            fp(price), pnl_pct,
            "  ($%+.2f)" % pnl_usd if pnl_usd != 0 else ""
        )
    else:
        result = "Closed."

    del portfolio[symbol]
    save_portfolio(portfolio)
    await bot.send_message(
        chat_id=chat_id,
        text="Position closed: %s %s\n%s" % (
            t["direction"], symbol.replace("USDT", ""), result)
    )

async def handle_pnl(bot, chat_id):
    portfolio = load_portfolio()
    if not portfolio:
        await bot.send_message(chat_id=chat_id, text="No open positions.")
        return

    winners, losers, flat = [], [], []

    for symbol, t in portfolio.items():
        price = get_price(symbol)
        if price == 0:
            continue
        pnl_pct = (
            (price - t["entry"]) / t["entry"] * 100 if t["direction"] == "LONG"
            else (t["entry"] - price) / t["entry"] * 100
        )
        label = "%s %s: %+.2f%%" % (
            t["direction"], symbol.replace("USDT", ""), pnl_pct)
        if pnl_pct > 0.5:   winners.append(label)
        elif pnl_pct < -0.5: losers.append(label)
        else:                flat.append(label)

    msg = "QUICK P&L SUMMARY\n\n"
    if winners: msg += "In Profit:\n"  + "\n".join("  " + w for w in winners) + "\n\n"
    if losers:  msg += "In Loss:\n"    + "\n".join("  " + l for l in losers)  + "\n\n"
    if flat:    msg += "Flat:\n"       + "\n".join("  " + f for f in flat)    + "\n\n"
    if not winners and not losers and not flat:
        msg += "Could not fetch prices right now."

    await bot.send_message(chat_id=chat_id, text=msg)

# ── Command dispatcher ────────────────────────────────────────────────────────

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
    elif cmd == "/add":
        await handle_add(bot, chat_id, args)
    elif cmd == "/portfolio":
        await handle_portfolio(bot, chat_id)
    elif cmd == "/close":
        await handle_close(bot, chat_id, args)
    elif cmd == "/pnl":
        await handle_pnl(bot, chat_id)

# ── Background price monitor ──────────────────────────────────────────────────

async def price_monitor(bot):
    while True:
        await asyncio.sleep(300)
        portfolio = load_portfolio()
        if not portfolio:
            continue

        for symbol, t in list(portfolio.items()):
            price = get_price(symbol)
            if price == 0:
                continue
            now = time.time()

            # SL approaching
            sl_dist = abs(price - t["sl"]) / price * 100
            sl_key  = "sl_%s" % symbol
            if sl_dist < 1.0 and now - t["sl_alerts"].get(sl_key, 0) > ALERT_COOLDOWN:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=(
                            "SL APPROACHING — %s %s\n\n"
                            "Current: $%s\n"
                            "SL:      $%s  (%.2f%% away)\n\n"
                            "SL is very close — review your position."
                        ) % (t["direction"], symbol.replace("USDT", ""),
                             fp(price), fp(t["sl"]), sl_dist)
                    )
                    portfolio[symbol]["sl_alerts"][sl_key] = now
                    save_portfolio(portfolio)
                except Exception as e:
                    log.error("SL alert: %s" % e)

            # TP1 approaching
            tp1_dist = abs(price - t["tp1"]) / price * 100
            tp1_key  = "tp1_%s" % symbol
            if tp1_dist < 1.0 and now - t["tp_alerts"].get(tp1_key, 0) > ALERT_COOLDOWN:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=(
                            "TP1 APPROACHING — %s %s\n\n"
                            "Current: $%s\n"
                            "TP1:     $%s  (%.2f%% away)\n\n"
                            "Get ready to take 40%% profit\n"
                            "and move SL to breakeven ($%s)."
                        ) % (t["direction"], symbol.replace("USDT", ""),
                             fp(price), fp(t["tp1"]), tp1_dist, fp(t["entry"]))
                    )
                    portfolio[symbol]["tp_alerts"][tp1_key] = now
                    save_portfolio(portfolio)
                except Exception as e:
                    log.error("TP1 alert: %s" % e)

            # Move SL to breakeven reminder
            tp1_passed = (
                (t["direction"] == "LONG"  and price >= t["tp1"]) or
                (t["direction"] == "SHORT" and price <= t["tp1"])
            )
            if tp1_passed and not t.get("be_alerted"):
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=(
                            "MOVE SL TO BREAKEVEN — %s %s\n\n"
                            "TP1 has been passed!\n"
                            "Move your Stop Loss to entry price:\n"
                            "$%s\n\n"
                            "This locks in a risk-free trade.\n"
                            "Current price: $%s"
                        ) % (t["direction"], symbol.replace("USDT", ""),
                             fp(t["entry"]), fp(price))
                    )
                    portfolio[symbol]["be_alerted"] = True
                    save_portfolio(portfolio)
                except Exception as e:
                    log.error("BE alert: %s" % e)

# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    log.info("Portfolio Tracker starting...")
    bot    = Bot(token=TELEGRAM_TOKEN)
    offset = 0

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Portfolio Tracker Online!\n\n"
            "Commands:\n"
            "  /add SYMBOL DIRECTION ENTRY SL TP1\n"
            "  /portfolio — live P&L for all positions\n"
            "  /close SYMBOL — remove a position\n"
            "  /pnl — quick summary\n"
            "  /help — full guide\n\n"
            "Example:\n"
            "  /add BTCUSDT LONG 65000 63000 70000\n\n"
            "I check prices every 5 minutes and\n"
            "alert you when targets are close."
        )
    )

    # Start background price monitor
    asyncio.create_task(price_monitor(bot))

    # Manual update polling loop
    while True:
        try:
            updates = await bot.get_updates(
                offset=offset, timeout=30, allowed_updates=["message"])
            for update in updates:
                offset = update.update_id + 1
                if update.message:
                    raw = update.message.to_dict()
                    await dispatch(bot, raw)
        except Exception as e:
            log.error("Poll error: %s" % e)
            await asyncio.sleep(5)

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
