"""
GemFinder Auto-Trader — Complete Production Build
Executes trades on Bybit based on the GemFinder signal scoring engine.
Paper trading is ON by default. Set PAPER_TRADE=false in Railway to go live.

Stage 2 safety features:
  - Slippage guard         (skip if price moved >0.5% from signal entry)
  - Anti-revenge cooldown  (30-min pause after any loss)
  - Correlation filter     (no two positions on the same base coin)
  - Funding rate filter    (skip if funding >0.1% against direction)
  - Trailing stop loss     (SL trails peak price after TP1 hit)
  - Time-based exit        (close stagnant trades after 24h)

Stage 3 production features:
  - Portfolio heat limit   (max 6% total risk across all open positions)
  - Weekly drawdown pause  (halt if down 15% in 7 days until Monday)
  - Dynamic position sizing (50% size after 2+ consecutive losses)
  - Weekly/monthly reports (auto Monday/monthly + /weekly /monthly commands)
  - Live API retry         (Bybit POST retried up to 3x on failure)

Complete build additions:
  - Position persistence   (JSON file — survives restarts, reload on startup)
  - Stats persistence      (balance, streaks, P&L survive restarts)
  - News/event blackout    (skip entries during major US economic event windows)
  - Max drawdown from peak (halt if account drops 20% from all-time high)
  - Spread/liquidity check (skip if bid/ask spread > 0.1%)
  - Compound mode          (COMPOUND_MODE=true grows size with balance; false=fixed)
  - Profit factor          (gross profit / gross loss shown in /performance)
  - Health heartbeat       (Telegram alive ping every 12 hours)
"""

import os
import time
import hmac
import hashlib
import json
import logging
import asyncio
import requests
from datetime import datetime, timezone, date, timedelta
from telegram import Bot

