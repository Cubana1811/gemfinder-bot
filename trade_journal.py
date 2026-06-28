"""
Trade Journal — logs every signal and sends a daily performance summary
to Telegram at 20:00 UTC every day.

Reads active_trades.json (written by tv_scanner, updated by tp_tracker)
and maintains a persistent journal in trade_journal.json.
"""

import os
import json
import time
import logging
import asyncio
from telegram import Bot
from datetime import datetime, timezone

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID         = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
TRADES_FILE     = "active_trades.json"
JOURNAL_FILE    = "trade_journal.json"
SUMMARY_HOUR    = 20    # send daily summary at 20:00 UTC
CHECK_INTERVAL  = 60    # check every 60 seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Journal store ─────────────────────────────────────────────────────────────

def load_journal():
    if not os.path.exists(JOURNAL_FILE):
        return {"trades": [], "last_summary_date": ""}
    try:
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"trades": [], "last_summary_date": ""}

def save_journal(journal):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(journal, f, indent=2)

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return {}
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

# ── Sync active trades into journal ──────────────────────────────────────────

def sync_trades(journal, trades):
    """Copy any new or updated trades from active_trades into journal."""
    journal_keys = {t["key"] for t in journal["trades"]}
    updated = False

    for key, t in trades.items():
        if key not in journal_keys:
            # New trade — add to journal
            journal["trades"].append({
                "key":        key,
                "symbol":     t["symbol"],
                "direction":  t["direction"],
                "entry":      t["entry"],
                "sl":         t["sl"],
                "tp1":        t["tp1"],
                "tp2":        t["tp2"],
                "tp3":        t["tp3"],
                "score":      t.get("score", 0),
                "tier":       t.get("tier", ""),
                "opened_at":  t.get("opened_at", time.time()),
                "outcome":    "OPEN",
                "pnl_r":      0.0,
                "closed_at":  None,
            })
            updated = True
            log.info("Journal: new trade logged %s %s" % (t["symbol"], t["direction"]))
        else:
            # Update outcome if trade has closed
            for j in journal["trades"]:
                if j["key"] == key and j["outcome"] == "OPEN":
                    risk = abs(t["entry"] - t["sl"])
                    if t.get("tp3_hit"):
                        j["outcome"] = "TP3"
                        j["pnl_r"]   = abs(t["tp3"] - t["entry"]) / risk if risk else 0
                        j["closed_at"] = time.time()
                        updated = True
                    elif t.get("tp2_hit"):
                        j["outcome"] = "TP2"
                        j["pnl_r"]   = abs(t["tp2"] - t["entry"]) / risk if risk else 0
                        j["closed_at"] = time.time()
                        updated = True
                    elif t.get("tp1_hit") and not t.get("tp2_hit"):
                        j["outcome"] = "TP1"
                        j["pnl_r"]   = abs(t["tp1"] - t["entry"]) / risk if risk else 0
                        updated = True
                    elif t.get("sl_hit"):
                        j["outcome"] = "SL"
                        j["pnl_r"]   = -1.0
                        j["closed_at"] = time.time()
                        updated = True

    return updated

# ── Summary builder ───────────────────────────────────────────────────────────

