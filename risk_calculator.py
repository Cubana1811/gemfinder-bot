"""
Risk Calculator Bot — instant position sizing via Telegram commands.

Commands:
  /risk ACCOUNT ENTRY SL TP1 [TP2] [TP3]
      Calculate exact position size, leverage, and expected P&L
      e.g. /risk 1000 65000 63000 70000 74000

  /riskpct ACCOUNT RISK_PCT ENTRY SL TP1 [TP2]
      Use a custom risk % instead of the default 2%
      e.g. /riskpct 1000 1.5 65000 63000 70000

  /setaccount SIZE
      Save your account size so you don't type it every time
      e.g. /setaccount 1000

  /calc ENTRY SL TP1 [TP2] [TP3]
      Uses your saved account size
      e.g. /calc 65000 63000 70000

  /help — show all commands

For each trade it returns:
  - Dollar amount to risk (2% of account)
  - Exact position size in USD and coins
  - Suggested leverage (capped at 10x)
  - Expected profit at TP1, TP2, TP3
  - Risk/Reward ratio
  - Max loss in dollars
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from telegram import Bot

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID          = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
SETTINGS_FILE    = "risk_settings.json"
DEFAULT_RISK_PCT = 2.0     # 2% per trade
MAX_LEVERAGE     = 10      # never suggest more than 10x
POLL_INTERVAL    = 2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Settings store ────────────────────────────────────────────────────────────

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(s):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)

# ── Core calculator ───────────────────────────────────────────────────────────

def fp(n):
    if n >= 1000: return "%.2f" % n
    if n >= 1:    return "%.4f" % n
    if n >= 0.01: return "%.6f" % n
    return "%.8f" % n

def calculate(account, risk_pct, entry, sl, tp1, tp2=None, tp3=None):
    risk_usd     = account * risk_pct / 100
    sl_dist_pct  = abs(entry - sl) / entry * 100
    sl_dist_usd  = abs(entry - sl)

    # Position size: risk_usd / sl_dist_per_coin
    position_usd  = risk_usd / (sl_dist_usd / entry) if sl_dist_usd > 0 else 0
    position_coin = position_usd / entry if entry > 0 else 0

    # Leverage needed (position / account)
    leverage_raw = position_usd / account if account > 0 else 1
    leverage     = min(round(leverage_raw, 1), MAX_LEVERAGE)

    # Direction
    direction = "LONG" if tp1 > entry else "SHORT"

    def pnl(tp):
        if tp is None:
            return None, None
        if direction == "LONG":
            gain_pct = (tp - entry) / entry * 100
            gain_usd = position_coin * (tp - entry)
        else:
            gain_pct = (entry - tp) / entry * 100
            gain_usd = position_coin * (entry - tp)
        rr = abs(gain_usd / risk_usd) if risk_usd > 0 else 0
        return gain_pct, gain_usd, rr

    tp1_pct, tp1_usd, rr1 = pnl(tp1)
    tp2_result = pnl(tp2) if tp2 else (None, None, None)
    tp3_result = pnl(tp3) if tp3 else (None, None, None)

    return {
        "direction":    direction,
        "account":      account,
        "risk_pct":     risk_pct,
        "risk_usd":     risk_usd,
        "sl_dist_pct":  sl_dist_pct,
        "position_usd": position_usd,
        "position_coin":position_coin,
        "leverage":     leverage,
        "entry":        entry,
        "sl":           sl,
        "tp1":          tp1,
        "tp2":          tp2,
        "tp3":          tp3,
        "tp1_pct":      tp1_pct,
        "tp1_usd":      tp1_usd,
        "rr1":          rr1,
        "tp2_result":   tp2_result,
        "tp3_result":   tp3_result,
    }

def build_result_msg(c):
    direction = c["direction"]
    dir_arrow = "LONG" if direction == "LONG" else "SHORT"

    tp2_line = ""
    tp3_line = ""
    t2p, t2u, t2r = c["tp2_result"]
    t3p, t3u, t3r = c["tp3_result"]

    if t2p is not None:
        tp2_line = "TP2 ($%s): +%.2f%%  +$%.2f  (%.2fR)\n" % (
            fp(c["tp2"]), t2p, t2u, t2r)
    if t3p is not None:
        tp3_line = "TP3 ($%s): +%.2f%%  +$%.2f  (%.2fR)\n" % (
            fp(c["tp3"]), t3p, t3u, t3r)

    leverage_note = ""
    if c["leverage"] >= MAX_LEVERAGE:
        leverage_note = (
            "\nNOTE: Raw leverage needed is %.1fx but capped\n"
            "at %dx. Reduce position size or use wider SL.\n"
        ) % (c["position_usd"] / c["account"], MAX_LEVERAGE)

    return (
        "RISK CALCULATOR — %s\n"
        "\n"
        "Account:   $%.2f\n"
        "Risk:      %.1f%%  =  $%.2f\n"
        "\n"
        "=== ENTRY PLAN ===\n"
        "Entry:     $%s\n"
        "SL:        $%s  (-%.2f%%  = -$%.2f)\n"
        "\n"
        "=== POSITION SIZE ===\n"
        "Size:      $%.2f\n"
        "Coins:     %s\n"
        "Leverage:  %.1fx\n"
        "%s"
        "\n"
        "=== PROFIT TARGETS ===\n"
        "TP1 ($%s): +%.2f%%  +$%.2f  (%.2fR)\n"
        "%s"
        "%s"
        "\n"
        "Max loss:  -$%.2f  (%.1f%% of account)\n"
        "\n"
        "Rule: Risk $%.2f to make $%.2f at TP1."
    ) % (
        dir_arrow,
        c["account"],
        c["risk_pct"], c["risk_usd"],
        fp(c["entry"]),
        fp(c["sl"]), c["sl_dist_pct"], c["risk_usd"],
        c["position_usd"],
        fp(c["position_coin"]),
        c["leverage"],
        leverage_note,
        fp(c["tp1"]), c["tp1_pct"], c["tp1_usd"], c["rr1"],
        tp2_line,
        tp3_line,
        c["risk_usd"],
        c["risk_pct"],
        c["risk_usd"], c["tp1_usd"],
    )

# ── Command handlers ──────────────────────────────────────────────────────────

async def handle_help(bot, chat_id):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "RISK CALCULATOR — COMMANDS\n\n"
            "/setaccount 1000\n"
            "  Save your account size once\n\n"
            "/calc ENTRY SL TP1 [TP2] [TP3]\n"
            "  Uses your saved account size\n"
            "  Example: /calc 65000 63000 70000\n\n"
            "/risk ACCOUNT ENTRY SL TP1 [TP2] [TP3]\n"
            "  Full calculation with account size\n"
            "  Example: /risk 1000 65000 63000 70000\n\n"
            "/riskpct ACCOUNT PCT ENTRY SL TP1\n"
            "  Use custom risk % (default is 2%%)\n"
            "  Example: /riskpct 1000 1.5 65000 63000 70000\n\n"
            "All calculations use the 2%% rule:\n"
            "Never risk more than 2%% per trade.\n"
            "Leverage capped at 10x for safety."
        )
    )

async def handle_setaccount(bot, chat_id, args):
    if not args:
        await bot.send_message(chat_id=chat_id,
                               text="Usage: /setaccount 1000")
        return
    try:
        size = float(args[0])
        s = load_settings()
        s[str(chat_id)] = {"account": size}
        save_settings(s)
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Account size saved: $%.2f\n\n"
                "Now use /calc ENTRY SL TP1\n"
                "and I'll calculate everything for you."
            ) % size
        )
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="Please enter a number. Example: /setaccount 1000")

async def handle_calc(bot, chat_id, args):
    s = load_settings()
    user_s = s.get(str(chat_id), {})
    account = user_s.get("account")
    if not account:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "No account size saved.\n"
                "First run: /setaccount 1000\n"
                "Or use: /risk 1000 ENTRY SL TP1"
            )
        )
        return
    await _run_calc(bot, chat_id, account, DEFAULT_RISK_PCT, args)

async def handle_risk(bot, chat_id, args):
    if len(args) < 4:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Usage: /risk ACCOUNT ENTRY SL TP1 [TP2] [TP3]\n"
                "Example: /risk 1000 65000 63000 70000 74000"
            )
        )
        return
    try:
        account = float(args[0])
        await _run_calc(bot, chat_id, account, DEFAULT_RISK_PCT, args[1:])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="Invalid number. Example: /risk 1000 65000 63000 70000")

async def handle_riskpct(bot, chat_id, args):
    if len(args) < 5:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Usage: /riskpct ACCOUNT PCT ENTRY SL TP1 [TP2] [TP3]\n"
                "Example: /riskpct 1000 1.5 65000 63000 70000"
            )
        )
        return
    try:
        account  = float(args[0])
        risk_pct = float(args[1])
        if risk_pct <= 0 or risk_pct > 10:
            await bot.send_message(chat_id=chat_id,
                                   text="Risk %% must be between 0.1 and 10.")
            return
        await _run_calc(bot, chat_id, account, risk_pct, args[2:])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="Invalid numbers. Example: /riskpct 1000 1.5 65000 63000 70000")

async def _run_calc(bot, chat_id, account, risk_pct, args):
    if len(args) < 3:
        await bot.send_message(chat_id=chat_id,
                               text="Need at least ENTRY SL TP1.")
        return
    try:
        entry = float(args[0])
        sl    = float(args[1])
        tp1   = float(args[2])
        tp2   = float(args[3]) if len(args) > 3 else None
        tp3   = float(args[4]) if len(args) > 4 else None

        if entry <= 0 or sl <= 0 or tp1 <= 0:
            raise ValueError("zeros")
        if abs(entry - sl) / entry < 0.001:
            await bot.send_message(chat_id=chat_id,
                                   text="SL is too close to entry (< 0.1%). Widen your SL.")
            return

        c   = calculate(account, risk_pct, entry, sl, tp1, tp2, tp3)
        msg = build_result_msg(c)
        await bot.send_message(chat_id=chat_id, text=msg)
        log.info("Calc: acc=%.0f entry=%s sl=%s tp1=%s" % (account, entry, sl, tp1))

    except (ValueError, IndexError):
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Invalid numbers.\n"
                "Example: /calc 65000 63000 70000\n"
                "         (entry  sl    tp1)"
            )
        )

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
    elif cmd == "/setaccount":
        await handle_setaccount(bot, chat_id, args)
    elif cmd == "/calc":
        await handle_calc(bot, chat_id, args)
    elif cmd == "/risk":
        await handle_risk(bot, chat_id, args)
    elif cmd == "/riskpct":
        await handle_riskpct(bot, chat_id, args)

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("Risk Calculator starting...")
    bot    = Bot(token=TELEGRAM_TOKEN)
    offset = 0

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Risk Calculator Online!\n\n"
            "Commands:\n"
            "  /setaccount 1000\n"
            "  /calc ENTRY SL TP1 [TP2] [TP3]\n"
            "  /risk ACCOUNT ENTRY SL TP1\n"
            "  /riskpct ACCOUNT PCT ENTRY SL TP1\n\n"
            "Example — BTC long:\n"
            "  /setaccount 1000\n"
            "  /calc 65000 63000 70000 74000\n\n"
            "I use the 2%% rule by default and\n"
            "cap leverage at 10x for your safety.\n\n"
            "I give you:\n"
            "  - Exact dollar risk\n"
            "  - Position size in USD and coins\n"
            "  - Leverage to set\n"
            "  - Profit at each TP level"
        )
    )

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