# Import scoring engine from the signal bot (same repo, no duplication)
from tradingview_scanner import (
    tv_scan_multi_exchange, score_setup, parse_klines,
    fetch_klines, fetch_klines_bnb, fetch_klines_okx,
    fetch_funding_rate, fetch_oi_change,
    fetch_top_trader_ratio, fetch_taker_ratio, exchange_confirms,
    is_active_session, btc_is_spiking, btc_is_ranging,
    fetch_fear_greed, fetch_btc_change,
    fetch_btc_dominance, fetch_btc_4h_trend, fetch_ls_ratio, fetch_cvd,
    fetch_eth_btc_trend, fetch_dvol, fetch_layered_ob_imbalance, fetch_dxy_signal,
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

# Stage 2 safety settings
MAX_HOLD_HOURS   = 24      # close stagnant position after 24h without TP1
SLIPPAGE_MAX_PCT = 0.5     # skip entry if price moved >0.5% from signal
REVENGE_COOLDOWN = 1800    # 30-min cool-down after any loss
TRAIL_STEP_PCT   = 0.5     # trailing SL sits 0.5% behind peak after TP1
MAX_FUND_RATE    = 0.1     # skip if funding rate >0.1% against direction

# Stage 3 production settings
PORTFOLIO_HEAT_MAX = 6.0   # max % total risk across all open positions
WEEKLY_LOSS_LIMIT  = 15.0  # % weekly drawdown that pauses trading until Monday
LOSS_STREAK_REDUCE = 2     # consecutive losses before cutting position size 50%

# Complete build settings
DATA_DIR            = os.environ.get("DATA_DIR", "/app/data")
PEAK_DRAWDOWN_LIMIT = 20.0  # halt if account drops 20% from all-time high
MAX_SPREAD_PCT      = 0.1   # skip entry if bid/ask spread > 0.1%
COMPOUND_MODE       = os.environ.get("COMPOUND_MODE", "true").lower() != "false"
HEARTBEAT_HOURS     = 12    # send alive ping every N hours

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Circuit Breaker ────────────────────────────────────────────────────────────

class CircuitBreaker:
    """Pause new entries after too many consecutive losses or a session drawdown breach."""
    def __init__(self, max_consecutive=4, daily_loss_pct=3.0, cooldown_hours=4):
        self.max_consecutive = max_consecutive
        self.daily_loss_pct  = daily_loss_pct
        self.cooldown_hours  = cooldown_hours
        self._consec         = 0
        self._daily_pnl      = 0.0
        self._paused_until   = None
        self._pause_reason   = ""

    def record(self, pnl: float, balance: float):
        self._daily_pnl += pnl
        if pnl < 0:
            self._consec += 1
        else:
            self._consec = 0
        trigger = (self._consec >= self.max_consecutive or
                   (balance > 0 and self._daily_pnl / balance * 100 <= -self.daily_loss_pct))
        if trigger and not self._paused_until:
            self._paused_until = datetime.now(timezone.utc) + timedelta(hours=self.cooldown_hours)
            self._pause_reason = ("%d consecutive losses" % self._consec
                                  if self._consec >= self.max_consecutive
                                  else "%.1f%% daily drawdown" % (self._daily_pnl / balance * 100))
            log.warning("Circuit breaker triggered: %s — pausing %dh" % (
                self._pause_reason, self.cooldown_hours))

    def is_paused(self) -> bool:
        if self._paused_until and datetime.now(timezone.utc) < self._paused_until:
            return True
        if self._paused_until and datetime.now(timezone.utc) >= self._paused_until:
            self._paused_until = None
            self._consec       = 0
            self._daily_pnl    = 0.0
            log.info("Circuit breaker reset — trading resumed")
        return False

    def reset_daily(self):
        self._daily_pnl = 0.0

    @property
    def pause_reason(self):
        return self._pause_reason

# ── Global State ───────────────────────────────────────────────────────────────
trading_active        = True
open_positions        = {}    # symbol → PaperPosition or live dict
seen_signals          = {}    # symbol → last signal timestamp (cooldown)
paper_balance         = float(PAPER_START_BAL)
peak_balance          = float(PAPER_START_BAL)   # all-time high for drawdown guard
daily_stats           = {"date": str(date.today()), "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}
total_stats           = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
                         "gross_profit": 0.0, "gross_loss": 0.0}
last_loss_time        = 0.0   # timestamp of most recent loss (anti-revenge)
consecutive_losses    = 0     # for dynamic position sizing
weekly_stats          = {}    # reset each Monday
monthly_stats         = {}    # reset each month
last_weekly_report    = ""    # ISO week key of last sent report
last_monthly_report   = ""    # YYYY-MM key of last sent monthly report
last_daily_report     = ""    # YYYY-MM-DD key of last sent daily report
bot_start_time        = datetime.now(timezone.utc)
circuit_breaker       = CircuitBreaker(max_consecutive=4, daily_loss_pct=3.0, cooldown_hours=4)

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
                    # Use walletBalance (total equity) not availableToWithdraw (free cash)
                    # so peak-drawdown compares like-for-like when positions are open
                    return float(coin.get("walletBalance") or coin.get("availableToWithdraw") or 0)
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

async def confirm_fill(symbol: str, order_id: str, retries: int = 6) -> float:
    """Poll until order is filled. Returns average fill price or 0."""
    for _ in range(retries):
        await asyncio.sleep(1)
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

def calc_qty(balance: float, entry: float, sl: float, leverage: int,
             risk_pct: float = None) -> float:
    """
    Size the position so that if SL is hit, exactly risk_pct% of balance is lost.
    Also capped so margin used never exceeds 25% of balance.
    """
    risk_usd    = balance * (risk_pct if risk_pct is not None else RISK_PCT) / 100
    if entry == 0:
        return 0.0
    sl_dist     = abs(entry - sl) / entry
    if sl_dist == 0:
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
        self.peak_price    = None   # trailing SL tracker (LONG)
        self.trough_price  = None   # trailing SL tracker (SHORT)

    def check(self, price: float) -> str:
        """Returns the event triggered at this price: tp1/tp2/tp3/sl/open."""
        sl_level = self.sl  # sl is updated to entry on TP1 hit, then trailed
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
        return mult * (exit_price - self.entry) * q

# ── Stats Reset Helpers ────────────────────────────────────────────────────────

def check_reset_daily():
    global daily_stats
    today = str(date.today())
    if daily_stats["date"] != today:
        daily_stats = {"date": today, "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}
        circuit_breaker.reset_daily()

def current_week_key() -> str:
    d = date.today()
    iso = d.isocalendar()
    return "%d-W%02d" % (iso[0], iso[1])

def check_reset_weekly():
    global weekly_stats
    wk = current_week_key()
    if weekly_stats.get("week") != wk:
        weekly_stats = {"week": wk, "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}

def effective_risk_pct() -> float:
    """Dynamic sizing: halve risk after LOSS_STREAK_REDUCE consecutive losses."""
    if consecutive_losses >= LOSS_STREAK_REDUCE:
        return RISK_PCT * 0.5
    return RISK_PCT

def paper_equity() -> float:
    """Paper equity = free cash + locked margins across all open positions.
    Used as circuit-breaker denominator so daily-drawdown % is not inflated
    by margin consumed by open trades."""
    locked = sum(
        p.qty_remaining * p.entry / p.leverage
        for p in open_positions.values()
        if isinstance(p, PaperPosition)
    )
    return paper_balance + locked

def current_month_key() -> str:
    d = date.today()
    return "%d-%02d" % (d.year, d.month)

def check_reset_monthly():
    global monthly_stats
    mk = current_month_key()
    if monthly_stats.get("month") != mk:
        monthly_stats = {"month": mk, "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}

def is_news_blackout() -> bool:
    """
    Returns True during high-impact US economic event windows (UTC).
    Avoids entries 5 min before and 15 min after major releases.
    Windows: 13:25-13:45 (CPI/NFP/retail sales), 18:55-19:15 (FOMC decisions).
    """
    now  = datetime.now(timezone.utc)
    mins = now.hour * 60 + now.minute
    blackout = [
        (13 * 60 + 25, 13 * 60 + 45),   # 13:25–13:45 UTC  (CPI, PPI, NFP, retail)
        (14 * 60 + 55, 15 * 60 + 15),   # 14:55–15:15 UTC  (some Fed speeches)
        (18 * 60 + 55, 19 * 60 + 15),   # 18:55–19:15 UTC  (FOMC rate decisions)
    ]
    return any(start <= mins <= end for start, end in blackout)

def get_spread_pct(symbol: str) -> float:
    """Return bid/ask spread as % of mid price. 0.0 on failure."""
    data = bybit_get("/v5/market/orderbook",
                     {"category": "linear", "symbol": symbol, "limit": "1"})
    if data.get("retCode") == 0:
        res  = data["result"]
        bids = res.get("b", [])
        asks = res.get("a", [])
        if bids and asks:
            bid = float(bids[0][0])
            ask = float(asks[0][0])
            mid = (bid + ask) / 2
            if mid > 0:
                return (ask - bid) / mid * 100
    return 0.0

# ── Persistence ────────────────────────────────────────────────────────────────

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def save_positions():
    _ensure_data_dir()
    rows = []
    for sym, pos in open_positions.items():
        if isinstance(pos, PaperPosition):
            rows.append({
                "type": "paper", "symbol": sym,
                "direction": pos.direction, "entry": pos.entry,
                "sl": pos.sl, "tp1": pos.tp1, "tp2": pos.tp2, "tp3": pos.tp3,
                "qty": pos.qty, "qty_remaining": pos.qty_remaining,
                "leverage": pos.leverage, "tp1_hit": pos.tp1_hit,
                "tp2_hit": pos.tp2_hit, "breakeven": pos.breakeven,
                "risk_pct_used": getattr(pos, "risk_pct_used", RISK_PCT),
                "peak_price": pos.peak_price, "trough_price": pos.trough_price,
                "opened_at": pos.opened_at.isoformat(),
            })
        else:
            row = {"type": "live", "symbol": sym}
            row.update({k: (v.isoformat() if isinstance(v, datetime) else v)
                        for k, v in pos.items()})
            rows.append(row)
    try:
        with open(os.path.join(DATA_DIR, "positions.json"), "w") as f:
            json.dump(rows, f)
    except Exception as e:
        log.error("save_positions error: %s" % e)

def load_positions():
    global open_positions
    path = os.path.join(DATA_DIR, "positions.json")
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            rows = json.load(f)
        for r in rows:
            sym = r["symbol"]
            if r["type"] == "paper":
                pos = PaperPosition(sym, r["direction"], r["entry"], r["sl"],
                                    r["tp1"], r["tp2"], r["tp3"], r["qty"], r["leverage"])
                pos.qty_remaining  = r["qty_remaining"]
                pos.tp1_hit        = r["tp1_hit"]
                pos.tp2_hit        = r["tp2_hit"]
                pos.breakeven      = r["breakeven"]
                pos.risk_pct_used  = r.get("risk_pct_used", RISK_PCT)
                pos.peak_price     = r.get("peak_price")
                pos.trough_price   = r.get("trough_price")
                pos.opened_at      = datetime.fromisoformat(r["opened_at"])
                open_positions[sym] = pos
            else:
                d = {k: v for k, v in r.items() if k not in ("type", "symbol")}
                if "opened_at" in d:
                    d["opened_at"] = datetime.fromisoformat(d["opened_at"])
                open_positions[sym] = d
        log.info("Restored %d position(s) from disk" % len(open_positions))
    except Exception as e:
        log.error("load_positions error: %s" % e)

def save_stats():
    _ensure_data_dir()
    try:
        cb_paused = circuit_breaker._paused_until.isoformat() if circuit_breaker._paused_until else None
        with open(os.path.join(DATA_DIR, "stats.json"), "w") as f:
            json.dump({
                "paper_balance":        paper_balance,
                "peak_balance":         peak_balance,
                "daily_stats":          daily_stats,
                "total_stats":          total_stats,
                "weekly_stats":         weekly_stats,
                "monthly_stats":        monthly_stats,
                "consecutive_losses":   consecutive_losses,
                "last_loss_time":       last_loss_time,
                "last_weekly_report":   last_weekly_report,
                "last_monthly_report":  last_monthly_report,
                "last_daily_report":    last_daily_report,
                "cb_consec":            circuit_breaker._consec,
                "cb_daily_pnl":         circuit_breaker._daily_pnl,
                "cb_paused_until":      cb_paused,
            }, f)
    except Exception as e:
        log.error("save_stats error: %s" % e)

def load_stats():
    global paper_balance, peak_balance, daily_stats, total_stats
    global weekly_stats, monthly_stats, consecutive_losses, last_loss_time
    global last_weekly_report, last_monthly_report, last_daily_report
    path = os.path.join(DATA_DIR, "stats.json")
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            d = json.load(f)
        paper_balance        = d.get("paper_balance",      paper_balance)
        peak_balance         = d.get("peak_balance",       peak_balance)
        daily_stats          = d.get("daily_stats",        daily_stats)
        total_stats          = d.get("total_stats",        total_stats)
        weekly_stats         = d.get("weekly_stats",       weekly_stats)
        monthly_stats        = d.get("monthly_stats",      monthly_stats)
        consecutive_losses   = d.get("consecutive_losses", 0)
        last_loss_time       = d.get("last_loss_time",     0.0)
        last_weekly_report   = d.get("last_weekly_report", "")
        last_monthly_report  = d.get("last_monthly_report", "")
        last_daily_report    = d.get("last_daily_report",  "")
        circuit_breaker._consec    = d.get("cb_consec",    0)
        circuit_breaker._daily_pnl = d.get("cb_daily_pnl", 0.0)
        cb_paused = d.get("cb_paused_until")
        if cb_paused:
            from datetime import datetime as _dt
            circuit_breaker._paused_until = _dt.fromisoformat(cb_paused)
        log.info("Stats restored from disk")
    except Exception as e:
        log.error("load_stats error: %s" % e)

# ── Bybit Retry Wrapper ────────────────────────────────────────────────────────

async def bybit_post_retry(endpoint: str, payload: dict, retries: int = 3) -> dict:
    """Retry critical Bybit POST calls up to 3x with exponential backoff."""
    result = {}
    for attempt in range(retries):
        result = bybit_post(endpoint, payload)
        if result.get("retCode") == 0:
            return result
        if attempt < retries - 1:
            await asyncio.sleep(2 ** attempt)
    return result

# ── Trade Execution ─────────────────────────────────────────────────────────────

async def execute_trade(result: dict, bot: Bot) -> bool:
    global paper_balance, peak_balance, daily_stats, total_stats, trading_active, last_loss_time, consecutive_losses

    symbol    = result["symbol"]
    direction = result["direction"]
    entry     = result["entry"]
    sl        = result["sl"]
    tp1       = result["tp1"]
    tp2       = result["tp2"]
    tp3       = result["tp3"]
    leverage  = min(result.get("leverage_max") or 5, MAX_LEVERAGE)
    score     = result["score"]
    tier      = result["tier"]
    rr        = result["rr"]

    # ── Pre-trade safety checks ────────────────────────────────────────────────
    check_reset_daily()
    check_reset_weekly()
    check_reset_monthly()

    if not trading_active:
        return False
    if circuit_breaker.is_paused():
        log.info("Circuit breaker active (%s) — skipping %s" % (circuit_breaker.pause_reason, symbol))
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

    # Complete — News/event blackout window
    if is_news_blackout():
        log.info("News blackout active — skipping %s" % symbol)
        return False

    # Complete — Max drawdown from peak using equity (free cash + locked margins)
    # Using raw paper_balance understates equity while positions are open and
    # triggers a false drawdown halt after just 1-2 normal trades.
    if PAPER_TRADE:
        locked = sum(
            (p.qty_remaining * p.entry / p.leverage)
            for p in open_positions.values()
            if isinstance(p, PaperPosition)
        )
        equity = paper_balance + locked
    else:
        equity = balance
    if equity > peak_balance:
        peak_balance = equity
    if peak_balance > 0 and (peak_balance - equity) / peak_balance * 100 >= PEAK_DRAWDOWN_LIMIT:
        await bot.send_message(chat_id=CHAT_ID, text=(
            "[AUTO-TRADER] Peak drawdown limit hit (%.1f%% from $%.2f).\n"
            "Trading paused to protect capital.\nUse /resume to override."
            % (PEAK_DRAWDOWN_LIMIT, peak_balance)))
        trading_active = False
        return False

    # Stage 3 — Weekly drawdown pause
    if weekly_stats.get("pnl", 0) <= -(balance * WEEKLY_LOSS_LIMIT / 100):
        days_left = 7 - date.today().weekday()
        await bot.send_message(chat_id=CHAT_ID, text=(
            "[AUTO-TRADER] Weekly loss limit hit (%.1f%%).\n"
            "Trading paused until Monday.\nUse /resume to override.\n"
            "Days remaining this week: %d" % (WEEKLY_LOSS_LIMIT, days_left)))
        trading_active = False
        return False

    # Stage 2 — Slippage guard: current price must be close to signal entry
    current_price = get_current_price(symbol)
    if current_price and entry:
        slippage_pct = abs(current_price - entry) / entry * 100
        if slippage_pct > SLIPPAGE_MAX_PCT:
            log.info("Slippage guard: %s moved %.2f%% from entry — skipping" % (symbol, slippage_pct))
            return False

    # Stage 2 — Anti-revenge: 30-min cool-down after any loss
    cooldown_remaining = REVENGE_COOLDOWN - (time.time() - last_loss_time)
    if cooldown_remaining > 0:
        log.info("Revenge cooldown: %dm left — skipping %s" % (int(cooldown_remaining / 60), symbol))
        return False

    # Stage 2 — Correlation filter: no two positions on the same base coin
    base = symbol.replace("USDT", "").replace("BUSD", "").replace("USD", "")
    for open_sym in open_positions:
        open_base = open_sym.replace("USDT", "").replace("BUSD", "").replace("USD", "")
        if open_base == base:
            log.info("Correlation filter: already have %s — skipping %s" % (open_sym, symbol))
            return False

    # Stage 2 — Funding rate filter: skip if funding strongly against direction
    try:
        funding = fetch_funding_rate(symbol)
        if isinstance(funding, (int, float)):
            if direction == "LONG" and funding > MAX_FUND_RATE:
                log.info("Funding filter: %.4f%% vs LONG %s — skipping" % (funding, symbol))
                return False
            if direction == "SHORT" and funding < -MAX_FUND_RATE:
                log.info("Funding filter: %.4f%% vs SHORT %s — skipping" % (funding, symbol))
                return False
    except Exception:
        pass

    # Complete — Spread/liquidity check
    try:
        spread = get_spread_pct(symbol)
        if spread > MAX_SPREAD_PCT:
            log.info("Spread guard: %s spread=%.3f%% > %.1f%% — skipping" % (
                symbol, spread, MAX_SPREAD_PCT))
            return False
    except Exception:
        pass

    # ── Dynamic position sizing modifiers ─────────────────────────────────────
    eff_risk  = effective_risk_pct()
    size_mult = 1.0
    # Weekend liquidity reduction (lower volume = wider slippage, weaker signals)
    weekday = datetime.now(timezone.utc).weekday()   # 5=Sat, 6=Sun
    if weekday >= 5:
        size_mult *= 0.5
    # Score-tiered sizing: reward high-conviction signals, reduce marginal ones
    if score >= 92:
        size_mult *= 1.25
    elif score < 83:
        size_mult *= 0.75
    eff_risk = eff_risk * size_mult

    # Stage 3 — Portfolio heat check runs after size multipliers so the real
    # capital consumption is compared against the cap (not the pre-multiplier value)
    current_heat = sum(
        getattr(p, "risk_pct_used", RISK_PCT) if isinstance(p, PaperPosition)
        else p.get("risk_pct_used", RISK_PCT)
        for p in open_positions.values()
    )
    if current_heat + eff_risk > PORTFOLIO_HEAT_MAX:
        log.info("Portfolio heat %.1f%% + %.1f%% > %.1f%% — skipping %s" % (
            current_heat, eff_risk, PORTFOLIO_HEAT_MAX, symbol))
        return False

    # Complete — Compound mode: use current balance or fixed starting balance
    sizing_balance = balance if COMPOUND_MODE else float(PAPER_START_BAL)
    qty = calc_qty(sizing_balance, entry, sl, leverage, eff_risk)
    if qty <= 0:
        return False

    # ── Paper Trade ────────────────────────────────────────────────────────────
    if PAPER_TRADE:
        margin_used = (qty * entry) / leverage
        paper_balance -= margin_used

        pos = PaperPosition(symbol, direction, entry, sl, tp1, tp2, tp3, qty, leverage)
        pos.risk_pct_used = eff_risk   # for portfolio heat tracking
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
        save_positions()
        save_stats()
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
    fill_price = await confirm_fill(symbol, order_id)

    if fill_price == 0:
        await bot.send_message(chat_id=CHAT_ID,
            text="[AUTO-TRADER] Fill NOT confirmed for %s (order %s).\nCheck Bybit immediately!" % (symbol, order_id))
        return False

    # Attach SL to position (with retry for reliability)
    await asyncio.sleep(0.3)
    await bybit_post_retry("/v5/position/trading-stop", {
        "category": "linear", "symbol": symbol, "positionIdx": 0,
        "stopLoss": str(round(sl, 6)), "slTriggerBy": "LastPrice",
        "slOrderType": "Market", "tpslMode": "Full",
    })
    await asyncio.sleep(0.2)

    # Place partial TP orders
    qty1 = round(qty * TP1_CLOSE, 3)
    qty2 = round(qty * TP2_CLOSE, 3)
    qty3 = round(qty - qty1 - qty2, 3)
    place_tp_order(symbol, direction, tp1, qty1); await asyncio.sleep(0.2)
    place_tp_order(symbol, direction, tp2, qty2); await asyncio.sleep(0.2)
    place_tp_order(symbol, direction, tp3, qty3)

    open_positions[symbol] = {
        "direction": direction, "entry": fill_price,
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "qty": qty, "qty1": qty1, "qty2": qty2, "qty3": qty3,
        "leverage": leverage, "tp1_hit": False, "tp2_hit": False,
        "breakeven": False, "opened_at": datetime.now(timezone.utc),
        "opened_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "risk_pct_used": eff_risk,
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
    save_positions()
    save_stats()
    return True

# ── Position Monitor ────────────────────────────────────────────────────────────

async def monitor_positions(bot: Bot):
    """
    Paper mode: poll price every 30s and simulate TP/SL hits.
    Live mode:  check if Bybit still shows the position open.
    """
    global paper_balance, peak_balance, daily_stats, total_stats, last_loss_time, consecutive_losses, weekly_stats, monthly_stats

    while True:
        await asyncio.sleep(30)
        check_reset_daily()
        check_reset_weekly()
        check_reset_monthly()

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
                            # Fetch realized PnL from Bybit closed-pnl endpoint
                            cpnl = 0.0
                            try:
                                # Sum all partial fills (TP1+TP2+TP3/SL) since position opened
                                opened_ms = int(pos.get("opened_at_ms", 0)) if isinstance(pos, dict) else 0
                                cp = bybit_get("/v5/position/closed-pnl", {
                                    "category": "linear", "symbol": symbol, "limit": 50,
                                    **({"startTime": str(opened_ms)} if opened_ms else {})
                                })
                                if cp.get("retCode") == 0 and cp["result"]["list"]:
                                    cpnl = sum(float(r.get("closedPnl", 0)) for r in cp["result"]["list"])
                            except Exception:
                                pass
                            daily_stats["pnl"]   += cpnl
                            total_stats["pnl"]   += cpnl
                            weekly_stats["pnl"]   = weekly_stats.get("pnl", 0) + cpnl
                            monthly_stats["pnl"]  = monthly_stats.get("pnl", 0) + cpnl
                            weekly_stats["trades"]  = weekly_stats.get("trades", 0) + 1
                            monthly_stats["trades"] = monthly_stats.get("trades", 0) + 1
                            if cpnl >= 0:
                                daily_stats["wins"]  += 1
                                total_stats["wins"]  += 1
                                total_stats["gross_profit"] = total_stats.get("gross_profit", 0.0) + cpnl
                                weekly_stats["wins"]  = weekly_stats.get("wins", 0) + 1
                                monthly_stats["wins"] = monthly_stats.get("wins", 0) + 1
                                consecutive_losses = 0
                            else:
                                daily_stats["losses"]  += 1
                                total_stats["losses"]  += 1
                                total_stats["gross_loss"] = total_stats.get("gross_loss", 0.0) + abs(cpnl)
                                weekly_stats["losses"]  = weekly_stats.get("losses", 0) + 1
                                monthly_stats["losses"] = monthly_stats.get("losses", 0) + 1
                                consecutive_losses += 1
                                last_loss_time = time.time()
                            circuit_breaker.record(cpnl, get_balance())
                            open_positions.pop(symbol, None)
                            save_positions()
                            save_stats()
                            await bot.send_message(chat_id=CHAT_ID,
                                text="[LIVE] %s closed\nRealized P&L: $%.2f" % (symbol, cpnl))
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
                    pos.sl            = pos.entry   # SL moves to breakeven; trailing improves from here
                    pos.qty_remaining = round(pos.qty_remaining - qty_closed, 3)
                    margin_back       = (qty_closed * pos.entry) / pos.leverage
                    paper_balance    += margin_back + pnl
                    if paper_balance > peak_balance:
                        peak_balance = paper_balance
                    daily_stats["pnl"] += pnl
                    total_stats["pnl"] += pnl
                    weekly_stats["pnl"]  = weekly_stats.get("pnl", 0) + pnl
                    monthly_stats["pnl"] = monthly_stats.get("pnl", 0) + pnl
                    circuit_breaker.record(pnl, paper_equity())
                    save_positions()
                    save_stats()
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[PAPER] TP1 HIT — %s %s\n"
                        "Price:   $%.5g\n"
                        "Profit:  +$%.2f  (40%% closed)\n"
                        "SL moved to BREAKEVEN ($%.5g)\n"
                        "Trailing SL now active\n"
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
                    if paper_balance > peak_balance:
                        peak_balance = paper_balance
                    daily_stats["pnl"] += pnl
                    total_stats["pnl"] += pnl
                    weekly_stats["pnl"]  = weekly_stats.get("pnl", 0) + pnl
                    monthly_stats["pnl"] = monthly_stats.get("pnl", 0) + pnl
                    circuit_breaker.record(pnl, paper_equity())
                    save_positions()
                    save_stats()
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
                    if paper_balance > peak_balance:
                        peak_balance = paper_balance
                    daily_stats["pnl"]    += pnl
                    daily_stats["wins"]   += 1
                    total_stats["pnl"]    += pnl
                    total_stats["wins"]   += 1
                    total_stats["gross_profit"] = total_stats.get("gross_profit", 0.0) + max(pnl, 0)
                    weekly_stats["pnl"]    = weekly_stats.get("pnl", 0) + pnl
                    weekly_stats["wins"]   = weekly_stats.get("wins", 0) + 1
                    weekly_stats["trades"] = weekly_stats.get("trades", 0) + 1
                    monthly_stats["pnl"]    = monthly_stats.get("pnl", 0) + pnl
                    monthly_stats["wins"]   = monthly_stats.get("wins", 0) + 1
                    monthly_stats["trades"] = monthly_stats.get("trades", 0) + 1
                    size_note = "  Size was reduced (loss streak)" if consecutive_losses >= LOSS_STREAK_REDUCE else ""
                    consecutive_losses    = 0   # win resets streak
                    open_positions.pop(symbol, None)   # pop first so paper_equity() doesn't double-count margin
                    circuit_breaker.record(pnl, paper_equity())
                    save_positions()
                    save_stats()
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[PAPER] FULL WIN — %s %s\n"
                        "TP3 hit at $%.5g\n"
                        "Final profit: +$%.2f%s\n"
                        "Balance: $%.2f"
                    ) % (pos.direction, symbol, pos.tp3, pnl, size_note, paper_balance))

                elif event == "sl":
                    exit_price = pos.sl   # entry/trailing if TP1 hit, else original SL
                    pnl        = pos.pnl(exit_price, pos.qty_remaining)
                    margin_back       = (pos.qty_remaining * pos.entry) / pos.leverage
                    paper_balance    += margin_back + pnl
                    if paper_balance > peak_balance:
                        peak_balance = paper_balance
                    daily_stats["pnl"]      += pnl
                    total_stats["pnl"]      += pnl
                    weekly_stats["pnl"]      = weekly_stats.get("pnl", 0) + pnl
                    weekly_stats["trades"]   = weekly_stats.get("trades", 0) + 1
                    monthly_stats["pnl"]     = monthly_stats.get("pnl", 0) + pnl
                    monthly_stats["trades"]  = monthly_stats.get("trades", 0) + 1
                    if pos.breakeven:
                        daily_stats["wins"]  += 1
                        total_stats["wins"]  += 1
                        total_stats["gross_profit"] = total_stats.get("gross_profit", 0.0) + max(pnl, 0)
                        weekly_stats["wins"]  = weekly_stats.get("wins", 0) + 1
                        monthly_stats["wins"] = monthly_stats.get("wins", 0) + 1
                        consecutive_losses   = 0
                        label = "BREAKEVEN/TRAIL EXIT"
                    else:
                        daily_stats["losses"]  += 1
                        total_stats["losses"]  += 1
                        total_stats["gross_loss"] = total_stats.get("gross_loss", 0.0) + abs(min(pnl, 0))
                        weekly_stats["losses"]  = weekly_stats.get("losses", 0) + 1
                        monthly_stats["losses"] = monthly_stats.get("losses", 0) + 1
                        consecutive_losses += 1
                        last_loss_time = time.time()
                        label = "STOPPED OUT"
                        if consecutive_losses >= LOSS_STREAK_REDUCE:
                            label += " (size halved next trade)"
                    open_positions.pop(symbol, None)   # pop first so paper_equity() doesn't double-count margin
                    circuit_breaker.record(pnl, paper_equity())
                    save_positions()
                    save_stats()
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[PAPER] %s — %s %s\n"
                        "Exit:    $%.5g\n"
                        "P&L:     $%.2f\n"
                        "Balance: $%.2f"
                    ) % (label, pos.direction, symbol, exit_price, pnl, paper_balance))

                # Stage 2 — Trailing SL: update after TP1 hit on each 30s poll
                if symbol in open_positions and pos.tp1_hit:
                    if pos.direction == "LONG":
                        if pos.peak_price is None or price > pos.peak_price:
                            pos.peak_price = price
                            trail_sl = round(price * (1 - TRAIL_STEP_PCT / 100), 8)
                            if trail_sl > pos.sl:
                                pos.sl = trail_sl
                                log.info("Trail SL %s LONG → $%.6g" % (symbol, trail_sl))
                    else:
                        if pos.trough_price is None or price < pos.trough_price:
                            pos.trough_price = price
                            trail_sl = round(price * (1 + TRAIL_STEP_PCT / 100), 8)
                            if trail_sl < pos.sl:
                                pos.sl = trail_sl
                                log.info("Trail SL %s SHORT → $%.6g" % (symbol, trail_sl))

                # Stage 2 — Time-based exit: close if stagnant >24h without TP1
                if symbol in open_positions and not pos.tp1_hit:
                    hours_open = (datetime.now(timezone.utc) - pos.opened_at).total_seconds() / 3600
                    if hours_open > MAX_HOLD_HOURS:
                        pnl         = pos.pnl(price, pos.qty_remaining)
                        margin_back = (pos.qty_remaining * pos.entry) / pos.leverage
                        paper_balance    += margin_back + pnl
                        if paper_balance > peak_balance:
                            peak_balance = paper_balance
                        daily_stats["pnl"]      += pnl
                        total_stats["pnl"]      += pnl
                        weekly_stats["pnl"]      = weekly_stats.get("pnl", 0) + pnl
                        weekly_stats["trades"]   = weekly_stats.get("trades", 0) + 1
                        monthly_stats["pnl"]     = monthly_stats.get("pnl", 0) + pnl
                        monthly_stats["trades"]  = monthly_stats.get("trades", 0) + 1
                        if pnl >= 0:
                            daily_stats["wins"]  += 1
                            total_stats["wins"]  += 1
                            total_stats["gross_profit"] = total_stats.get("gross_profit", 0.0) + pnl
                            weekly_stats["wins"]  = weekly_stats.get("wins", 0) + 1
                            monthly_stats["wins"] = monthly_stats.get("wins", 0) + 1
                            consecutive_losses = 0
                        else:
                            daily_stats["losses"]  += 1
                            total_stats["losses"]  += 1
                            total_stats["gross_loss"] = total_stats.get("gross_loss", 0.0) + abs(pnl)
                            weekly_stats["losses"]  = weekly_stats.get("losses", 0) + 1
                            monthly_stats["losses"] = monthly_stats.get("losses", 0) + 1
                            consecutive_losses += 1
                            last_loss_time = time.time()
                        open_positions.pop(symbol, None)   # pop first so paper_equity() doesn't double-count margin
                        circuit_breaker.record(pnl, paper_equity())
                        save_positions()
                        save_stats()
                        await bot.send_message(chat_id=CHAT_ID, text=(
                            "[PAPER] TIME EXIT (24h) — %s %s\n"
                            "Never reached TP1. Closed at market.\n"
                            "Exit:    $%.5g\n"
                            "P&L:     $%.2f\n"
                            "Balance: $%.2f"
                        ) % (pos.direction, symbol, price, pnl, paper_balance))

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
            dur  = int((datetime.now(timezone.utc) - pos.opened_at).total_seconds()) // 60
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
    dd   = (peak_balance - bal) / peak_balance * 100 if peak_balance > 0 else 0.0
    msg  = "[%s] Balance: $%.2f USDT" % (mode, bal)
    if PAPER_TRADE:
        msg += "\nStarted:  $%.2f  |  Change: %s$%.2f" % (PAPER_START_BAL, sign, gain)
    msg += "\nPeak:     $%.2f  |  Drawdown: %.1f%%" % (peak_balance, dd)
    await bot.send_message(chat_id=chat_id, text=msg)

async def _send_cmd_performance(bot: Bot, chat_id):
    check_reset_daily()
    t  = total_stats
    wr = (t["wins"] / t["trades"] * 100) if t["trades"] > 0 else 0.0
    gp = t.get("gross_profit", 0.0)
    gl = t.get("gross_loss",   0.0)
    pf = (gp / gl) if gl > 0 else float("inf")
    pf_str = "%.2f" % pf if pf != float("inf") else "∞"
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] Overall Performance\n"
        "Total Trades: %d\n"
        "Wins: %d  |  Losses: %d\n"
        "Win Rate:     %.1f%%\n"
        "Total P&L:    $%.2f\n"
        "Gross Profit: $%.2f\n"
        "Gross Loss:   $%.2f\n"
        "Profit Factor: %s\n\n"
        "Today (%s)\n"
        "Trades: %d  |  Wins: %d  |  Losses: %d\n"
        "Today P&L: $%.2f"
        % (t["trades"], t["wins"], t["losses"], wr, t["pnl"],
           gp, gl, pf_str,
           daily_stats["date"], daily_stats["trades"],
           daily_stats["wins"], daily_stats["losses"], daily_stats["pnl"])))

