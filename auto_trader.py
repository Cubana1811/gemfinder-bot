"""
GemFinder Auto-Trader — Stage 1
Executes trades on Bybit based on the GemFinder signal scoring engine.
Paper trading is ON by default. Set PAPER_TRADE=false in Railway to go live.
"""

import os
import time
import hmac
import hashlib
import json
import logging
import asyncio
import requests
from datetime import datetime, timezone, date
from telegram import Bot

# Import scoring engine from the signal bot (same repo, no duplication)
from tradingview_scanner import (
    tv_scan_multi_exchange, score_setup, parse_klines,
    fetch_klines, fetch_klines_bnb, fetch_klines_okx,
    fetch_funding_rate, fetch_oi_change, fetch_order_book_imbalance,
    fetch_top_trader_ratio, fetch_taker_ratio, exchange_confirms,
    is_active_session, btc_is_spiking, btc_is_ranging,
    fetch_fear_greed, fetch_btc_change,
    MIN_SCORE, SIGNAL_COOLDOWN, SCAN_INTERVAL,
)

# ── Config ─────────────────────────────────────────────────────────────────────
BYBIT_API_KEY    = os.environ.get("BYBIT_API_KEY",    "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
CHAT_ID          = os.environ.get("CHAT_ID",          "")
PAPER_TRADE      = os.environ.get("PAPER_TRADE", "true").lower() != "false"

RISK_PCT          = 2.0    # % of account risked per trade
MAX_POSITIONS     = 3      # maximum open trades at once
DAILY_LOSS_LIMIT  = 6.0    # % daily loss that pauses trading (3 max losses)
MAX_LEVERAGE      = 10     # hard leverage ceiling
PAPER_START_BAL   = 10000  # virtual starting balance ($)
BYBIT_BASE        = "https://api.bybit.com"

TP1_CLOSE = 0.40   # close 40% at TP1
TP2_CLOSE = 0.35   # close 35% at TP2
TP3_CLOSE = 0.25   # let 25% run to TP3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Global State ───────────────────────────────────────────────────────────────
trading_active        = True
open_positions        = {}    # symbol → PaperPosition or live dict
seen_signals          = {}    # symbol → last signal timestamp (cooldown)
paper_balance         = float(PAPER_START_BAL)
daily_stats           = {"date": str(date.today()), "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}
total_stats           = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}

# ── Bybit V5 Authenticated API ─────────────────────────────────────────────────

def _sign(payload_str: str):
    ts  = str(int(time.time() * 1000))
    msg = ts + BYBIT_API_KEY + "5000" + payload_str
    sig = hmac.new(BYBIT_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return ts, sig

def bybit_post(endpoint: str, payload: dict) -> dict:
    body    = json.dumps(payload, separators=(",", ":"))
    ts, sig = _sign(body)
    headers = {
        "X-BAPI-API-KEY":     BYBIT_API_KEY,
        "X-BAPI-SIGN":        sig,
        "X-BAPI-TIMESTAMP":   ts,
        "X-BAPI-RECV-WINDOW": "5000",
        "Content-Type":       "application/json",
    }
    try:
        r = requests.post(BYBIT_BASE + endpoint, headers=headers, data=body, timeout=10)
        return r.json()
    except Exception as e:
        log.error("Bybit POST %s: %s" % (endpoint, e))
        return {}

def bybit_get(endpoint: str, params: dict) -> dict:
    query   = "&".join("%s=%s" % (k, v) for k, v in sorted(params.items()))
    ts, sig = _sign(query)
    headers = {
        "X-BAPI-API-KEY":     BYBIT_API_KEY,
        "X-BAPI-SIGN":        sig,
        "X-BAPI-TIMESTAMP":   ts,
        "X-BAPI-RECV-WINDOW": "5000",
    }
    try:
        r = requests.get(BYBIT_BASE + endpoint + "?" + query, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        log.error("Bybit GET %s: %s" % (endpoint, e))
        return {}

def get_live_balance() -> float:
    data = bybit_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    if data.get("retCode") == 0:
        for acct in data["result"]["list"]:
            for coin in acct.get("coin", []):
                if coin["coin"] == "USDT":
                    return float(coin.get("availableToWithdraw") or coin.get("walletBalance") or 0)
    return 0.0

def get_balance() -> float:
    return paper_balance if PAPER_TRADE else get_live_balance()

def setup_symbol(symbol: str, leverage: int) -> bool:
    """Set isolated margin + leverage before placing any order."""
    r1 = bybit_post("/v5/position/switch-isolated", {
        "category":     "linear",
        "symbol":       symbol,
        "tradeMode":    1,
        "buyLeverage":  str(leverage),
        "sellLeverage": str(leverage),
    })
    r2 = bybit_post("/v5/position/set-leverage", {
        "category":     "linear",
        "symbol":       symbol,
        "buyLeverage":  str(leverage),
        "sellLeverage": str(leverage),
    })
    ok1 = r1.get("retCode") in (0, 110026)  # 110026 = already isolated
    ok2 = r2.get("retCode") in (0, 110043)  # 110043 = leverage unchanged
    return ok1 and ok2

def place_market_order(symbol: str, direction: str, qty: float) -> dict:
    return bybit_post("/v5/order/create", {
        "category":    "linear",
        "symbol":      symbol,
        "side":        "Buy" if direction == "LONG" else "Sell",
        "orderType":   "Market",
        "qty":         str(qty),
        "timeInForce": "GTC",
    })

def confirm_fill(symbol: str, order_id: str, retries: int = 6) -> float:
    """Poll until order is filled. Returns average fill price or 0."""
    for _ in range(retries):
        time.sleep(1)
        data = bybit_get("/v5/order/realtime", {"category": "linear", "symbol": symbol, "orderId": order_id})
        if data.get("retCode") == 0:
            orders = data["result"].get("list", [])
            if orders and orders[0]["orderStatus"] == "Filled":
                return float(orders[0].get("avgPrice") or orders[0].get("price") or 0)
    return 0.0

def set_position_sl(symbol: str, sl: float) -> dict:
    """Attach stop-loss to the open position."""
    return bybit_post("/v5/position/trading-stop", {
        "category":    "linear",
        "symbol":      symbol,
        "positionIdx": 0,
        "stopLoss":    str(round(sl, 6)),
        "slTriggerBy": "LastPrice",
        "slOrderType": "Market",
        "tpslMode":    "Full",
    })

def move_sl_breakeven(symbol: str, entry: float) -> dict:
    """Move stop-loss to entry price (breakeven protection)."""
    return bybit_post("/v5/position/trading-stop", {
        "category":    "linear",
        "symbol":      symbol,
        "positionIdx": 0,
        "stopLoss":    str(round(entry, 6)),
        "slTriggerBy": "LastPrice",
        "slOrderType": "Market",
        "tpslMode":    "Full",
    })

def place_tp_order(symbol: str, direction: str, tp_price: float, qty: float) -> dict:
    """Place a conditional take-profit market order (reduce-only)."""
    close_side  = "Sell" if direction == "LONG" else "Buy"
    trigger_dir = 1 if direction == "LONG" else 2  # 1=rises to, 2=falls to
    return bybit_post("/v5/order/create", {
        "category":         "linear",
        "symbol":           symbol,
        "side":             close_side,
        "orderType":        "Market",
        "qty":              str(qty),
        "triggerPrice":     str(round(tp_price, 6)),
        "triggerDirection": trigger_dir,
        "orderFilter":      "StopOrder",
        "reduceOnly":       True,
        "timeInForce":      "GTC",
    })

def cancel_all_open_orders(symbol: str):
    bybit_post("/v5/order/cancel-all", {"category": "linear", "symbol": symbol})

def get_current_price(symbol: str) -> float:
    data = bybit_get("/v5/market/tickers", {"category": "linear", "symbol": symbol})
    if data.get("retCode") == 0 and data["result"]["list"]:
        return float(data["result"]["list"][0]["lastPrice"])
    return 0.0

# ── Position Sizing ─────────────────────────────────────────────────────────────

def calc_qty(balance: float, entry: float, sl: float, leverage: int) -> float:
    """
    Size the position so that if SL is hit, exactly RISK_PCT% of balance is lost.
    Also capped so margin used never exceeds 25% of balance.
    """
    risk_usd    = balance * RISK_PCT / 100
    sl_dist     = abs(entry - sl) / entry
    if sl_dist == 0 or entry == 0:
        return 0.0
    notional    = risk_usd / sl_dist
    qty         = notional / entry
    max_margin  = balance * 0.25
    if (notional / leverage) > max_margin:
        qty = (max_margin * leverage) / entry
    return max(round(qty, 3), 0.001)

# ── Paper Trading Engine ────────────────────────────────────────────────────────

class PaperPosition:
    def __init__(self, symbol, direction, entry, sl, tp1, tp2, tp3, qty, leverage):
        self.symbol        = symbol
        self.direction     = direction
        self.entry         = entry
        self.sl            = sl
        self.tp1           = tp1
        self.tp2           = tp2
        self.tp3           = tp3
        self.qty           = qty
        self.leverage      = leverage
        self.qty_remaining = qty
        self.tp1_hit       = False
        self.tp2_hit       = False
        self.breakeven     = False
        self.opened_at     = datetime.now(timezone.utc)

    def check(self, price: float) -> str:
        """Returns the event triggered at this price: tp1/tp2/tp3/sl/open."""
        sl_level = self.entry if self.breakeven else self.sl
        if self.direction == "LONG":
            if not self.tp1_hit and price >= self.tp1:       return "tp1"
            if self.tp1_hit and not self.tp2_hit and price >= self.tp2: return "tp2"
            if self.tp2_hit and price >= self.tp3:           return "tp3"
            if price <= sl_level:                            return "sl"
        else:
            if not self.tp1_hit and price <= self.tp1:       return "tp1"
            if self.tp1_hit and not self.tp2_hit and price <= self.tp2: return "tp2"
            if self.tp2_hit and price <= self.tp3:           return "tp3"
            if price >= sl_level:                            return "sl"
        return "open"

    def pnl(self, exit_price: float, qty: float = None) -> float:
        q = qty if qty is not None else self.qty_remaining
        mult = 1 if self.direction == "LONG" else -1
        return mult * (exit_price - self.entry) / self.entry * self.entry * q * self.leverage

# ── Daily Stats Reset ──────────────────────────────────────────────────────────

def check_reset_daily():
    global daily_stats
    today = str(date.today())
    if daily_stats["date"] != today:
        daily_stats = {"date": today, "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}

# ── Trade Execution ─────────────────────────────────────────────────────────────

async def execute_trade(result: dict, bot: Bot) -> bool:
    global paper_balance, daily_stats, total_stats, trading_active

    symbol    = result["symbol"]
    direction = result["direction"]
    entry     = result["entry"]
    sl        = result["sl"]
    tp1       = result["tp1"]
    tp2       = result["tp2"]
    tp3       = result["tp3"]
    leverage  = min(result.get("leverage_max", 5), MAX_LEVERAGE)
    score     = result["score"]
    tier      = result["tier"]
    rr        = result["rr"]

    # ── Pre-trade safety checks ────────────────────────────────────────────────
    check_reset_daily()

    if not trading_active:
        return False
    if symbol in open_positions:
        return False
    if len(open_positions) >= MAX_POSITIONS:
        log.info("Max positions reached — skipping %s" % symbol)
        return False

    balance = get_balance()
    if daily_stats["pnl"] <= -(balance * DAILY_LOSS_LIMIT / 100):
        await bot.send_message(chat_id=CHAT_ID, text=(
            "[AUTO-TRADER] Daily loss limit hit (%.1f%%).\n"
            "Trading paused until tomorrow.\nUse /resume to override." % DAILY_LOSS_LIMIT))
        trading_active = False
        return False

    qty = calc_qty(balance, entry, sl, leverage)
    if qty <= 0:
        return False

    # ── Paper Trade ────────────────────────────────────────────────────────────
    if PAPER_TRADE:
        margin_used = (qty * entry) / leverage
        paper_balance -= margin_used

        pos = PaperPosition(symbol, direction, entry, sl, tp1, tp2, tp3, qty, leverage)
        open_positions[symbol] = pos

        daily_stats["trades"] += 1
        total_stats["trades"] += 1

        await bot.send_message(chat_id=CHAT_ID, text=(
            "[PAPER] %s %s OPENED\n"
            "Score: %d/100 | %s | R/R: %.2fx\n"
            "Entry:  $%.5g\n"
            "SL:     $%.5g\n"
            "TP1:    $%.5g  [40%%]\n"
            "TP2:    $%.5g  [35%%]\n"
            "TP3:    $%.5g  [25%%]\n"
            "Qty:    %.3f | Lev: %dx\n"
            "Margin: $%.2f  |  Balance: $%.2f"
        ) % (direction, symbol, score, tier, rr,
             entry, sl, tp1, tp2, tp3, qty, leverage,
             margin_used, paper_balance))

        log.info("PAPER: %s %s qty=%.3f entry=%.5g sl=%.5g" % (direction, symbol, qty, entry, sl))
        return True

    # ── Live Trade ─────────────────────────────────────────────────────────────
    if not setup_symbol(symbol, leverage):
        log.warning("Could not set margin/leverage for %s — proceeding anyway" % symbol)

    order = place_market_order(symbol, direction, qty)
    if order.get("retCode") != 0:
        err = order.get("retMsg", "Unknown error")
        log.error("Entry order FAILED for %s: %s" % (symbol, err))
        await bot.send_message(chat_id=CHAT_ID,
            text="[AUTO-TRADER] Entry FAILED — %s\nReason: %s" % (symbol, err))
        return False

    order_id   = order["result"]["orderId"]
    fill_price = confirm_fill(symbol, order_id)

    if fill_price == 0:
        await bot.send_message(chat_id=CHAT_ID,
            text="[AUTO-TRADER] Fill NOT confirmed for %s (order %s).\nCheck Bybit immediately!" % (symbol, order_id))
        return False

    # Attach SL to position
    time.sleep(0.3)
    set_position_sl(symbol, sl)
    time.sleep(0.2)

    # Place partial TP orders
    qty1 = round(qty * TP1_CLOSE, 3)
    qty2 = round(qty * TP2_CLOSE, 3)
    qty3 = round(qty - qty1 - qty2, 3)
    place_tp_order(symbol, direction, tp1, qty1); time.sleep(0.2)
    place_tp_order(symbol, direction, tp2, qty2); time.sleep(0.2)
    place_tp_order(symbol, direction, tp3, qty3)

    open_positions[symbol] = {
        "direction": direction, "entry": fill_price,
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "qty": qty, "qty1": qty1, "qty2": qty2, "qty3": qty3,
        "leverage": leverage, "tp1_hit": False, "tp2_hit": False,
        "breakeven": False, "opened_at": datetime.now(timezone.utc),
    }
    daily_stats["trades"] += 1
    total_stats["trades"] += 1

    await bot.send_message(chat_id=CHAT_ID, text=(
        "[LIVE] %s %s OPENED\n"
        "Score: %d/100 | %s | R/R: %.2fx\n"
        "Fill:   $%.5g\n"
        "SL:     $%.5g\n"
        "TP1:    $%.5g  [40%%]\n"
        "TP2:    $%.5g  [35%%]\n"
        "TP3:    $%.5g  [25%%]\n"
        "Qty:    %.3f | Lev: %dx"
    ) % (direction, symbol, score, tier, rr,
         fill_price, sl, tp1, tp2, tp3, qty, leverage))

    log.info("LIVE: %s %s qty=%.3f fill=%.5g" % (direction, symbol, qty, fill_price))
    return True

# ── Position Monitor ────────────────────────────────────────────────────────────

async def monitor_positions(bot: Bot):
    """
    Paper mode: poll price every 30s and simulate TP/SL hits.
    Live mode:  check if Bybit still shows the position open.
    """
    global paper_balance, daily_stats, total_stats

    while True:
        await asyncio.sleep(30)

        if not open_positions:
            continue

        for symbol in list(open_positions.keys()):
            try:
                pos = open_positions[symbol]

                # ── Live mode: just verify position still exists ────────────
                if not PAPER_TRADE:
                    data = bybit_get("/v5/position/list", {"category": "linear", "symbol": symbol})
                    if data.get("retCode") == 0:
                        positions = data["result"]["list"]
                        size = float(positions[0].get("size", 0)) if positions else 0
                        if size == 0:
                            open_positions.pop(symbol, None)
                            await bot.send_message(chat_id=CHAT_ID,
                                text="[LIVE] Position closed on exchange: %s" % symbol)
                        else:
                            # Move SL to breakeven if TP1 was hit and not yet moved
                            if not pos["tp1_hit"]:
                                price = get_current_price(symbol)
                                if pos["direction"] == "LONG" and price >= pos["tp1"]:
                                    pos["tp1_hit"]  = True
                                    pos["breakeven"] = True
                                    move_sl_breakeven(symbol, pos["entry"])
                                    await bot.send_message(chat_id=CHAT_ID,
                                        text="[LIVE] TP1 area reached — %s\nSL moved to breakeven ($%.5g)" % (
                                            symbol, pos["entry"]))
                                elif pos["direction"] == "SHORT" and price <= pos["tp1"]:
                                    pos["tp1_hit"]  = True
                                    pos["breakeven"] = True
                                    move_sl_breakeven(symbol, pos["entry"])
                                    await bot.send_message(chat_id=CHAT_ID,
                                        text="[LIVE] TP1 area reached — %s\nSL moved to breakeven ($%.5g)" % (
                                            symbol, pos["entry"]))
                    continue

                # ── Paper mode: simulate ───────────────────────────────────
                price = get_current_price(symbol)
                if price == 0:
                    continue

                event = pos.check(price)

                if event == "tp1":
                    qty_closed = round(pos.qty * TP1_CLOSE, 3)
                    pnl        = pos.pnl(pos.tp1, qty_closed)
                    pos.tp1_hit       = True
                    pos.breakeven     = True
                    pos.qty_remaining = round(pos.qty_remaining - qty_closed, 3)
                    margin_back       = (qty_closed * pos.entry) / pos.leverage
                    paper_balance    += margin_back + pnl
                    daily_stats["pnl"] += pnl
                    total_stats["pnl"] += pnl
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[PAPER] TP1 HIT — %s %s\n"
                        "Price:   $%.5g\n"
                        "Profit:  +$%.2f  (40%% closed)\n"
                        "SL moved to BREAKEVEN ($%.5g)\n"
                        "35%% + 25%% still running\n"
                        "Balance: $%.2f"
                    ) % (pos.direction, symbol, pos.tp1, pnl, pos.entry, paper_balance))

                elif event == "tp2":
                    qty_closed = round(pos.qty * TP2_CLOSE, 3)
                    pnl        = pos.pnl(pos.tp2, qty_closed)
                    pos.tp2_hit       = True
                    pos.qty_remaining = round(pos.qty_remaining - qty_closed, 3)
                    margin_back       = (qty_closed * pos.entry) / pos.leverage
                    paper_balance    += margin_back + pnl
                    daily_stats["pnl"] += pnl
                    total_stats["pnl"] += pnl
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[PAPER] TP2 HIT — %s %s\n"
                        "Price:   $%.5g\n"
                        "Profit:  +$%.2f  (35%% closed)\n"
                        "25%% still running to TP3\n"
                        "Balance: $%.2f"
                    ) % (pos.direction, symbol, pos.tp2, pnl, paper_balance))

                elif event == "tp3":
                    qty_closed = pos.qty_remaining
                    pnl        = pos.pnl(pos.tp3, qty_closed)
                    margin_back       = (qty_closed * pos.entry) / pos.leverage
                    paper_balance    += margin_back + pnl
                    daily_stats["pnl"]    += pnl
                    daily_stats["wins"]   += 1
                    total_stats["pnl"]    += pnl
                    total_stats["wins"]   += 1
                    open_positions.pop(symbol)
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[PAPER] FULL WIN — %s %s\n"
                        "TP3 hit at $%.5g\n"
                        "Final profit: +$%.2f\n"
                        "Balance: $%.2f"
                    ) % (pos.direction, symbol, pos.tp3, pnl, paper_balance))

                elif event == "sl":
                    exit_price = pos.entry if pos.breakeven else pos.sl
                    pnl        = pos.pnl(exit_price, pos.qty_remaining)
                    margin_back       = (pos.qty_remaining * pos.entry) / pos.leverage
                    paper_balance    += margin_back + pnl
                    daily_stats["pnl"] += pnl
                    total_stats["pnl"] += pnl
                    if pos.breakeven:
                        daily_stats["wins"] += 1
                        total_stats["wins"] += 1
                        label = "BREAKEVEN EXIT"
                    else:
                        daily_stats["losses"] += 1
                        total_stats["losses"] += 1
                        label = "STOPPED OUT"
                    open_positions.pop(symbol)
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[PAPER] %s — %s %s\n"
                        "Exit:    $%.5g\n"
                        "P&L:     $%.2f\n"
                        "Balance: $%.2f"
                    ) % (label, pos.direction, symbol, exit_price, pnl, paper_balance))

            except Exception as e:
                log.error("Monitor error for %s: %s" % (symbol, e))

