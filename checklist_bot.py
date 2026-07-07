#!/usr/bin/env python3
"""
Standalone memecoin due diligence checklist Telegram bot.
Requires CHECKLIST_BOT_TOKEN env var (separate bot from auto_trader).
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["CHECKLIST_BOT_TOKEN"]
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = DATA_DIR / "checklist_history.json"

# Conversation states
ENTER_NAME, ENTER_ADDRESS, CHECKING = range(3)

SEVERITY_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
SEVERITY_WEIGHT = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

PARTS = {
    1: "🔐 Contract Security",
    2: "💧 Liquidity & Tokenomics",
    3: "📣 Social & Community",
    4: "📈 Trading Strategy",
    5: "⚠️ Advanced Rug Vectors",
}

CHECKS = [
    # Part 1 — Contract Security
    {"id": 1, "part": 1, "severity": "CRITICAL", "title": "Honeypot test passed",
     "desc": "Token can be sold after buying. Verify on honeypot.is"},
    {"id": 2, "part": 1, "severity": "CRITICAL", "title": "Mint authority renounced",
     "desc": "Dev cannot print new tokens. Verify on block explorer."},
    {"id": 3, "part": 1, "severity": "CRITICAL", "title": "Freeze authority revoked",
     "desc": "Dev cannot freeze wallets. Check on rugcheck.xyz"},
    {"id": 4, "part": 1, "severity": "CRITICAL", "title": "No blacklist function",
     "desc": "No function exists to trap holders from selling."},
    {"id": 5, "part": 1, "severity": "CRITICAL", "title": "No hidden fee switch",
     "desc": "Buy/sell tax cannot be changed after deploy. Check tokensniffer.com"},
    {"id": 6, "part": 1, "severity": "HIGH", "title": "Contract not upgradeable",
     "desc": "No proxy contract — code cannot be silently swapped after launch."},
    {"id": 7, "part": 1, "severity": "HIGH", "title": "Renouncement verified on-chain",
     "desc": "Verified on blockchain explorer, not just claimed on socials."},
    {"id": 8, "part": 1, "severity": "HIGH", "title": "No migration rug vector",
     "desc": "No 'v2 migration' function that could drain liquidity."},
    {"id": 9, "part": 1, "severity": "MEDIUM", "title": "Source code verified",
     "desc": "Contract source is public and verified on explorer."},
    {"id": 10, "part": 1, "severity": "MEDIUM", "title": "No suspicious owner functions",
     "desc": "ABI has no hidden backdoor or privileged functions."},
    # Part 2 — Liquidity & Tokenomics
    {"id": 11, "part": 2, "severity": "CRITICAL", "title": "Liquidity locked ≥90%",
     "desc": "≥90% LP tokens locked on Unicrypt / Team.Finance / PinkLock."},
    {"id": 12, "part": 2, "severity": "CRITICAL", "title": "Lock duration ≥6 months",
     "desc": "Lock must be ≥6 months from TODAY, not from launch date."},
    {"id": 13, "part": 2, "severity": "HIGH", "title": "Dev wallet ≤5% of supply",
     "desc": "Team allocation below 5% reduces dump risk. Check bubblemaps.io"},
    {"id": 14, "part": 2, "severity": "HIGH", "title": "Top 10 wallets ≤20%",
     "desc": "No extreme whale concentration in top holders."},
    {"id": 15, "part": 2, "severity": "HIGH", "title": "No cluster >15% on Bubblemaps",
     "desc": "No coordinated wallet cluster holding more than 15%."},
    {"id": 16, "part": 2, "severity": "MEDIUM", "title": "Liquidity depth >$50K",
     "desc": "Minimum $50K liquidity to avoid easy price manipulation."},
    {"id": 17, "part": 2, "severity": "MEDIUM", "title": "No wash trading detected",
     "desc": "Volume spike >500% with <5% price move = wash trading red flag."},
    {"id": 18, "part": 2, "severity": "MEDIUM", "title": "Reasonable token supply",
     "desc": "Avoid 1 quadrillion supplies with no burn mechanism."},
    # Part 3 — Social & Community
    {"id": 19, "part": 3, "severity": "HIGH", "title": "Telegram >1K organic members",
     "desc": "Real conversation, not just bots saying 'gm'. Lurk for 10 mins."},
    {"id": 20, "part": 3, "severity": "HIGH", "title": "Twitter/X account established",
     "desc": ">1 month old OR launched with a clear unique narrative."},
    {"id": 21, "part": 3, "severity": "HIGH", "title": "Original website & branding",
     "desc": "No copy-paste template. Real roadmap with unique identity."},
    {"id": 22, "part": 3, "severity": "HIGH", "title": "KOL attention is organic",
     "desc": "Influencer coverage is not a paid coordinated shill cluster."},
    {"id": 23, "part": 3, "severity": "MEDIUM", "title": "Narrative fits current meta",
     "desc": "AI, RWA, DeSci, or active memecoin cycle narrative."},
    {"id": 24, "part": 3, "severity": "MEDIUM", "title": "No FUD suppression in TG",
     "desc": "Critics are not being silently banned from the Telegram group."},
    {"id": 25, "part": 3, "severity": "MEDIUM", "title": "Dev doxxed or verifiable",
     "desc": "Dev is known or has verifiable on-chain reputation."},
    {"id": 26, "part": 3, "severity": "LOW", "title": "Organic community memes",
     "desc": "Community memes are original and spreading naturally."},
    # Part 4 — Trading Strategy
    {"id": 27, "part": 4, "severity": "HIGH", "title": "Market cap <$500K at entry",
     "desc": "Entry below $500K for meaningful 10x+ potential. Check dexscreener.com"},
    {"id": 28, "part": 4, "severity": "HIGH", "title": "BTC dominance <54%",
     "desc": "Memecoin season conditions. Check BTCD chart on TradingView."},
    {"id": 29, "part": 4, "severity": "HIGH", "title": "Position ≤2% of portfolio",
     "desc": "Max 1-2% of total portfolio per memecoin play."},
    {"id": 30, "part": 4, "severity": "MEDIUM", "title": "Take-profit plan defined",
     "desc": "50% at 2x → 25% at 4x → 15% at 8x → moonbag the rest."},
    {"id": 31, "part": 4, "severity": "MEDIUM", "title": "Stop-loss level defined",
     "desc": "Exit plan if -40% from entry with no recovery volume."},
    # Part 5 — Advanced Rug Vectors
    {"id": 32, "part": 5, "severity": "CRITICAL", "title": "No bridge rug vector",
     "desc": "Funds not routed through unaudited bridge contract."},
    {"id": 33, "part": 5, "severity": "CRITICAL", "title": "No industrial bundle cluster",
     "desc": "No 12+ wallets buying same block at launch (82% drain pattern on pump.fun)."},
    {"id": 34, "part": 5, "severity": "HIGH", "title": "Pump.fun graduation verified",
     "desc": "Not a failed launch re-listed (only 0.26% legitimately graduate)."},
    {"id": 35, "part": 5, "severity": "HIGH", "title": "No live-stream dump pattern",
     "desc": "No influencer live-stream coordinated dump history on this token."},
    {"id": 36, "part": 5, "severity": "MEDIUM", "title": "Dev wallet not from mixer",
     "desc": "Dev funding not sourced from Tornado Cash or other mixer. Check Arkham."},
]

GATE_DISPLAY = {
    "STRONG": "💎 STRONG — High conviction play",
    "GREEN":  "✅ GREEN — Proceed with normal position",
    "YELLOW": "⚠️ YELLOW — High risk, small position only",
    "RED":    "🚫 RED — DO NOT BUY",
}


# ---- persistence ----

def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return []
    return []


def save_history(history: list) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


# ---- scoring ----

def calculate_score(results: dict) -> tuple:
    """Returns (score_pct, gate, critical_fails)."""
    total_weight = 0
    passed_weight = 0
    critical_fails = 0

    for check in CHECKS:
        result = results.get(str(check["id"]), "skip")
        if result == "skip":
            continue
        weight = SEVERITY_WEIGHT[check["severity"]]
        total_weight += weight
        if result == "pass":
            passed_weight += weight
        elif result == "fail" and check["severity"] == "CRITICAL":
            critical_fails += 1

    score_pct = int(passed_weight / total_weight * 100) if total_weight > 0 else 0

    if critical_fails > 0:
        gate = "RED"
    elif score_pct >= 85:
        gate = "STRONG"
    elif score_pct >= 70:
        gate = "GREEN"
    elif score_pct >= 50:
        gate = "YELLOW"
    else:
        gate = "RED"

    return score_pct, gate, critical_fails


# ---- helpers ----

def _check_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Pass", callback_data="check:pass"),
        InlineKeyboardButton("❌ Fail",  callback_data="check:fail"),
        InlineKeyboardButton("⏭ Skip",  callback_data="check:skip"),
    ]])


async def _send_check(chat_id: int, idx: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    check = CHECKS[idx]
    results = context.user_data.get("results", {})

    # Part transition banner
    if idx > 0 and CHECKS[idx - 1]["part"] != check["part"]:
        prev_part = CHECKS[idx - 1]["part"]
        passed = sum(
            1 for c in CHECKS
            if c["part"] == prev_part and results.get(str(c["id"])) == "pass"
        )
        answered = sum(
            1 for c in CHECKS
            if c["part"] == prev_part and results.get(str(c["id"])) in ("pass", "fail")
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"*{PARTS[prev_part]} complete*\n"
                f"Passed: {passed}/{answered}\n\n"
                f"Starting: *{PARTS[check['part']]}*"
            ),
            parse_mode="Markdown",
        )

    sev = check["severity"]
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"*[{idx + 1}/36] {SEVERITY_EMOJI[sev]} {sev}*\n"
            f"_{PARTS[check['part']]}_\n\n"
            f"*{check['title']}*\n"
            f"{check['desc']}"
        ),
        parse_mode="Markdown",
        reply_markup=_check_keyboard(),
    )


async def _send_final(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    results = context.user_data["results"]
    token_name = context.user_data["token_name"]
    contract = context.user_data["contract"]
    score, gate, critical_fails = calculate_score(results)

    passed  = sum(1 for v in results.values() if v == "pass")
    failed  = sum(1 for v in results.values() if v == "fail")
    skipped = sum(1 for v in results.values() if v == "skip")

    crit_line = f"\n🚨 *{critical_fails} CRITICAL failure(s)*" if critical_fails else ""

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📊 *Evaluation Complete: {token_name}*\n"
            f"`{contract}`\n\n"
            f"Score: *{score}%*  |  ✅{passed}  ❌{failed}  ⏭{skipped}"
            f"{crit_line}\n\n"
            f"Verdict: *{GATE_DISPLAY[gate]}*\n\n"
            f"📌 TP plan: 50% @2x → 25% @4x → 15% @8x → moonbag"
        ),
        parse_mode="Markdown",
    )

    history = load_history()
    history.insert(0, {
        "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "token_name": token_name,
        "contract": contract,
        "score": score,
        "gate": gate,
        "critical_fails": critical_fails,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    })
    save_history(history[:20])


# ---- command handlers ----

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *GemFinder Checklist Bot*\n\n"
        "36-point memecoin due diligence system to catch 2–10x gains and avoid rugpulls.\n\n"
        "/check — Start a new token evaluation\n"
        "/history — View past evaluations\n"
        "/tools — Research tools reference\n"
        "/narrative — Narrative cycle guide\n"
        "/cancel — Cancel current evaluation",
        parse_mode="Markdown",
    )


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🔍 *New Token Evaluation*\n\nWhat is the token name or ticker?",
        parse_mode="Markdown",
    )
    return ENTER_NAME


async def recv_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["token_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"Token: *{context.user_data['token_name']}*\n\nPaste the contract address:",
        parse_mode="Markdown",
    )
    return ENTER_ADDRESS


async def recv_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["contract"] = update.message.text.strip()
    context.user_data["current_check"] = 0
    context.user_data["results"] = {}
    context.user_data["chat_id"] = update.effective_chat.id

    await update.message.reply_text(
        f"Starting 36-check evaluation for *{context.user_data['token_name']}*\n\n"
        "Rate each check:  ✅ Pass  /  ❌ Fail  /  ⏭ Skip",
        parse_mode="Markdown",
    )
    await _send_check(update.effective_chat.id, 0, context)
    return CHECKING


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if "current_check" not in context.user_data:
        await query.message.reply_text("No active evaluation. Use /check to start.")
        return ConversationHandler.END

    idx = context.user_data["current_check"]
    check = CHECKS[idx]
    action = query.data.split(":")[1]  # pass / fail / skip

    context.user_data["results"][str(check["id"])] = action

    icons = {"pass": "✅", "fail": "❌", "skip": "⏭"}
    await query.edit_message_text(
        f"{icons[action]} *{check['title']}* — {action.upper()}",
        parse_mode="Markdown",
    )

    context.user_data["current_check"] = idx + 1
    chat_id = context.user_data["chat_id"]

    if context.user_data["current_check"] >= len(CHECKS):
        await _send_final(chat_id, context)
        return ConversationHandler.END

    await _send_check(chat_id, context.user_data["current_check"], context)
    return CHECKING


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history = load_history()
    if not history:
        await update.message.reply_text("No evaluations saved yet. Use /check to start.")
        return

    gate_icons = {"STRONG": "💎", "GREEN": "✅", "YELLOW": "⚠️", "RED": "🚫"}
    lines = ["📋 *Recent Evaluations*\n"]
    for item in history[:10]:
        icon = gate_icons.get(item["gate"], "❓")
        lines.append(
            f"{icon} *{item['token_name']}* — {item['score']}% ({item['gate']})\n"
            f"   {item['date']}  ✅{item['passed']} ❌{item['failed']} ⏭{item['skipped']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def tools_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛠 *Research Tools*\n\n"
        "*Contract Security*\n"
        "• honeypot.is — Honeypot test\n"
        "• rugcheck.xyz — Solana rug check\n"
        "• tokensniffer.com — EVM contract scan\n\n"
        "*Wallet & Clustering*\n"
        "• bubblemaps.io — Wallet cluster visualization\n"
        "• arkham.intelligence — Wallet tracking\n"
        "• cielo.finance — Smart money flows\n\n"
        "*Price & Volume*\n"
        "• dexscreener.com — Price/volume charts\n"
        "• defined.fi — Advanced DEX analytics\n"
        "• birdeye.so — Solana token analytics\n\n"
        "*Liquidity Locks*\n"
        "• unicrypt.network — Lock verification\n"
        "• team.finance — Lock verification\n"
        "• pinksale.finance — PinkLock check",
        parse_mode="Markdown",
    )


async def narrative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 *Narrative Cycle Stages*\n\n"
        "1️⃣ Niche Discovery  ✅ BEST ENTRY\n"
        "   Only insiders know it. Lowest risk.\n\n"
        "2️⃣ CT-Native  ✅ GOOD ENTRY\n"
        "   Small crypto Twitter accounts posting.\n\n"
        "3️⃣ Mid-Tier KOLs  ⚠️ OKAY\n"
        "   10K-100K follower accounts covering it.\n\n"
        "4️⃣ Mainstream CT  ⚠️ RISKY\n"
        "   Top CT accounts. Most retail sees it here.\n\n"
        "5️⃣ Normie Onboarding  🔴 LATE\n"
        "   Friends/family asking 'should I buy?'\n\n"
        "6️⃣ Media Coverage  🔴 VERY LATE\n"
        "   News articles and YouTube videos.\n\n"
        "7️⃣ Exhaustion  ❌ EXIT\n"
        "   Price dumps despite good news coverage.\n\n"
        "Rule: Enter Stage 1-2. Exit by Stage 4-5.",
        parse_mode="Markdown",
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Evaluation cancelled. Use /check to start a new one.")
    return ConversationHandler.END


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("check", check_cmd)],
        states={
            ENTER_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_name)],
            ENTER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_address)],
            CHECKING:      [CallbackQueryHandler(handle_answer, pattern=r"^check:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help",  start_cmd))
    app.add_handler(CommandHandler("tools", tools_cmd))
    app.add_handler(CommandHandler("narrative", narrative_cmd))
    app.add_handler(CommandHandler("history",   history_cmd))
    app.add_handler(conv)

    logger.info("Checklist bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
