"""
Correlation Filter — monitors active_trades.json every 60 seconds.

Alerts you when multiple open positions belong to the same correlation
group, because correlated trades = one trade risk, not multiple.

Groups:
  BTC_LAYER   — BTC, LTC, BCH (BTC narrative)
  ETH_LAYER   — ETH, LINK, AAVE, UNI (Ethereum ecosystem)
  L1_ALTS     — SOL, AVAX, NEAR, APT, ATOM (competing L1s)
  L2_ALTS     — OP, ARB, MATIC (Ethereum scaling)
  MEME        — DOGE, SHIB, PEPE (meme coins)
  EXCHANGE    — BNB, OKB (exchange tokens)
  ORACLE_DeFi — LINK, INJ, AAVE, UNI (DeFi / oracle)

Rules:
  - 2 positions in same group → WARNING (yellow flag)
  - 3+ positions in same group → DANGER (reduce exposure now)
  - Opposing directions in same group → HEDGE ALERT (contradictory positions)
  - Checks immediately on startup, then every 60 seconds
"""

import os
import json
import time
import logging
import asyncio
from datetime import datetime, timezone
from telegram import Bot

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID         = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
TRADES_FILE     = "active_trades.json"
CHECK_INTERVAL  = 60     # seconds
ALERT_COOLDOWN  = 3600   # 1 hour between same group alert
COOLDOWN_FILE   = "correlation_cooldowns.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Correlation groups ────────────────────────────────────────────────────────