def build_daily_summary(journal):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_trades = [
        t for t in journal["trades"]
        if datetime.fromtimestamp(t["opened_at"], tz=timezone.utc).strftime("%Y-%m-%d") == today
    ]

    # All-time stats
    all_closed  = [t for t in journal["trades"] if t["outcome"] not in ("OPEN",)]
    all_wins    = [t for t in all_closed if t["outcome"] in ("TP1", "TP2", "TP3")]
    all_losses  = [t for t in all_closed if t["outcome"] == "SL"]
    all_net_r   = sum(t["pnl_r"] for t in all_closed)
    all_wr      = len(all_wins) / len(all_closed) * 100 if all_closed else 0

    # Today stats
    today_closed = [t for t in today_trades if t["outcome"] not in ("OPEN",)]
    today_wins   = [t for t in today_closed if t["outcome"] in ("TP1", "TP2", "TP3")]
    today_losses = [t for t in today_closed if t["outcome"] == "SL"]
    today_open   = [t for t in today_trades if t["outcome"] == "OPEN"]
    today_net_r  = sum(t["pnl_r"] for t in today_closed)

    # Today trade list
    if today_trades:
        trade_lines = []
        for t in today_trades:
            if t["outcome"] == "OPEN":
                status = "OPEN"
            elif t["outcome"] == "SL":
                status = "SL (-1R)"
            elif t["outcome"] == "TP3":
                status = "TP3 (+%.2fR)" % t["pnl_r"]
            elif t["outcome"] == "TP2":
                status = "TP2 (+%.2fR)" % t["pnl_r"]
            elif t["outcome"] == "TP1":
                status = "TP1 (+%.2fR)" % t["pnl_r"]
            else:
                status = t["outcome"]
            trade_lines.append("  %s %s [%s] %s" % (
                t["direction"], t["symbol"].replace("USDT", ""),
                t["tier"][:1] if t["tier"] else "B",
                status
            ))
        trades_text = "\n".join(trade_lines)
    else:
        trades_text = "  No signals sent today"

    # P&L bar (visual)
    if today_net_r > 0:
        pnl_bar = "+" * min(int(today_net_r), 10)
        pnl_color = "PROFIT"
    elif today_net_r < 0:
        pnl_bar = "-" * min(int(abs(today_net_r)), 10)
        pnl_color = "LOSS"
    else:
        pnl_bar = "="
        pnl_color = "FLAT"

    return (
        "DAILY TRADE JOURNAL — %s\n"
        "\n"
        "=== TODAY ===\n"
        "%s\n"
        "\n"
        "Today Results:\n"
        "  Signals:  %d total (%d closed, %d open)\n"
        "  Wins:     %d  |  Losses: %d\n"
        "  Net P&L:  %+.2fR  [%s] %s\n"
        "\n"
        "=== ALL TIME ===\n"
        "  Total closed trades: %d\n"
        "  Wins: %d  |  Losses: %d\n"
        "  Win Rate: %.1f%%\n"
        "  Net R earned: %+.2fR\n"
        "  Est. profit (2%% risk/trade): %+.1f%% account\n"
        "\n"
        "Keep following the rules.\n"
        "Win rate builds over many trades."
    ) % (
        today,
        trades_text,
        len(today_trades), len(today_closed), len(today_open),
        len(today_wins), len(today_losses),
        today_net_r, pnl_color, pnl_bar,
        len(all_closed),
        len(all_wins), len(all_losses),
        all_wr,
        all_net_r,
        all_net_r * 2,   # each R = 2% of account
    )

def build_new_trade_log(t):
    """Short log message sent immediately when a new signal is detected."""
    return (
        "TRADE LOGGED\n"
        "%s %s | Score: %d | %s\n"
        "Entry: $%.4f  SL: $%.4f\n"
        "TP1: $%.4f  TP2: $%.4f  TP3: $%.4f\n"
        "Watching for exits..."
    ) % (
        t["direction"], t["symbol"].replace("USDT", ""),
        t["score"], t["tier"],
        t["entry"], t["sl"],
        t["tp1"], t["tp2"], t["tp3"],
    )

# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    log.info("Trade Journal starting...")
    bot     = Bot(token=TELEGRAM_TOKEN)
    journal = load_journal()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Trade Journal Online!\n\n"
            "I will:\n"
            "  - Log every signal automatically\n"
            "  - Track TP1/TP2/TP3/SL outcomes\n"
            "  - Send you a daily summary at 20:00 UTC\n"
            "  - Track your win rate and total R earned\n\n"
            "All-time journal: %d trades recorded so far."
        ) % len(journal["trades"])
    )

    notified_keys = {t["key"] for t in journal["trades"]}

    while True:
        now    = datetime.now(timezone.utc)
        trades = load_trades()

        # Sync new trades into journal
        updated = sync_trades(journal, trades)
        if updated:
            save_journal(journal)

        # Notify about brand new trades (just logged)
        for t in journal["trades"]:
            if t["key"] not in notified_keys:
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=build_new_trade_log(t)
                    )
                    notified_keys.add(t["key"])
                    log.info("Logged new trade: %s %s" % (t["symbol"], t["direction"]))
                    await asyncio.sleep(1)
                except Exception as e:
                    log.error("Log notify error: %s" % e)

        # Daily summary at SUMMARY_HOUR UTC
        today_str = now.strftime("%Y-%m-%d")
        if now.hour == SUMMARY_HOUR and journal["last_summary_date"] != today_str:
            try:
                summary = build_daily_summary(journal)
                await bot.send_message(chat_id=CHAT_ID, text=summary)
                journal["last_summary_date"] = today_str
                save_journal(journal)
                log.info("Daily summary sent for %s" % today_str)
            except Exception as e:
                log.error("Summary send error: %s" % e)

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