async def _send_cmd_daily(bot: Bot, chat_id):
    check_reset_daily()
    d  = daily_stats
    wr = (d["wins"] / d["trades"] * 100) if d["trades"] > 0 else 0.0
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] Today — %s\n"
        "Trades: %d\n"
        "Wins: %d  |  Losses: %d\n"
        "Win Rate: %.1f%%\n"
        "P&L: $%.2f"
        % (d["date"], d["trades"], d["wins"], d["losses"], wr, d["pnl"])))

async def _send_cmd_monthly(bot: Bot, chat_id):
    check_reset_monthly()
    m  = monthly_stats
    tr = m.get("trades", 0)
    wr = (m.get("wins", 0) / tr * 100) if tr > 0 else 0.0
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] This Month — %s\n"
        "Trades: %d\n"
        "Wins: %d  |  Losses: %d\n"
        "Win Rate: %.1f%%\n"
        "Monthly P&L: $%.2f"
    ) % (m.get("month", "—"), tr, m.get("wins", 0), m.get("losses", 0), wr,
         m.get("pnl", 0.0)))

async def _send_cmd_help(bot: Bot, chat_id):
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] Commands:\n"
        "/stop        — halt all new entries\n"
        "/resume      — resume trading\n"
        "/status      — open positions + live P&L\n"
        "/balance     — account balance + drawdown\n"
        "/performance — all-time win rate + profit factor\n"
        "/daily       — today's summary\n"
        "/weekly      — this week's summary\n"
        "/monthly     — this month's summary\n"
        "/help        — this message"))