# ── Telegram Commands ───────────────────────────────────────────────────────────

async def _send_cmd_stop(bot: Bot, chat_id):
    global trading_active
    trading_active = False
    await bot.send_message(chat_id=chat_id,
        text="[AUTO-TRADER] Trading HALTED.\n"
             "No new entries. Existing positions managed.\n"
             "Use /resume to restart.")

async def _send_cmd_resume(bot: Bot, chat_id):
    global trading_active
    trading_active = True
    await bot.send_message(chat_id=chat_id, text="[AUTO-TRADER] Trading RESUMED.")

async def _send_cmd_status(bot: Bot, chat_id):
    if not open_positions:
        await bot.send_message(chat_id=chat_id, text="[AUTO-TRADER] No open positions.")
        return
    lines = ["[AUTO-TRADER] Open Positions (%d/%d):\n" % (len(open_positions), MAX_POSITIONS)]
    for sym, pos in open_positions.items():
        price = get_current_price(sym)
        if isinstance(pos, PaperPosition):
            pnl  = pos.pnl(price) if price else 0
            dur  = (datetime.now(timezone.utc) - pos.opened_at).seconds // 60
            lines.append(
                "%s %s\n"
                "  Entry: $%.5g  |  Now: $%.5g\n"
                "  P&L:   $%.2f  |  Open: %dm\n"
                "  TP1 hit: %s  |  Breakeven: %s"
                % (pos.direction, sym, pos.entry, price, pnl, dur,
                   "Yes" if pos.tp1_hit else "No",
                   "Yes" if pos.breakeven else "No"))
        else:
            lines.append("%s %s  |  Entry: $%.5g" % (pos["direction"], sym, pos["entry"]))
    await bot.send_message(chat_id=chat_id, text="\n".join(lines))

