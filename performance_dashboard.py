"""
Signal Performance Dashboard — tracks and reports your trading statistics.

Reads trade_journal.json (written by trade_journal.py) and gives you
a full breakdown of your system's performance.

Commands:
  /stats      — overall win rate, profit factor, net R, best streak
  /breakdown  — win rate by coin, by direction (LONG/SHORT), by tier
  /recent     — last 10 closed trades with outcomes
  /best       — top 5 performing coins
  /worst      — worst 5 performing coins
  /today      — today's trades and P&L
  /weekly     — this week's summary
  /reset      — clear all stats (asks for confirmation)
  /help

Also sends a weekly performance report every Sunday at 08:00 UTC.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from telegram import Bot

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID          = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
JOURNAL_FILE     = "trade_journal.json"
TRADES_FILE      = "active_trades.json"
CHECK_INTERVAL   = 60
POLL_INTERVAL    = 2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Data loaders ──────────────────────────────────────────────────────────────

def load_journal():
    if not os.path.exists(JOURNAL_FILE):
        return {}
    try:
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return {}
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

# ── Stats engine ──────────────────────────────────────────────────────────────

def get_closed_trades():
    """Return list of closed trades from active_trades.json, sorted by open time."""
    trades = load_trades()
    closed = [t for t in trades.values() if t.get("closed")]
    closed.sort(key=lambda t: t.get("opened_at", 0))
    return closed

def get_all_trades():
    trades = load_trades()
    all_t = list(trades.values())
    all_t.sort(key=lambda t: t.get("opened_at", 0))
    return all_t

def compute_stats(trade_list):
    if not trade_list:
        return None

    wins   = [t for t in trade_list if t.get("result") == "WIN"]
    losses = [t for t in trade_list if t.get("result") == "LOSS"]
    open_t = [t for t in trade_list if not t.get("closed")]

    total_closed = len(wins) + len(losses)
    win_rate     = len(wins) / total_closed * 100 if total_closed > 0 else 0

    # Net R (each win = +2R assuming 1:2 RR minimum, each loss = -1R)
    # Use actual R multiples if stored, else assume fixed
    def r_value(t):
        return t.get("r_multiple", 2.0 if t.get("result") == "WIN" else -1.0)

    net_r    = sum(r_value(t) for t in wins + losses)
    gross_w  = sum(r_value(t) for t in wins)
    gross_l  = abs(sum(r_value(t) for t in losses))
    pf       = gross_w / gross_l if gross_l > 0 else gross_w if gross_w > 0 else 0

    # Streaks
    results  = [t.get("result") for t in sorted(wins + losses, key=lambda x: x.get("opened_at", 0))]
    best_win_streak  = cur_win = max_win = 0
    worst_loss_streak = cur_loss = max_loss = 0
    for r in results:
        if r == "WIN":
            cur_win  += 1
            cur_loss  = 0
            max_win   = max(max_win, cur_win)
        elif r == "LOSS":
            cur_loss  += 1
            cur_win   = 0
            max_loss  = max(max_loss, cur_loss)

    # Current streak
    cur_streak = 0
    cur_type   = ""
    for r in reversed(results):
        if cur_type == "":
            cur_type = r
        if r == cur_type:
            cur_streak += 1
        else:
            break

    return {
        "total":      len(trade_list),
        "closed":     total_closed,
        "wins":       len(wins),
        "losses":     len(losses),
        "open":       len(open_t),
        "win_rate":   win_rate,
        "net_r":      net_r,
        "profit_factor": pf,
        "best_win_streak":   max_win,
        "worst_loss_streak": max_loss,
        "cur_streak":  cur_streak,
        "cur_type":    cur_type,
    }

def breakdown_by_coin(trades):
    by_coin = defaultdict(list)
    for t in trades:
        if t.get("closed") and t.get("result"):
            by_coin[t["symbol"].replace("USDT", "")].append(t)
    result = {}
    for coin, tlist in by_coin.items():
        wins = sum(1 for t in tlist if t.get("result") == "WIN")
        result[coin] = {"total": len(tlist), "wins": wins,
                        "wr": wins / len(tlist) * 100}
    return dict(sorted(result.items(), key=lambda x: -x[1]["wr"]))

def breakdown_by_direction(trades):
    longs  = [t for t in trades if t.get("closed") and t.get("direction") == "LONG"]
    shorts = [t for t in trades if t.get("closed") and t.get("direction") == "SHORT"]
    def wr(lst):
        w = sum(1 for t in lst if t.get("result") == "WIN")
        return w / len(lst) * 100 if lst else 0
    return {
        "LONG":  {"total": len(longs),  "wr": wr(longs)},
        "SHORT": {"total": len(shorts), "wr": wr(shorts)},
    }

def breakdown_by_tier(trades):
    by_tier = defaultdict(list)
    for t in trades:
        if t.get("closed") and t.get("result"):
            tier = t.get("tier", "UNKNOWN")
            by_tier[tier].append(t)
    result = {}
    for tier, tlist in by_tier.items():
        wins = sum(1 for t in tlist if t.get("result") == "WIN")
        result[tier] = {"total": len(tlist), "wins": wins,
                        "wr": wins / len(tlist) * 100}
    return dict(sorted(result.items()))

# ── Message builders ──────────────────────────────────────────────────────────

def bar(pct, width=10):
    filled = round(pct / 100 * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"

def build_stats_msg(trades):
    s = compute_stats(trades)
    if not s or s["closed"] == 0:
        return "No closed trades yet.\nTrades are logged automatically when tv_scanner fires a signal."

    streak_line = ""
    if s["cur_streak"] > 0 and s["cur_type"]:
        streak_line = "Current:   %d %s streak\n" % (s["cur_streak"], s["cur_type"])

    acct_growth = s["net_r"] * 2  # 1R = 2% account risk

    return (
        "PERFORMANCE DASHBOARD\n"
        "\n"
        "=== OVERVIEW ===\n"
        "Total signals: %d\n"
        "Closed trades: %d  (Open: %d)\n"
        "Wins:  %d  |  Losses: %d\n"
        "\n"
        "=== KEY METRICS ===\n"
        "Win Rate:      %.1f%%  %s\n"
        "Net R:         %+.1fR\n"
        "Acct Growth:   %+.1f%%  (at 2%% risk/trade)\n"
        "Profit Factor: %.2fx\n"
        "\n"
        "=== STREAKS ===\n"
        "Best win streak:   %d\n"
        "Worst loss streak: %d\n"
        "%s"
        "\n"
        "Use /breakdown for coin/direction details.\n"
        "Use /recent for last 10 trades."
    ) % (
        s["total"], s["closed"], s["open"],
        s["wins"], s["losses"],
        s["win_rate"], bar(s["win_rate"]),
        s["net_r"],
        acct_growth,
        s["profit_factor"],
        s["best_win_streak"],
        s["worst_loss_streak"],
        streak_line,
    )

def build_breakdown_msg(trades):
    by_coin = breakdown_by_coin(trades)
    by_dir  = breakdown_by_direction(trades)
    by_tier = breakdown_by_tier(trades)

    lines = ["PERFORMANCE BREAKDOWN\n"]

    lines.append("=== BY DIRECTION ===")
    for d, info in by_dir.items():
        if info["total"] > 0:
            lines.append("%-6s  %d trades  %.1f%% WR  %s" % (
                d, info["total"], info["wr"], bar(info["wr"], 8)))

    if by_tier:
        lines.append("\n=== BY TIER ===")
        for tier, info in by_tier.items():
            lines.append("%-10s  %d trades  %.1f%% WR  %s" % (
                tier, info["total"], info["wr"], bar(info["wr"], 8)))

    if by_coin:
        lines.append("\n=== BY COIN (top 10) ===")
        for coin, info in list(by_coin.items())[:10]:
            lines.append("%-8s  %d/%d  %.1f%% WR" % (
                coin, info["wins"], info["total"], info["wr"]))

    return "\n".join(lines)

def build_recent_msg(trades):
    closed = [t for t in trades if t.get("closed") and t.get("result")]
    if not closed:
        return "No closed trades yet."
    recent = sorted(closed, key=lambda t: t.get("opened_at", 0), reverse=True)[:10]
    lines  = ["LAST %d CLOSED TRADES\n" % len(recent)]
    for t in recent:
        ts    = datetime.fromtimestamp(t.get("opened_at", 0), tz=timezone.utc).strftime("%m/%d")
        coin  = t["symbol"].replace("USDT", "")
        res   = "WIN " if t.get("result") == "WIN" else "LOSS"
        r_val = t.get("r_multiple", "")
        r_str = ("  (%+.1fR)" % r_val) if r_val != "" else ""
        lines.append("%s  %-6s  %s  %s%s" % (ts, coin, t["direction"], res, r_str))
    return "\n".join(lines)

def build_top_coins_msg(trades, worst=False):
    by_coin = breakdown_by_coin(trades)
    if not by_coin:
        return "No closed trades yet."
    min_trades = 2
    filtered = {k: v for k, v in by_coin.items() if v["total"] >= min_trades}
    if not filtered:
        filtered = by_coin
    sorted_coins = sorted(filtered.items(), key=lambda x: x[1]["wr"], reverse=not worst)[:5]
    label = "WORST" if worst else "BEST"
    lines = ["%s 5 COINS\n" % label]
    for coin, info in sorted_coins:
        lines.append("%-8s  %d/%d wins  %.1f%% WR  %s" % (
            coin, info["wins"], info["total"], info["wr"], bar(info["wr"], 8)))
    return "\n".join(lines)

def build_today_msg(trades):
    today = datetime.now(timezone.utc).date()
    today_trades = [
        t for t in trades
        if datetime.fromtimestamp(t.get("opened_at", 0), tz=timezone.utc).date() == today
    ]
    if not today_trades:
        return "No trades opened today."

    closed_today = [t for t in today_trades if t.get("closed") and t.get("result")]
    wins   = sum(1 for t in closed_today if t.get("result") == "WIN")
    losses = sum(1 for t in closed_today if t.get("result") == "LOSS")
    net_r  = sum(t.get("r_multiple", 2.0 if t.get("result") == "WIN" else -1.0)
                 for t in closed_today)

    lines = ["TODAY — %s UTC\n" % today.strftime("%Y-%m-%d")]
    lines.append("Signals:  %d" % len(today_trades))
    lines.append("Closed:   %d  (W:%d / L:%d)" % (len(closed_today), wins, losses))
    if closed_today:
        lines.append("Net R:    %+.1fR  (%+.1f%% acct)" % (net_r, net_r * 2))

    open_today = [t for t in today_trades if not t.get("closed")]
    if open_today:
        lines.append("\nOpen today:")
        for t in open_today:
            coin = t["symbol"].replace("USDT", "")
            lines.append("  %s %s @ $%.2f" % (t["direction"], coin, t["entry"]))

    return "\n".join(lines)

def build_weekly_msg(trades):
    now      = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    week_trades = [
        t for t in trades
        if datetime.fromtimestamp(t.get("opened_at", 0), tz=timezone.utc) >= week_ago
    ]
    s = compute_stats(week_trades)
    if not s or s["closed"] == 0:
        return "No closed trades this week."

    acct_growth = s["net_r"] * 2
    return (
        "WEEKLY REPORT — last 7 days\n"
        "\n"
        "Signals:  %d\n"
        "Closed:   %d  (W:%d / L:%d)\n"
        "Win Rate: %.1f%%  %s\n"
        "Net R:    %+.1fR\n"
        "Account:  %+.1f%%  (at 2%% risk)\n"
        "PF:       %.2fx\n"
        "\n"
        "Use /breakdown for full details."
    ) % (
        s["total"], s["closed"], s["wins"], s["losses"],
        s["win_rate"], bar(s["win_rate"]),
        s["net_r"],
        acct_growth,
        s["profit_factor"],
    )

# ── Command dispatcher ────────────────────────────────────────────────────────

async def dispatch(bot, message):
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return
    chat_id = message["chat"]["id"]
    if str(chat_id) != str(CHAT_ID):
        return
    cmd     = text.split()[0].lower().split("@")[0]
    trades  = get_all_trades()

    if cmd == "/help":
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "PERFORMANCE DASHBOARD — COMMANDS\n\n"
                "/stats     — overall win rate and key metrics\n"
                "/breakdown — by coin, direction, tier\n"
                "/recent    — last 10 closed trades\n"
                "/best      — top 5 performing coins\n"
                "/worst     — worst 5 performing coins\n"
                "/today     — today's trades\n"
                "/weekly    — this week's summary\n\n"
                "Stats update live from your scanner signals.\n"
                "Weekly report sent every Sunday 08:00 UTC."
            )
        )
    elif cmd == "/stats":
        await bot.send_message(chat_id=chat_id, text=build_stats_msg(trades))
    elif cmd == "/breakdown":
        await bot.send_message(chat_id=chat_id, text=build_breakdown_msg(trades))
    elif cmd == "/recent":
        await bot.send_message(chat_id=chat_id, text=build_recent_msg(trades))
    elif cmd == "/best":
        await bot.send_message(chat_id=chat_id, text=build_top_coins_msg(trades, worst=False))
    elif cmd == "/worst":
        await bot.send_message(chat_id=chat_id, text=build_top_coins_msg(trades, worst=True))
    elif cmd == "/today":
        await bot.send_message(chat_id=chat_id, text=build_today_msg(trades))
    elif cmd == "/weekly":
        await bot.send_message(chat_id=chat_id, text=build_weekly_msg(trades))

# ── Weekly report scheduler ───────────────────────────────────────────────────

async def weekly_reporter(bot):
    last_sent = ""
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        now = datetime.now(timezone.utc)
        if now.weekday() == 6 and now.hour == 8:
            key = now.strftime("%Y-W%W")
            if key != last_sent:
                trades = get_all_trades()
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text="WEEKLY PERFORMANCE REPORT\n\n" + build_weekly_msg(trades)
                    )
                    last_sent = key
                    log.info("Weekly report sent.")
                except Exception as e:
                    log.error("Weekly report error: %s" % e)

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("Performance Dashboard starting...")
    bot    = Bot(token=TELEGRAM_TOKEN)
    offset = 0

    trades = get_all_trades()
    s      = compute_stats(trades)

    if s and s["closed"] > 0:
        startup_extra = (
            "\n\nCurrent stats:\n"
            "Win rate: %.1f%%  |  Net R: %+.1fR\n"
            "Trades: %d closed, %d open"
        ) % (s["win_rate"], s["net_r"], s["closed"], s["open"])
    else:
        startup_extra = "\n\nNo trades yet. Stats will populate as scanner fires signals."

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Performance Dashboard Online!\n\n"
            "Commands:\n"
            "  /stats     — win rate + key metrics\n"
            "  /breakdown — by coin, direction, tier\n"
            "  /recent    — last 10 trades\n"
            "  /best      — top 5 coins\n"
            "  /worst     — worst 5 coins\n"
            "  /today     — today's P&L\n"
            "  /weekly    — 7-day summary\n"
            + startup_extra
        )
    )

    asyncio.create_task(weekly_reporter(bot))

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