async def _send_cmd_weekly(bot: Bot, chat_id):
    check_reset_weekly()
    w  = weekly_stats
    tr = w.get("trades", 0)
    wr = (w.get("wins", 0) / tr * 100) if tr > 0 else 0.0
    streak_note = ("\nLoss streak: %d — position size at 50%%" % consecutive_losses
                   if consecutive_losses >= LOSS_STREAK_REDUCE else "")
    await bot.send_message(chat_id=chat_id, text=(
        "[AUTO-TRADER] This Week — %s\n"
        "Trades: %d\n"
        "Wins: %d  |  Losses: %d\n"
        "Win Rate: %.1f%%\n"
        "Weekly P&L: $%.2f%s"
    ) % (w.get("week", "—"), tr, w.get("wins", 0), w.get("losses", 0), wr,
         w.get("pnl", 0.0), streak_note))

async def daily_reporter(bot: Bot):
    """Auto-send daily P&L summary at UTC midnight (hour 0–1)."""
    global last_daily_report
    while True:
        try:
            now   = datetime.now(timezone.utc)
            today = str(date.today())
            if now.hour < 2 and last_daily_report != today:
                snap = dict(daily_stats)
                check_reset_daily()
                last_daily_report = today
                save_stats()
                if snap.get("trades", 0) > 0 and snap.get("date", "") != today:
                    wr = (snap["wins"] / snap["trades"] * 100) if snap["trades"] > 0 else 0.0
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[AUTO-TRADER] Daily Report — %s\n"
                        "Trades:   %d\n"
                        "Wins: %d  |  Losses: %d\n"
                        "Win Rate: %.1f%%\n"
                        "Day P&L:  $%.2f"
                    ) % (snap["date"], snap["trades"], snap["wins"],
                         snap["losses"], wr, snap["pnl"]))
                    log.info("Daily report sent for %s" % snap["date"])
        except Exception as e:
            log.error("Daily reporter error: %s" % e)
        await asyncio.sleep(3600)

