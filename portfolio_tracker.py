"""
Portfolio Tracker — interactive Telegram bot for tracking open trades.

Commands:
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
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID          = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
BINANCE_BASE     = "https://fapi.binance.com"
PORTFOLIO_FILE   = "portfolio.json"
ALERT_COOLDOWN   = 3600    # 1 hour between same alert per symbol

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

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "PORTFOLIO TRACKER — COMMANDS\n\n"
        "/add SYMBOL DIRECTION ENTRY SL TP1 [TP2] [SIZE]\n"
        "  Example:\n"
        "  /add BTCUSDT LONG 65000 63000 70000 74000 100\n"
        "  (SIZE = USD amount in trade, optional)\n\n"
        "/portfolio\n"
        "  Show all open positions with live P&L\n\n"
        "/close SYMBOL\n"
        "  Remove a position (mark as closed)\n"
        "  Example: /close BTCUSDT\n\n"
        "/pnl\n"
        "  Quick profit/loss summary\n\n"
        "Auto-alerts when:\n"
        "  - Price within 1%% of your TP or SL\n"
        "  - Reminder to move SL after TP1 hit"
    )

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 5:
        await update.message.reply_text(
            "Usage: /add SYMBOL DIRECTION ENTRY SL TP1 [TP2] [SIZE_USD]\n"
            "Example: /add BTCUSDT LONG 65000 63000 70000 74000 100"
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
            await update.message.reply_text("Direction must be LONG or SHORT.")
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
        await update.message.reply_text(msg)
        log.info("Position added: %s %s @ %s" % (direction, symbol, entry))

    except ValueError:
        await update.message.reply_text(
            "Invalid numbers. Example:\n"
            "/add BTCUSDT LONG 65000 63000 70000"
        )

async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    portfolio = load_portfolio()
    if not portfolio:
        await update.message.reply_text(
            "No open positions.\n"
            "Add one with /add SYMBOL DIRECTION ENTRY SL TP1"
        )
        return

    lines = ["OPEN POSITIONS\n"]
    total_pnl_pct = 0
    count = 0

    for symbol, t in portfolio.items():
        price = get_price(symbol)
        if price == 0:
            lines.append("%s — price unavailable\n" % symbol)
            continue

        entry = t["entry"]
        if t["direction"] == "LONG":
            pnl_pct = (price - entry) / entry * 100
        else:
            pnl_pct = (entry - price) / entry * 100

        pnl_usd = (t["size_usd"] * pnl_pct / 100) if t["size_usd"] > 0 else 0
        sl_dist  = abs(price - t["sl"])   / price * 100
        tp1_dist = abs(price - t["tp1"])  / price * 100

        status = "IN PROFIT" if pnl_pct > 0 else "IN LOSS"
        pnl_sign = "+" if pnl_pct >= 0 else ""

        line = (
            "%s %s\n"
            "  Entry: $%s  Now: $%s\n"
            "  P&L:   %s%.2f%%"
        ) % (
            t["direction"], symbol.replace("USDT", ""),
            fp(entry), fp(price),
            pnl_sign, pnl_pct,
        )
        if pnl_usd != 0:
            line += "  ($%s%.2f)" % ("+" if pnl_usd >= 0 else "", pnl_usd)
        line += "\n"
        line += "  SL: %.2f%% away  |  TP1: %.2f%% away\n" % (sl_dist, tp1_dist)
        line += "  [%s]\n" % status

        lines.append(line)
        total_pnl_pct += pnl_pct
        count += 1

    if count > 1:
        lines.append("Total open positions: %d" % count)

    await update.message.reply_text("\n".join(lines))

async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /close SYMBOL\nExample: /close BTCUSDT")
        return

    symbol    = context.args[0].upper()
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    portfolio = load_portfolio()
    if symbol not in portfolio:
        await update.message.reply_text("%s not found in portfolio." % symbol)
        return

    t     = portfolio[symbol]
    price = get_price(symbol)
    entry = t["entry"]

    if price > 0:
        if t["direction"] == "LONG":
            pnl_pct = (price - entry) / entry * 100
        else:
            pnl_pct = (entry - price) / entry * 100
        pnl_usd = (t["size_usd"] * pnl_pct / 100) if t["size_usd"] > 0 else 0
        result_msg = "Closed at $%s  |  P&L: %+.2f%%%s" % (
            fp(price), pnl_pct,
            "  ($%+.2f)" % pnl_usd if pnl_usd != 0 else ""
        )
    else:
        result_msg = "Closed."

    del portfolio[symbol]
    save_portfolio(portfolio)
    await update.message.reply_text(
        "Position closed: %s %s\n%s" % (t["direction"], symbol.replace("USDT", ""), result_msg)
    )
    log.info("Position closed: %s" % symbol)

async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    portfolio = load_portfolio()
    if not portfolio:
        await update.message.reply_text("No open positions.")
        return

    winners = []
    losers  = []
    flat    = []

    for symbol, t in portfolio.items():
        price = get_price(symbol)
        if price == 0:
            continue
        if t["direction"] == "LONG":
            pnl_pct = (price - t["entry"]) / t["entry"] * 100
        else:
            pnl_pct = (t["entry"] - price) / t["entry"] * 100

        label = "%s %s: %+.2f%%" % (
            t["direction"], symbol.replace("USDT", ""), pnl_pct)
        if pnl_pct > 0.5:
            winners.append(label)
        elif pnl_pct < -0.5:
            losers.append(label)
        else:
            flat.append(label)

    msg = "QUICK P&L SUMMARY\n\n"
    if winners:
        msg += "In Profit:\n" + "\n".join("  " + w for w in winners) + "\n\n"
    if losers:
        msg += "In Loss:\n"   + "\n".join("  " + l for l in losers)  + "\n\n"
    if flat:
        msg += "Flat:\n"      + "\n".join("  " + f for f in flat)    + "\n\n"
    if not winners and not losers and not flat:
        msg += "Could not fetch prices."

    await update.message.reply_text(msg)

# ── Background price monitor ──────────────────────────────────────────────────

async def price_monitor(bot):
    """Check all positions every 5 minutes and send proximity alerts."""
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

            # Alert: price within 1% of SL
            sl_dist_pct = abs(price - t["sl"]) / price * 100
            sl_key      = "sl_%s" % symbol
            last_sl_alert = t["sl_alerts"].get(sl_key, 0)
            if sl_dist_pct < 1.0 and now - last_sl_alert > ALERT_COOLDOWN:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=(
                            "SL APPROACHING — %s %s\n\n"
                            "Current: $%s\n"
                            "SL:      $%s  (%.2f%% away)\n\n"
                            "Consider your position — SL is very close."
                        ) % (
                            t["direction"], symbol.replace("USDT", ""),
                            fp(price), fp(t["sl"]), sl_dist_pct
                        )
                    )
                    portfolio[symbol]["sl_alerts"][sl_key] = now
                    save_portfolio(portfolio)
                    log.info("SL alert: %s" % symbol)
                except Exception as e:
                    log.error("SL alert error: %s" % e)

            # Alert: price within 1% of TP1
            tp1_dist_pct = abs(price - t["tp1"]) / price * 100
            tp1_key      = "tp1_%s" % symbol
            last_tp_alert = t["tp_alerts"].get(tp1_key, 0)
            if tp1_dist_pct < 1.0 and now - last_tp_alert > ALERT_COOLDOWN:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=(
                            "TP1 APPROACHING — %s %s\n\n"
                            "Current: $%s\n"
                            "TP1:     $%s  (%.2f%% away)\n\n"
                            "Get ready to take 40%% profit\n"
                            "and move SL to breakeven."
                        ) % (
                            t["direction"], symbol.replace("USDT", ""),
                            fp(price), fp(t["tp1"]), tp1_dist_pct
                        )
                    )
                    portfolio[symbol]["tp_alerts"][tp1_key] = now
                    save_portfolio(portfolio)
                    log.info("TP1 alert: %s" % symbol)
                except Exception as e:
                    log.error("TP1 alert error: %s" % e)

            # Reminder: move SL to breakeven if TP1 passed
            tp1_hit = (
                (t["direction"] == "LONG"  and price >= t["tp1"]) or
                (t["direction"] == "SHORT" and price <= t["tp1"])
            )
            if tp1_hit and not t.get("be_alerted"):
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=(
                            "MOVE SL TO BREAKEVEN — %s %s\n\n"
                            "TP1 has been passed.\n"
                            "Move your Stop Loss to $%s (entry)\n"
                            "to lock in a risk-free trade.\n\n"
                            "Current price: $%s"
                        ) % (
                            t["direction"], symbol.replace("USDT", ""),
                            fp(t["entry"]), fp(price)
                        )
                    )
                    portfolio[symbol]["be_alerted"] = True
                    save_portfolio(portfolio)
                    log.info("BE reminder: %s" % symbol)
                except Exception as e:
                    log.error("BE alert error: %s" % e)

# ── Main ──────────────────────────────────────────────────────────────────────

async def post_init(application):
    bot = application.bot
    asyncio.create_task(price_monitor(bot))
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

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("add",       cmd_add))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("close",     cmd_close))
    app.add_handler(CommandHandler("pnl",       cmd_pnl))
    log.info("Portfolio Tracker polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