GROUPS = {
    "BTC Layer":    ["BTCUSDT", "LTCUSDT", "BCHUSDT"],
    "ETH Ecosystem":["ETHUSDT", "LINKUSDT", "AAVEUSDT", "UNIUSDT"],
    "L1 Alts":      ["SOLUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "ATOMUSDT", "ADAUSDT"],
    "L2 Scaling":   ["OPUSDT",  "ARBUSDT",  "MATICUSDT"],
    "Meme Coins":   ["DOGEUSDT","SHIBUSDT", "PEPEUSDT"],
    "Exchange Tkns":["BNBUSDT", "OKBUSDT"],
    "DeFi / Oracle":["LINKUSDT","INJUSDT",  "AAVEUSDT", "UNIUSDT"],
    "XRP / Payments":["XRPUSDT","XLMUSDT",  "TRXUSDT"],
    "Dot Ecosystem":["DOTUSDT", "KSMUSDT"],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return {}
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_cooldowns():
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    try:
        with open(COOLDOWN_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cooldowns(cd):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(cd, f)

def on_cooldown(cd, key):
    return time.time() - cd.get(key, 0) < ALERT_COOLDOWN

# ── Core analysis ─────────────────────────────────────────────────────────────

def analyse_correlations(trades):
    """
    Returns list of (group_name, symbols_in_group, directions, alert_level)
    alert_level = 'HEDGE' | 'DANGER' | 'WARNING'
    """
    # Only active (not closed) trades
    active = {k: v for k, v in trades.items() if not v.get("closed", False)}
    if not active:
        return []

    open_symbols = {}   # symbol → list of directions
    for t in active.values():
        sym = t["symbol"]
        d   = t["direction"]
        open_symbols.setdefault(sym, []).append(d)

    issues = []
    for group_name, members in GROUPS.items():
        in_group = [(s, open_symbols[s]) for s in members if s in open_symbols]
        if len(in_group) < 2:
            continue

        symbols    = [s for s, _ in in_group]
        directions = [ds[0] for _, ds in in_group]

        # Opposing directions in same group
        if "LONG" in directions and "SHORT" in directions:
            issues.append((group_name, symbols, directions, "HEDGE"))
        elif len(in_group) >= 3:
            issues.append((group_name, symbols, directions, "DANGER"))
        else:
            issues.append((group_name, symbols, directions, "WARNING"))

    return issues

# ── Message builders ──────────────────────────────────────────────────────────

def build_warning(group_name, symbols, directions, level):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    coins = [s.replace("USDT", "") for s in symbols]
    pairs = ["%s (%s)" % (c, d) for c, d in zip(coins, directions)]

    if level == "HEDGE":
        header  = "CORRELATION HEDGE ALERT"
        summary = "You have OPPOSING positions in the same group."
        advice  = (
            "You are simultaneously LONG and SHORT within the '%s' group.\n"
            "These coins move together — your positions cancel out.\n\n"
            "ACTION: Close one side or this is a flat trade wasting margin."
        ) % group_name

    elif level == "DANGER":
        header  = "CORRELATION DANGER — OVER-EXPOSED"
        summary = "3+ positions in the same correlation group."
        advice  = (
            "You have %d positions in the '%s' group.\n"
            "This is NOT diversification — it's concentrated risk.\n\n"
            "ACTION: Close at least %d positions, keep your strongest setup only."
        ) % (len(symbols), group_name, len(symbols) - 1)

    else:
        header  = "CORRELATION WARNING"
        summary = "2 positions in the same correlation group."
        advice  = (
            "Both coins are in the '%s' group — they move together.\n\n"
            "This means if one hits SL, the other likely will too.\n"
            "Consider: Is the combined risk within your 2%% rule?"
        ) % group_name

    return (
        "%s\n"
        "\n"
        "Group:    %s\n"
        "Coins:    %s\n"
        "\n"
        "%s\n"
        "\n"
        "%s\n"
        "\n"
        "Time: %s UTC"
    ) % (
        header,
        group_name,
        " | ".join(pairs),
        summary,
        advice,
        now,
    )

def build_clear_msg(prev_count):
    return (
        "CORRELATION CHECK — ALL CLEAR\n\n"
        "No correlated position clusters detected.\n"
        "Your open trades are well-diversified.\n\n"
        "Time: %s UTC"
    ) % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    log.info("Correlation Filter starting...")
    bot = Bot(token=TELEGRAM_TOKEN)
    cd  = load_cooldowns()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Correlation Filter Online!\n\n"
            "I watch your open positions every 60 seconds\n"
            "and alert you when correlated trades pile up:\n\n"
            "  WARNING  — 2 coins from same group\n"
            "  DANGER   — 3+ coins from same group\n"
            "  HEDGE    — opposing directions, same group\n\n"
            "Groups monitored:\n"
            "  BTC Layer, ETH Ecosystem, L1 Alts,\n"
            "  L2 Scaling, DeFi, Meme Coins, Payments\n\n"
            "Correlated trades = 1 trade risk, not many.\n"
            "I keep your book honest."
        )
    )

    prev_issue_count = 0
    scan_count       = 0

    while True:
        scan_count += 1
        trades = load_trades()

        if not trades:
            await asyncio.sleep(CHECK_INTERVAL)
            continue

        active = {k: v for k, v in trades.items() if not v.get("closed", False)}
        open_count = len(active)

        log.info("Correlation scan #%d — %d open trades" % (scan_count, open_count))

        issues = analyse_correlations(trades)

        if not issues and prev_issue_count > 0:
            # Correlations just cleared — notify once
            try:
                await bot.send_message(chat_id=CHAT_ID, text=build_clear_msg(prev_issue_count))
            except Exception as e:
                log.error("Clear msg error: %s" % e)

        prev_issue_count = len(issues)

        for group_name, symbols, directions, level in issues:
            cd_key = "grp_%s_%s" % (group_name.replace(" ", "_"), level)
            if on_cooldown(cd, cd_key):
                continue

            msg = build_warning(group_name, symbols, directions, level)
            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    disable_web_page_preview=True,
                )
                cd[cd_key] = time.time()
                save_cooldowns(cd)
                log.info("Correlation alert: %s %s — %s" % (level, group_name, symbols))
                await asyncio.sleep(2)
            except Exception as e:
                log.error("Alert send error: %s" % e)

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