async def weekly_reporter(bot: Bot):
    """Auto-send weekly report every Monday at 00:00–02:00 UTC."""
    global last_weekly_report
    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.weekday() == 0 and now.hour < 2:
                wk = current_week_key()
                if last_weekly_report != wk:
                    snap = dict(weekly_stats)
                    check_reset_weekly()
                    last_weekly_report = wk
                    save_stats()
                    tr = snap.get("trades", 0)
                    wr = (snap.get("wins", 0) / tr * 100) if tr > 0 else 0.0
                    streak_note = ("\nLoss streak: %d — size at 50%%" % consecutive_losses
                                   if consecutive_losses >= LOSS_STREAK_REDUCE else "")
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[AUTO-TRADER] Weekly Report — %s\n"
                        "Trades: %d\n"
                        "Wins: %d  |  Losses: %d\n"
                        "Win Rate: %.1f%%\n"
                        "Weekly P&L: $%.2f%s"
                    ) % (snap.get("week", "—"), tr, snap.get("wins", 0),
                         snap.get("losses", 0), wr, snap.get("pnl", 0.0), streak_note))
                    log.info("Weekly report sent for %s" % wk)
        except Exception as e:
            log.error("Weekly reporter error: %s" % e)
        await asyncio.sleep(3600)

async def monthly_reporter(bot: Bot):
    """Auto-send monthly report on 1st of each month at 00:00–02:00 UTC."""
    global last_monthly_report
    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.day == 1 and now.hour < 2:
                mk = current_month_key()
                if last_monthly_report != mk:
                    snap = dict(monthly_stats)
                    check_reset_monthly()
                    last_monthly_report = mk
                    save_stats()
                    tr = snap.get("trades", 0)
                    wr = (snap.get("wins", 0) / tr * 100) if tr > 0 else 0.0
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[AUTO-TRADER] Monthly Report — %s\n"
                        "Trades: %d\n"
                        "Wins: %d  |  Losses: %d\n"
                        "Win Rate: %.1f%%\n"
                        "Monthly P&L: $%.2f"
                    ) % (snap.get("month", "—"), tr, snap.get("wins", 0),
                         snap.get("losses", 0), wr, snap.get("pnl", 0.0)))
                    log.info("Monthly report sent for %s" % mk)
        except Exception as e:
            log.error("Monthly reporter error: %s" % e)
        await asyncio.sleep(3600)