async def _send_cmd_balance(bot: Bot, chat_id):
    bal  = get_balance()
    mode = "PAPER" if PAPER_TRADE else "LIVE"
    gain = bal - PAPER_START_BAL if PAPER_TRADE else 0
    sign = "+" if gain >= 0 else ""
    msg  = "[%s] Balance: $%.2f USDT" % (mode, bal)
    if PAPER_TRADE:
        msg += "\nStarted: $%.2f  |  Change: %s$%.2f" % (PAPER_START_BAL, sign, gain)
    await bot.send_message(chat_id=chat_id, text=msg)

async def _send_cmd_performance(bot: Bot, chat_id):
    t  = total_stats
    wr = (t["wins"] / t["trades"] * 100) if t["trades"] > 0 else 0.0
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] Overall Performance\n"
        "Total Trades: %d\n"
        "Wins: %d  |  Losses: %d\n"
        "Win Rate:  %.1f%%\n"
        "Total P&L: $%.2f\n\n"
        "Today (%s)\n"
        "Trades: %d  |  Wins: %d  |  Losses: %d\n"
        "Today P&L: $%.2f"
        % (t["trades"], t["wins"], t["losses"], wr, t["pnl"],
           daily_stats["date"], daily_stats["trades"],
           daily_stats["wins"], daily_stats["losses"], daily_stats["pnl"])))