async def heartbeat(bot: Bot):
    """Send an alive ping every HEARTBEAT_HOURS hours."""
    while True:
        await asyncio.sleep(HEARTBEAT_HOURS * 3600)
        try:
            bal    = get_balance()
            mode   = "PAPER" if PAPER_TRADE else "LIVE"
            uptime = datetime.now(timezone.utc) - bot_start_time
            hours  = int(uptime.total_seconds() // 3600)
            await bot.send_message(chat_id=CHAT_ID, text=(
                "[AUTO-TRADER] Heartbeat — still running\n"
                "Mode:      %s\n"
                "Balance:   $%.2f\n"
                "Uptime:    %dh\n"
                "Positions: %d/%d\n"
                "Trading:   %s"
            ) % (mode, bal, hours, len(open_positions), MAX_POSITIONS,
                 "Active" if trading_active else "PAUSED"))
            log.info("Heartbeat sent — uptime %dh, balance $%.2f" % (hours, bal))
        except Exception as e:
            log.error("Heartbeat error: %s" % e)

_CMD_MAP = {}  # populated in command_listener; guarded below against empty state

async def _dispatch_command(data: dict, bot: Bot):
    """Handle one raw Telegram update dict (from webhook or polling)."""
    try:
        if not _CMD_MAP:
            return
        msg = data.get("message") or data.get("edited_message")
        if not msg:
            return
        text    = msg.get("text", "")
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not text or not chat_id:
            return
        cmd = text.strip().lower().split("@")[0].split()[0]
        if cmd in _CMD_MAP:
            await _CMD_MAP[cmd](bot, chat_id)
    except Exception as e:
        log.error("dispatch_command error: %s" % e)

async def command_listener(bot: Bot):
    """
    Webhook mode when RAILWAY_PUBLIC_DOMAIN is set — zero getUpdates calls,
    zero conflict with other services sharing the same token.
    Falls back to long-polling when running outside Railway.
    """
    global _CMD_MAP
    _CMD_MAP = {
        "/stop":        _send_cmd_stop,
        "/resume":      _send_cmd_resume,
        "/status":      _send_cmd_status,
        "/balance":     _send_cmd_balance,
        "/performance": _send_cmd_performance,
        "/daily":       _send_cmd_daily,
        "/weekly":      _send_cmd_weekly,
        "/monthly":     _send_cmd_monthly,
        "/help":        _send_cmd_help,
    }

    # BOT_WEBHOOK_HOST takes priority; falls back to RAILWAY_PUBLIC_DOMAIN
    domain = (os.environ.get("BOT_WEBHOOK_HOST", "")
              or os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")).strip()
    port   = int(os.environ.get("PORT", "8080"))
    log.info("Webhook domain resolved: '%s' (port %d)" % (domain, port))

    if domain:
        # ── Webhook mode (Railway) ─────────────────────────────────────────
        try:
            from aiohttp import web as aio_web

            webhook_url = "https://%s/tg" % domain
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(webhook_url)
            log.info("Webhook set: %s" % webhook_url)

            async def _handle(request):
                try:
                    data = await request.json()
                    asyncio.create_task(_dispatch_command(data, bot))
                except Exception as e:
                    log.error("Webhook handler: %s" % e)
                return aio_web.Response(text="ok")

            app    = aio_web.Application()
            app.router.add_post("/tg", _handle)
            runner = aio_web.AppRunner(app)
            await runner.setup()
            await aio_web.TCPSite(runner, "0.0.0.0", port).start()
            log.info("Webhook server on :%d — commands active" % port)

            while True:
                await asyncio.sleep(3600)

        except ImportError:
            log.warning("aiohttp not installed — falling back to polling")
            domain = ""   # trigger polling fallback below

    if not domain:
        # ── Polling fallback (local / no public domain) ────────────────────
        log.info("Polling mode active (no RAILWAY_PUBLIC_DOMAIN)")
        await bot.delete_webhook(drop_pending_updates=True)
        offset = 0
        while True:
            try:
                updates = await bot.get_updates(offset=offset, timeout=10,
                                                allowed_updates=["message"])
                for upd in updates:
                    offset = upd.update_id + 1
                    msg = upd.message
                    if not msg or not msg.text:
                        continue
                    cmd = msg.text.strip().lower().split("@")[0].split()[0]
                    if cmd in _CMD_MAP:
                        await _CMD_MAP[cmd](bot, str(msg.chat_id))
            except Exception as e:
                log.error("Command listener error: %s" % e)
                await asyncio.sleep(5)
            await asyncio.sleep(1)

# ── Main Scan + Trade Loop ──────────────────────────────────────────────────────

async def trading_loop(bot: Bot):
    log.info("Trading loop started. PAPER_TRADE=%s" % PAPER_TRADE)
    scan_count         = 0
    btc_was_ranging    = False
    last_ranging_alert = 0.0

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

        btc_ranging = btc_is_ranging()
        if btc_ranging:
            log.info("Scan #%d — BTC ranging (ADX<20), skipping crypto." % scan_count)
            if not btc_was_ranging:
                try:
                    fgi = fetch_fear_greed()
                    btc_chg = fetch_btc_change()
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[AUTO-TRADER] BTC ranging — trading paused\n\n"
                        "BTC 4h ADX dropped below 20.\n"
                        "No new entries until BTC trends again.\n\n"
                        "FGI: %d  |  BTC: %+.2f%%\n\n"
                        "I will notify you when trading resumes."
                    ) % (fgi, btc_chg))
                except Exception as e:
                    log.error("Ranging start alert error: %s" % e)
                last_ranging_alert = time.time()
                btc_was_ranging = True
            elif time.time() - last_ranging_alert >= 3600:
                try:
                    fgi = fetch_fear_greed()
                    btc_chg = fetch_btc_change()
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[AUTO-TRADER] Still ranging — Scan #%d\n\n"
                        "BTC 4h ADX still below 20. No trades until trend returns.\n"
                        "FGI: %d  |  BTC: %+.2f%%"
                    ) % (scan_count, fgi, btc_chg))
                except Exception as e:
                    log.error("Ranging hourly alert error: %s" % e)
                last_ranging_alert = time.time()
            await asyncio.sleep(SCAN_INTERVAL)
            continue
        else:
            if btc_was_ranging:
                try:
                    fgi = fetch_fear_greed()
                    btc_chg = fetch_btc_change()
                    await bot.send_message(chat_id=CHAT_ID, text=(
                        "[AUTO-TRADER] BTC trending again — trading resumed!\n\n"
                        "FGI: %d  |  BTC: %+.2f%%\n\n"
                        "Watching for high-quality setups..."
                    ) % (fgi, btc_chg))
                except Exception as e:
                    log.error("Ranging end alert error: %s" % e)
            btc_was_ranging = False

        log.info("Scan #%d starting..." % scan_count)

        market = {
            "fear_greed":    fetch_fear_greed(),
            "btc_chg":       fetch_btc_change(),
            "btc_4h_trend":  fetch_btc_4h_trend(),
            "btc_dom":       fetch_btc_dominance(),
            "eth_btc_trend": fetch_eth_btc_trend(),
            "dvol":          fetch_dvol(),
            "dxy_rating":    fetch_dxy_signal(),
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
                    k1h     = fetch_klines(symbol, "1h", 200);         await asyncio.sleep(0.15)
                    k4h     = fetch_klines(symbol, "4h", 250);         await asyncio.sleep(0.15)
                    k1d     = fetch_klines(symbol, "1d", 250);         await asyncio.sleep(0.15)
                    funding = fetch_funding_rate(symbol);               await asyncio.sleep(0.10)
                    oi_chg  = fetch_oi_change(symbol);                 await asyncio.sleep(0.10)
                    ob_t1, ob_t2, ob_t3 = fetch_layered_ob_imbalance(symbol); await asyncio.sleep(0.10)
                    ob      = ob_t1  # tier1 ratio kept for backward-compat scoring
                    cvd     = fetch_cvd(symbol);                       await asyncio.sleep(0.10)
                    # Binance L/S ratio uses base symbol only (e.g. BTCUSDT not BTCUSDT.P)
                    ls_r    = fetch_ls_ratio(symbol);                  await asyncio.sleep(0.10)

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
                        cvd=cvd,
                        ls_ratio=ls_r,
                    )

                    if result:
                        direction   = result["direction"]
                        k1h_bnb     = fetch_klines_bnb(symbol, "1h", 50); await asyncio.sleep(0.10)
                        k1h_okx     = fetch_klines_okx(symbol, "1h", 50); await asyncio.sleep(0.10)
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
    global paper_balance, peak_balance
    mode = "PAPER TRADING" if PAPER_TRADE else "LIVE TRADING"
    log.info("GemFinder Auto-Trader starting in %s mode" % mode)

    # Restore persisted state from previous run
    load_stats()
    check_reset_daily()
    check_reset_weekly()
    check_reset_monthly()
    load_positions()
    log.info("Startup — balance=$%.2f  peak=$%.2f  positions=%d" % (
        paper_balance, peak_balance, len(open_positions)))

    bot = Bot(token=TELEGRAM_TOKEN)

    # Clear any stale webhook from previous deploys
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Stale webhook cleared")

    restored_note = ""
    if open_positions:
        restored_note = "\nRestored %d open position(s) from disk." % len(open_positions)

    await bot.send_message(chat_id=CHAT_ID, text=(
        "[AUTO-TRADER] GemFinder Auto-Trader Online!\n\n"
        "Mode:            %s\n"
        "Risk/trade:      %.1f%% of account\n"
        "Max positions:   %d\n"
        "Daily loss cap:  %.1f%%\n"
        "Max leverage:    %dx\n"
        "Compound mode:   %s\n"
        "%s%s\n\n"
        "Partial exits:\n"
        "  TP1 → close 40%%\n"
        "  TP2 → close 35%%\n"
        "  TP3 → let 25%% run\n"
        "  TP1 hit → SL moves to breakeven + trailing SL\n\n"
        "Safety: news blackout | spread guard | funding filter\n"
        "        peak drawdown limit | portfolio heat cap\n\n"
        "Commands: /stop /resume /status /balance\n"
        "/performance /daily /weekly /monthly /help\n\n"
        "Heartbeat every %dh. Scanning every %ds..."
    ) % (mode, RISK_PCT, MAX_POSITIONS, DAILY_LOSS_LIMIT, MAX_LEVERAGE,
         "ON" if COMPOUND_MODE else "OFF",
         "Paper balance: $%.2f  |  Peak: $%.2f" % (paper_balance, peak_balance)
             if PAPER_TRADE else "Live Bybit account connected.",
         restored_note, HEARTBEAT_HOURS, SCAN_INTERVAL))

    await asyncio.gather(
        trading_loop(bot),
        monitor_positions(bot),
        command_listener(bot),
        daily_reporter(bot),
        weekly_reporter(bot),
        monthly_reporter(bot),
        heartbeat(bot),
    )

if __name__ == "__main__":
    asyncio.run(main())