async def _send_cmd_daily(bot: Bot, chat_id):
    d  = daily_stats
    wr = (d["wins"] / d["trades"] * 100) if d["trades"] > 0 else 0.0
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] Today — %s\n"
        "Trades: %d\n"
        "Wins: %d  |  Losses: %d\n"
        "Win Rate: %.1f%%\n"
        "P&L: $%.2f"
        % (d["date"], d["trades"], d["wins"], d["losses"], wr, d["pnl"])))

async def _send_cmd_help(bot: Bot, chat_id):
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] Commands:\n"
        "/stop        — halt all new entries\n"
        "/resume      — resume trading\n"
        "/status      — open positions + live P&L\n"
        "/balance     — account balance\n"
        "/performance — all-time win rate + P&L\n"
        "/daily       — today's summary\n"
        "/help        — this message"))

async def command_listener(bot: Bot):
    """Poll Telegram for commands using raw get_updates — no Application framework needed."""
    offset = 0
    cmd_map = {
        "/stop":        _send_cmd_stop,
        "/resume":      _send_cmd_resume,
        "/status":      _send_cmd_status,
        "/balance":     _send_cmd_balance,
        "/performance": _send_cmd_performance,
        "/daily":       _send_cmd_daily,
        "/help":        _send_cmd_help,
    }
    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=10,
                                            allowed_updates=["message"])
            for upd in updates:
                offset = upd.update_id + 1
                msg = upd.message
                if not msg or not msg.text:
                    continue
                # strip bot username suffix e.g. /stop@MyBot → /stop
                cmd = msg.text.strip().lower().split("@")[0].split()[0]
                if cmd in cmd_map:
                    await cmd_map[cmd](bot, msg.chat_id)
        except Exception as e:
            log.error("Command listener error: %s" % e)
            await asyncio.sleep(5)
        await asyncio.sleep(1)

# ── Main Scan + Trade Loop ──────────────────────────────────────────────────────

async def trading_loop(bot: Bot):
    log.info("Trading loop started. PAPER_TRADE=%s" % PAPER_TRADE)
    scan_count = 0

    while True:
        scan_count += 1

        if not is_active_session():
            log.info("Scan #%d — outside session hours, sleeping." % scan_count)
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        if not trading_active:
            log.info("Scan #%d — trading paused." % scan_count)
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        if btc_is_spiking():
            log.info("Scan #%d — BTC spiking, skipping." % scan_count)
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        if btc_is_ranging():
            log.info("Scan #%d — BTC ranging (ADX<20), skipping crypto." % scan_count)
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        log.info("Scan #%d starting..." % scan_count)

        market = {
            "fear_greed": fetch_fear_greed(),
            "btc_chg":    fetch_btc_change(),
        }

        try:
            candidates = tv_scan_multi_exchange(filter_side="both", limit=100)
            candidates.sort(key=lambda x: abs(x["tv_rating"]), reverse=True)
            log.info("%d candidates from TradingView" % len(candidates))

            for tv in candidates:
                if len(open_positions) >= MAX_POSITIONS:
                    break
                if not trading_active:
                    break

                symbol = tv["symbol"]
                if time.time() - seen_signals.get(symbol, 0) < SIGNAL_COOLDOWN:
                    continue

                try:
                    k1h     = fetch_klines(symbol, "1h", 200);      time.sleep(0.15)
                    k4h     = fetch_klines(symbol, "4h", 250);      time.sleep(0.15)
                    k1d     = fetch_klines(symbol, "1d", 250);      time.sleep(0.15)
                    funding = fetch_funding_rate(symbol);            time.sleep(0.10)
                    oi_chg  = fetch_oi_change(symbol);              time.sleep(0.10)
                    ob      = fetch_order_book_imbalance(symbol);   time.sleep(0.10)

                    if not k1h or not k4h:
                        continue

                    result = score_setup(
                        tv,
                        parse_klines(k1h),
                        parse_klines(k4h),
                        parse_klines(k1d) if k1d else ([], [], [], [], []),
                        market,
                        funding=funding, oi_chg=oi_chg,
                        top_trader_ratio=fetch_top_trader_ratio(symbol),
                        taker_ratio=fetch_taker_ratio(symbol),
                        ob_imbalance=ob,
                    )

                    if result:
                        direction   = result["direction"]
                        k1h_bnb     = fetch_klines_bnb(symbol, "1h", 50); time.sleep(0.10)
                        k1h_okx     = fetch_klines_okx(symbol, "1h", 50); time.sleep(0.10)
                        exchanges   = ["Bybit"]
                        if exchange_confirms(k1h_bnb, direction): exchanges.append("Binance")
                        if exchange_confirms(k1h_okx, direction): exchanges.append("OKX")
                        boost           = {3: 15, 2: 8}.get(len(exchanges), 0)
                        result["score"] = min(100, result["score"] + boost)
                        result["exchanges"] = exchanges

                        sc, rr = result["score"], result["rr"]
                        if sc >= 88 and rr >= 3.0:   result["tier"] = "S-TIER (PREMIUM)"
                        elif sc >= 80 and rr >= 2.5: result["tier"] = "A-TIER (HIGH CONF)"
                        else:                         result["tier"] = "B-TIER (STANDARD)"

                        if result["score"] >= MIN_SCORE:
                            traded = await execute_trade(result, bot)
                            if traded:
                                seen_signals[symbol] = time.time()
                                await asyncio.sleep(2)

                except Exception as e:
                    log.error("Error processing %s: %s" % (symbol, e))

        except Exception as e:
            log.error("Scan error: %s" % e)

        log.info("Scan #%d done. Positions: %d/%d" % (scan_count, len(open_positions), MAX_POSITIONS))
        await asyncio.sleep(SCAN_INTERVAL)

# ── Entry Point ─────────────────────────────────────────────────────────────────

async def main():
    mode = "PAPER TRADING" if PAPER_TRADE else "LIVE TRADING"
    log.info("GemFinder Auto-Trader starting in %s mode" % mode)

    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(chat_id=CHAT_ID, text=(
        "[AUTO-TRADER] GemFinder Auto-Trader Online!\n\n"
        "Mode:            %s\n"
        "Risk/trade:      %.1f%% of account\n"
        "Max positions:   %d\n"
        "Daily loss cap:  %.1f%%\n"
        "Max leverage:    %dx\n"
        "%s\n\n"
        "Partial exits:\n"
        "  TP1 → close 40%%\n"
        "  TP2 → close 35%%\n"
        "  TP3 → let 25%% run\n"
        "  TP1 hit → SL moves to breakeven\n\n"
        "Commands: /stop /resume /status\n"
        "/balance /performance /daily /help\n\n"
        "Scanning every %ds. Watching the market..."
    ) % (mode, RISK_PCT, MAX_POSITIONS, DAILY_LOSS_LIMIT, MAX_LEVERAGE,
         "Paper balance: $%.2f" % paper_balance if PAPER_TRADE else "Live Bybit account connected.",
         SCAN_INTERVAL))

    await asyncio.gather(
        trading_loop(bot),
        monitor_positions(bot),
        command_listener(bot),
    )

if __name__ == "__main__":
    asyncio.run(main())
