import os
import time
import math
import logging
import requests
import asyncio
from telegram import Bot
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID         = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
SCAN_INTERVAL   = 300        # 5 minutes between scans
MIN_SCORE       = 72         # minimum confluence score to send
MIN_RR          = 2.0        # minimum risk/reward ratio
SIGNAL_COOLDOWN = 7200       # 2 hours cooldown per symbol
MAX_SIGNALS     = 3          # max signals per scan cycle

BYBIT_BASE      = "https://api.bybit.com"
BINANCE_BASE    = "https://fapi.binance.com"
OKX_BASE        = "https://www.okx.com"
INTERVAL_MAP    = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
                   "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
                   "1d": "D", "1w": "W"}
FEAR_GREED_URL  = "https://api.alternative.me/fng/?limit=1"
TV_SCAN_URL     = "https://scanner.tradingview.com/crypto/scan"
TV_FOREX_URL    = "https://scanner.tradingview.com/forex/scan"
TV_STOCKS_URL   = "https://scanner.tradingview.com/america/scan"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════════
# TRADINGVIEW SCANNER
# ════════════════════════════════════════════════════════════════════════════════

TV_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

def tv_scan(filter_side="both", limit=50, exchange="BINANCE"):
    """
    Query TradingView's public screener for crypto futures pairs on a given exchange.
    Returns a list of dicts with symbol + raw indicator values.
    """
    columns = [
        "name", "close", "change", "volume", "market_cap_calc",
        "Recommend.All",       # overall TradingView rating  (-1 to +1)
        "Recommend.MA",        # moving-average rating
        "Recommend.Other",     # oscillator rating
        "RSI",
        "RSI[1]",
        "MACD.macd",
        "MACD.signal",
        "Mom",                 # momentum
        "EMA20",
        "EMA50",
        "EMA200",
        "BB.upper",
        "BB.lower",
        "ATR",
        "Stoch.K",
        "Stoch.D",
        "ADX",
        "CCI20",
        "W.R",                 # Williams %R
        "VWAP",
        "average_volume_10d_calc",
    ]

    filters = [
        {"left": "exchange", "operation": "equal", "right": exchange},
        {"left": "typespecs", "operation": "has_none_of", "right": ["spot"]},
        {"left": "volume", "operation": "greater", "right": 10000000},
    ]

    if filter_side == "long":
        filters.append({"left": "Recommend.All", "operation": "greater", "right": 0.1})
    elif filter_side == "short":
        filters.append({"left": "Recommend.All", "operation": "less", "right": -0.1})

    payload = {
        "filter": filters,
        "columns": columns,
        "sort": {"sortBy": "volume", "sortOrder": "desc"},
        "options": {"lang": "en"},
        "range": [0, limit],
    }

    try:
        r = requests.post(TV_SCAN_URL, json=payload, headers=TV_HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning("TV scanner HTTP %d" % r.status_code)
            return []
        data = r.json().get("data", [])
        results = []
        for row in data:
            sym = row.get("s", "")           # e.g. "BINANCE:BTCUSDT.P"
            vals = row.get("d", [])
            if len(vals) < len(columns): continue

            # Normalise symbol: strip exchange prefix and contract suffix
            clean = sym.split(":")[-1].replace(".P", "").replace(".F", "").upper()
            if not clean.endswith("USDT"): continue

            results.append({
                "symbol":       clean,
                "tv_symbol":    sym,
                "close":        vals[1]  or 0,
                "change":       vals[2]  or 0,
                "volume":       vals[3]  or 0,
                "tv_rating":    vals[5]  or 0,   # Recommend.All
                "tv_ma":        vals[6]  or 0,
                "tv_osc":       vals[7]  or 0,
                "rsi":          vals[8]  or 50,
                "rsi_prev":     vals[9]  or 50,
                "macd":         vals[10] or 0,
                "macd_sig":     vals[11] or 0,
                "momentum":     vals[12] or 0,
                "ema20":        vals[13] or 0,
                "ema50":        vals[14] or 0,
                "ema200":       vals[15] or 0,
                "bb_upper":     vals[16] or 0,
                "bb_lower":     vals[17] or 0,
                "atr":          vals[18] or 0,
                "stoch_k":      vals[19] or 50,
                "stoch_d":      vals[20] or 50,
                "adx":          vals[21] or 0,
                "cci":          vals[22] or 0,
                "williams_r":   vals[23] or -50,
                "vwap":         vals[24] or 0,
                "avg_vol_10d":  vals[25] or 1,
            })
        return results
    except Exception as e:
        log.warning("TV scan error: %s" % e)
        return []


def tv_scan_multi_exchange(filter_side="both", limit=50):
    """
    Query TradingView for BINANCE + BYBIT + OKX crypto futures.
    Deduplicates by symbol; keeps the row with the strongest TV rating.
    """
    seen = {}
    for ex in ["BINANCE", "BYBIT", "OKX"]:
        rows = tv_scan(filter_side=filter_side, limit=limit, exchange=ex)
        for row in rows:
            sym = row["symbol"]
            if sym not in seen or abs(row["tv_rating"]) > abs(seen[sym]["tv_rating"]):
                seen[sym] = row
        time.sleep(0.5)
    return list(seen.values())


def tv_scan_forex(filter_side="both", limit=30):
    """
    Query TradingView forex screener for major/minor FX pairs.
    Returns a list of dicts with symbol + raw TV indicator values.
    """
    columns = [
        "name", "close", "change", "volume",
        "Recommend.All", "Recommend.MA", "Recommend.Other",
        "RSI", "RSI[1]",
        "MACD.macd", "MACD.signal",
        "Mom",
        "EMA20", "EMA50", "EMA200",
        "ATR",
        "Stoch.K", "Stoch.D",
        "ADX",
        "CCI20",
        "W.R",
    ]

    filters = []
    if filter_side == "long":
        filters.append({"left": "Recommend.All", "operation": "greater", "right": 0.2})
    elif filter_side == "short":
        filters.append({"left": "Recommend.All", "operation": "less", "right": -0.2})

    payload = {
        "filter": filters,
        "columns": columns,
        "sort": {"sortBy": "Recommend.All", "sortOrder": "desc"},
        "options": {"lang": "en"},
        "range": [0, limit],
    }

    try:
        r = requests.post(TV_FOREX_URL, json=payload, headers=TV_HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning("TV forex scanner HTTP %d" % r.status_code)
            return []
        data = r.json().get("data", [])
        results = []
        for row in data:
            sym  = row.get("s", "")
            vals = row.get("d", [])
            if len(vals) < len(columns): continue

            clean = sym.split(":")[-1].upper()
            if not clean or len(clean) < 6: continue

            results.append({
                "symbol":      clean,
                "tv_symbol":   sym,
                "asset_class": "forex",
                "close":       vals[1]  or 0,
                "change":      vals[2]  or 0,
                "volume":      vals[3]  or 0,
                "tv_rating":   vals[4]  or 0,
                "tv_ma":       vals[5]  or 0,
                "tv_osc":      vals[6]  or 0,
                "rsi":         vals[7]  or 50,
                "rsi_prev":    vals[8]  or 50,
                "macd":        vals[9]  or 0,
                "macd_sig":    vals[10] or 0,
                "momentum":    vals[11] or 0,
                "ema20":       vals[12] or 0,
                "ema50":       vals[13] or 0,
                "ema200":      vals[14] or 0,
                "atr":         vals[15] or 0,
                "stoch_k":     vals[16] or 50,
                "stoch_d":     vals[17] or 50,
                "adx":         vals[18] or 0,
                "cci":         vals[19] or 0,
                "williams_r":  vals[20] or -50,
            })
        return results
    except Exception as e:
        log.warning("TV forex scan error: %s" % e)
        return []


def tv_scan_stocks(filter_side="both", limit=30):
    """
    Query TradingView US stocks screener (NYSE + NASDAQ) for high-volume equity signals.
    Only liquid stocks above $5 with >5M daily volume are considered.
    """
    columns = [
        "name", "close", "change", "volume",
        "Recommend.All", "Recommend.MA", "Recommend.Other",
        "RSI", "RSI[1]",
        "MACD.macd", "MACD.signal",
        "Mom",
        "EMA20", "EMA50", "EMA200",
        "ATR",
        "Stoch.K", "Stoch.D",
        "ADX",
        "CCI20",
        "W.R",
    ]

    filters = [
        {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ"]},
        {"left": "volume",   "operation": "greater",  "right": 5000000},
        {"left": "close",    "operation": "greater",  "right": 5},
    ]

    if filter_side == "long":
        filters.append({"left": "Recommend.All", "operation": "greater", "right": 0.2})
    elif filter_side == "short":
        filters.append({"left": "Recommend.All", "operation": "less", "right": -0.2})

    payload = {
        "filter": filters,
        "columns": columns,
        "sort": {"sortBy": "volume", "sortOrder": "desc"},
        "options": {"lang": "en"},
        "range": [0, limit],
    }

    try:
        r = requests.post(TV_STOCKS_URL, json=payload, headers=TV_HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning("TV stocks scanner HTTP %d" % r.status_code)
            return []
        data = r.json().get("data", [])
        results = []
        for row in data:
            sym  = row.get("s", "")
            vals = row.get("d", [])
            if len(vals) < len(columns): continue

            clean = sym.split(":")[-1].upper()
            if not clean: continue

            results.append({
                "symbol":      clean,
                "tv_symbol":   sym,
                "asset_class": "stocks",
                "close":       vals[1]  or 0,
                "change":      vals[2]  or 0,
                "volume":      vals[3]  or 0,
                "tv_rating":   vals[4]  or 0,
                "tv_ma":       vals[5]  or 0,
                "tv_osc":      vals[6]  or 0,
                "rsi":         vals[7]  or 50,
                "rsi_prev":    vals[8]  or 50,
                "macd":        vals[9]  or 0,
                "macd_sig":    vals[10] or 0,
                "momentum":    vals[11] or 0,
                "ema20":       vals[12] or 0,
                "ema50":       vals[13] or 0,
                "ema200":      vals[14] or 0,
                "atr":         vals[15] or 0,
                "stoch_k":     vals[16] or 50,
                "stoch_d":     vals[17] or 50,
                "adx":         vals[18] or 0,
                "cci":         vals[19] or 0,
                "williams_r":  vals[20] or -50,
            })
        return results
    except Exception as e:
        log.warning("TV stocks scan error: %s" % e)
        return []


def tv_rating_label(val):
    """Map TradingView -1..+1 rating to human label."""
    if val >= 0.5:   return "STRONG BUY"
    if val >= 0.1:   return "BUY"
    if val <= -0.5:  return "STRONG SELL"
    if val <= -0.1:  return "SELL"
    return "NEUTRAL"

# ════════════════════════════════════════════════════════════════════════════════
# BINANCE DATA
# ════════════════════════════════════════════════════════════════════════════════

def safe_get(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("HTTP %s: %s" % (url[:55], e))
    return None

def fetch_klines(symbol, interval, limit=200):
    bybit_interval = INTERVAL_MAP.get(interval, interval)
    data = safe_get("%s/v5/market/kline?category=linear&symbol=%s&interval=%s&limit=%s" % (
        BYBIT_BASE, symbol, bybit_interval, limit))
    if data and data.get("retCode") == 0:
        return list(reversed(data["result"]["list"]))
    return []

def fetch_funding_rate(symbol):
    data = safe_get("%s/v5/market/funding/history?category=linear&symbol=%s&limit=3" % (
        BYBIT_BASE, symbol))
    if data and data.get("retCode") == 0:
        entries = data["result"]["list"]
        if entries:
            return float(entries[0].get("fundingRate", 0)) * 100
    return 0.0

def fetch_oi_change(symbol):
    data = safe_get("%s/v5/market/open-interest?category=linear&symbol=%s&intervalTime=1h&limit=8" % (
        BYBIT_BASE, symbol))
    if data and data.get("retCode") == 0:
        entries = data["result"]["list"]
        if len(entries) >= 2:
            new = float(entries[0].get("openInterest", 1))
            old = float(entries[-1].get("openInterest", 1))
            return (new - old) / old * 100 if old else 0
    return 0.0

def fetch_top_trader_ratio(symbol):
    data = safe_get("%s/futures/data/topLongShortPositionRatio?symbol=%s&period=1h&limit=1" % (
        BINANCE_BASE, symbol))
    if data and isinstance(data, list) and data:
        return float(data[-1].get("longShortRatio", 1.0))
    return 1.0

def fetch_taker_ratio(symbol):
    data = safe_get("%s/futures/data/takerlongshortRatio?symbol=%s&period=1h&limit=1" % (
        BINANCE_BASE, symbol))
    if data and isinstance(data, list) and data:
        entry = data[-1]
        buy_vol  = float(entry.get("buyVol",  1))
        sell_vol = float(entry.get("sellVol", 1))
        return round(buy_vol / sell_vol, 3) if sell_vol > 0 else 1.0
    return 1.0

# ════════════════════════════════════════════════════════════════════════════════
# BINANCE & OKX — CROSS-EXCHANGE CONFIRMATION
# ════════════════════════════════════════════════════════════════════════════════

def to_okx(symbol):
    return "%s-USDT-SWAP" % symbol.replace("USDT", "")

def fetch_klines_bnb(symbol, interval, limit=100):
    bi = {"1h": "1h", "4h": "4h", "1d": "1d", "15m": "15m"}.get(interval, interval)
    data = safe_get("%s/fapi/v1/klines?symbol=%s&interval=%s&limit=%d" % (
        BINANCE_BASE, symbol, bi, limit))
    if data and isinstance(data, list):
        return data  # oldest first: [ts, open, high, low, close, vol, ...]
    return []

def fetch_klines_okx(symbol, interval, limit=100):
    bar = {"1h": "1H", "4h": "4H", "1d": "1D", "15m": "15m"}.get(interval, interval)
    data = safe_get("%s/api/v5/market/candles?instId=%s&bar=%s&limit=%d" % (
        OKX_BASE, to_okx(symbol), bar, limit))
    if data and data.get("code") == "0":
        return list(reversed(data["data"]))  # reverse to oldest first
    return []

def fetch_funding_bnb(symbol):
    data = safe_get("%s/fapi/v1/fundingRate?symbol=%s&limit=1" % (BINANCE_BASE, symbol))
    if data and isinstance(data, list) and data:
        return float(data[-1].get("fundingRate", 0)) * 100
    return 0.0

def fetch_funding_okx(symbol):
    data = safe_get("%s/api/v5/public/funding-rate?instId=%s" % (OKX_BASE, to_okx(symbol)))
    if data and data.get("code") == "0" and data.get("data"):
        return float(data["data"][0].get("fundingRate", 0)) * 100
    return 0.0

def fetch_ob_bnb(symbol, depth=20):
    data = safe_get("%s/fapi/v1/depth?symbol=%s&limit=%d" % (BINANCE_BASE, symbol, depth))
    if data:
        bid_val = sum(float(b[0]) * float(b[1]) for b in data.get("bids", []))
        ask_val = sum(float(a[0]) * float(a[1]) for a in data.get("asks", []))
        return round(bid_val / ask_val, 3) if ask_val > 0 else 1.0
    return 1.0

def exchange_confirms(klines_1h, direction):
    """Quick RSI + EMA check: does this exchange agree with the signal direction?"""
    if not klines_1h or len(klines_1h) < 21:
        return None
    _, _, _, closes, _ = parse_klines(klines_1h)
    if not closes:
        return None
    r   = rsi(closes)
    e21 = ema(closes, 21)
    p   = closes[-1]
    if direction == "LONG":
        return r < 65 and p > e21 * 0.985
    return r > 35 and p < e21 * 1.015

def fetch_order_book_imbalance(symbol, depth=20):
    """
    Bid $ value / Ask $ value from the top N levels of the order book.
    >1.5 = large buy walls (price supported).  <0.67 = large sell walls.
    """
    data = safe_get("%s/v5/market/orderbook?category=linear&symbol=%s&limit=%d" % (
        BYBIT_BASE, symbol, depth))
    if data and data.get("retCode") == 0:
        result = data["result"]
        bid_val = sum(float(b[0]) * float(b[1]) for b in result.get("b", []))
        ask_val = sum(float(a[0]) * float(a[1]) for a in result.get("a", []))
        return round(bid_val / ask_val, 3) if ask_val > 0 else 1.0
    return 1.0

def fetch_fear_greed():
    data = safe_get(FEAR_GREED_URL)
    if data and data.get("data"):
        return int(data["data"][0].get("value", 50))
    return 50

def fetch_btc_change():
    data = safe_get("%s/v5/market/tickers?category=linear&symbol=BTCUSDT" % BYBIT_BASE)
    if data and data.get("retCode") == 0:
        tickers = data["result"]["list"]
        if tickers:
            return float(tickers[0].get("price24hPcnt", 0)) * 100
    return 0.0

def btc_is_spiking():
    """
    True if BTC moved >2% on any of the last 3 × 15m candles.
    Signals fired into violent BTC moves have a far lower hit rate —
    stop-hunts and cascading liquidations make all setups unreliable.
    """
    data = safe_get("%s/v5/market/kline?category=linear&symbol=BTCUSDT&interval=15&limit=4" % BYBIT_BASE)
    if not data or data.get("retCode") != 0:
        return False
    klines = list(reversed(data["result"]["list"]))
    if len(klines) < 3:
        return False
    for k in klines[-3:]:
        o, c = float(k[1]), float(k[4])
        if o > 0 and abs(c - o) / o * 100 > 2.0:
            return True
    return False

# ════════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS (pure-Python, no deps)
# ════════════════════════════════════════════════════════════════════════════════

def parse_klines(klines):
    if not klines: return [], [], [], [], []
    return (
        [float(k[1]) for k in klines],
        [float(k[2]) for k in klines],
        [float(k[3]) for k in klines],
        [float(k[4]) for k in klines],
        [float(k[5]) for k in klines],
    )

def ema(closes, period):
    if len(closes) < period: return closes[-1] if closes else 0
    k = 2.0 / (period + 1)
    e = sum(closes[:period]) / period
    for p in closes[period:]:
        e = p * k + e * (1 - k)
    return e

def rsi(closes, period=14):
    if len(closes) < period + 1: return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    return 100 - (100 / (1 + ag / al))

def macd_hist(closes, fast=12, slow=26, signal_p=9):
    if len(closes) < slow + signal_p: return 0, 0
    ema_f = ema(closes, fast)
    ema_s = ema(closes, slow)
    macd_line = ema_f - ema_s
    hist_vals = [ema(closes[:i], fast) - ema(closes[:i], slow)
                 for i in range(slow, len(closes) + 1)]
    sig = sum(hist_vals[-signal_p:]) / len(hist_vals[-signal_p:]) if len(hist_vals) >= signal_p else macd_line
    return macd_line - sig, macd_line

def atr(highs, lows, closes, period=14):
    if len(closes) < 2: return closes[-1] * 0.02
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i-1]),
               abs(lows[i]  - closes[i-1]))
           for i in range(1, len(closes))]
    return sum(trs[-period:]) / min(len(trs), period)

def adx_value(highs, lows, closes, period=14):
    """
    Average Directional Index via Wilder smoothing.
    >20 = trending market (safe to trade momentum signals).
    >30 = strong trend (high-confidence setup).
    <20 = choppy/ranging — signals here are coin-flips, skip them.
    """
    if len(closes) < period * 2:
        return 0
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(closes)):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        plus_dm.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        tr_list.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1])
        ))

    def wilder(data, p):
        s = sum(data[:p])
        out = [s]
        for v in data[p:]:
            s = s - (s / p) + v
            out.append(s)
        return out

    atr_s = wilder(tr_list, period)
    pdm_s = wilder(plus_dm, period)
    mdm_s = wilder(minus_dm, period)

    dx_vals = []
    for a, p, m in zip(atr_s, pdm_s, mdm_s):
        if a == 0:
            dx_vals.append(0)
            continue
        pdi = 100 * p / a
        mdi = 100 * m / a
        denom = pdi + mdi
        dx_vals.append(100 * abs(pdi - mdi) / denom if denom > 0 else 0)

    return sum(dx_vals[-period:]) / period if len(dx_vals) >= period else 0


def is_active_session():
    """
    True during London (08:00-17:00 UTC) or New York (13:00-22:00 UTC).
    The Asia dead-zone (22:00-08:00 UTC) has ~3x lower volume and
    produces far more false breakouts — skip scanning during that window.
    """
    hour = datetime.now(timezone.utc).hour
    return (8 <= hour < 17) or (13 <= hour < 22)   # covers 08:00-22:00 UTC


def is_us_market_open():
    """True during US stock market hours: 09:30-16:00 ET = 13:30-20:00 UTC."""
    now      = datetime.now(timezone.utc)
    time_min = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= time_min < 20 * 60


def candle_structure(opens, closes, required=2, window=3):
    """
    Returns (bull_count, bear_count) of directional closes in the last `window` candles.
    A LONG signal needs bull_count >= required; SHORT needs bear_count >= required.
    Entering against immediate price action (e.g. LONG while last 3 candles all red)
    is the single biggest source of premature entries.
    """
    bull = sum(1 for i in range(-window, 0) if closes[i] > opens[i])
    bear = sum(1 for i in range(-window, 0) if closes[i] < opens[i])
    return bull, bear


def bb_squeeze_state(closes, period=20, std_dev=2, expand_lookback=8):
    """
    Returns (is_expanding, bb_width_pct).
    is_expanding = True when BBands are widening after a squeeze.
    Entries at a BB squeeze breakout ride the full directional move;
    entries into already-wide bands often catch the tail end.
    """
    if len(closes) < period + expand_lookback:
        return False, 0.0

    def bb_width(window):
        mid = sum(window) / len(window)
        std = (sum((x - mid) ** 2 for x in window) / len(window)) ** 0.5
        return (std * std_dev * 2) / mid if mid > 0 else 0

    widths = [bb_width(closes[-(period + expand_lookback - i):-(expand_lookback - i)])
              for i in range(expand_lookback)]
    widths = [w for w in widths if w > 0]
    if len(widths) < 3:
        return False, 0.0

    current_width  = widths[-1]
    avg_prior      = sum(widths[:-2]) / len(widths[:-2])
    is_expanding   = current_width > avg_prior * 1.08   # 8% wider than prior avg
    return is_expanding, round(current_width * 100, 2)


def liquidity_sweep(highs, lows, closes, opens, sweep_window=5, ref_window=20):
    """
    Smart Money / ICT liquidity sweep detector.

    BULLISH sweep: within the last `sweep_window` candles, a wick dipped
    BELOW the lowest low of the prior `ref_window` candles, but the candle
    CLOSED back above that level.  Smart money grabbed sell-side liquidity
    (cleared stop-losses below the swing low) then drove price back up.

    BEARISH sweep: wick above the highest high of prior range, closed below.
    Smart money grabbed buy-side liquidity above the swing high.

    This is the highest-conviction entry in Smart Money Concepts — you're
    entering AFTER weak hands have been flushed out.
    """
    if len(closes) < ref_window + sweep_window + 2:
        return False, False

    ref_slice  = slice(-(ref_window + sweep_window), -sweep_window)
    ref_low    = min(lows[ref_slice])
    ref_high   = max(highs[ref_slice])

    bull_sweep = False
    bear_sweep = False

    for i in range(-sweep_window, 0):
        # Wick below prior swing low, but candle closed above it
        if lows[i] < ref_low and closes[i] > ref_low:
            bull_sweep = True
        # Wick above prior swing high, but candle closed below it
        if highs[i] > ref_high and closes[i] < ref_high:
            bear_sweep = True

    return bull_sweep, bear_sweep


def find_sr_zones(highs, lows, closes, tolerance=0.006):
    """
    Only zones tested 3+ times are considered significant.
    Uses last 100 candles so daily-level structure is captured.
    """
    levels = list(highs[-100:]) + list(lows[-100:])
    levels.sort()
    zones, used = [], set()
    for i, lvl in enumerate(levels):
        if i in used: continue
        cluster = [lvl]
        for j in range(i + 1, len(levels)):
            if j not in used and abs(levels[j] - lvl) / lvl <= tolerance:
                cluster.append(levels[j])
                used.add(j)
        if len(cluster) >= 3:                # 3-touch minimum for a real zone
            zones.append(sum(cluster) / len(cluster))
        used.add(i)
    price = closes[-1]
    supports    = sorted([z for z in zones if z < price], reverse=True)
    resistances = sorted([z for z in zones if z > price])
    return supports[:4], resistances[:4]

def calculate_leverage_and_sizing(score, atr_val, price, rr):
    """
    Volatility-adjusted leverage + 2% account-risk position sizing.

    Formula: if you allocate `alloc%` of your account at leverage L,
    and SL is `sl_pct%` away from entry, your loss when stopped is:
        alloc x L x sl_pct / 100  (as % of account)
    Solving for alloc with a fixed 2% account risk per trade:
        alloc = 200 / (L x sl_pct)

    Leverage ceiling is reduced for high-volatility coins (large ATR%),
    then given a small boost when R/R is exceptional (>= 3.5).
    """
    atr_pct = (atr_val / price * 100) if price > 0 else 2.0
    sl_pct  = atr_pct * 1.8   # matches the 1.8x ATR stop in score_setup

    # Base leverage ceiling by score tier
    if score >= 88 and rr >= 3.0:
        max_lev = 10
    elif score >= 80 and rr >= 2.5:
        max_lev = 7
    else:
        max_lev = 5

    # Reduce leverage for high-volatility coins
    if atr_pct > 4.0:
        max_lev = max(2, max_lev - 4)
    elif atr_pct > 2.5:
        max_lev = max(2, max_lev - 2)
    elif atr_pct > 1.5:
        max_lev = max(2, max_lev - 1)

    # R/R bonus: great reward potential justifies slightly more exposure
    if rr >= 3.5 and max_lev < 15:
        max_lev += 1

    # Position allocation that keeps loss at exactly 2% of account
    alloc_pct = round(200.0 / (max_lev * sl_pct), 1) if sl_pct > 0 else 5.0
    alloc_pct = min(alloc_pct, 25.0)   # never more than 25% of account per trade

    # Conservative and aggressive ends of the recommendation band
    lev_low  = max(2, max_lev - 2)
    lev_high = max_lev
    lev_label = "%d-%dx" % (lev_low, lev_high) if lev_low != lev_high else "%dx" % lev_high

    return {
        "leverage":     max_lev,
        "lev_label":    lev_label,
        "alloc_pct":    alloc_pct,
        "atr_pct":      round(atr_pct, 2),
        "sl_pct":       round(sl_pct, 2),
    }


def market_structure(highs, lows, lookback=5):
    sh, sl = [], []
    for i in range(lookback, len(highs) - lookback):
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            sh.append(highs[i])
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            sl.append(lows[i])
    if len(sh) < 2 or len(sl) < 2:
        return "RANGING"
    hh = all(sh[i] > sh[i-1] for i in range(1, min(3, len(sh))))
    hl = all(sl[i] > sl[i-1] for i in range(1, min(3, len(sl))))
    lh = all(sh[i] < sh[i-1] for i in range(1, min(3, len(sh))))
    ll = all(sl[i] < sl[i-1] for i in range(1, min(3, len(sl))))
    if hh and hl: return "UPTREND"
    if lh and ll: return "DOWNTREND"
    return "RANGING"

# ════════════════════════════════════════════════════════════════════════════════
# SCORING ENGINE
# ════════════════════════════════════════════════════════════════════════════════

def score_setup(tv, k1h_data, k4h_data, k1d_data, market, funding=0.0, oi_chg=0.0,
                top_trader_ratio=1.0, taker_ratio=1.0, ob_imbalance=1.0):
    """
    Score a symbol using TradingView ratings + Bybit candle confirmation.
    Daily candles used as HTF trend filter. Funding + OI gate extreme conditions.
    Returns a dict with direction, score, entry/SL/TP, and reasons.
    """
    o1h, h1h, l1h, c1h, v1h = k1h_data
    o4h, h4h, l4h, c4h, v4h = k4h_data
    o1d, h1d, l1d, c1d, v1d = k1d_data

    if not c1h or not c4h:
        return None

    price = c1h[-1]
    if price == 0:
        return None

    tv_rating  = tv["tv_rating"]
    tv_ma      = tv["tv_ma"]
    tv_osc     = tv["tv_osc"]

    # ── Bybit indicators ────────────────────────────────────────────────────
    rsi1h  = rsi(c1h)
    rsi4h  = rsi(c4h)
    rsi1d  = rsi(c1d) if c1d else 50
    mh1h, ml1h = macd_hist(c1h)
    mh4h, _    = macd_hist(c4h)

    ema21_1h  = ema(c1h, 21)
    ema50_1h  = ema(c1h, 50)
    ema200_1h = ema(c1h, min(200, len(c1h)))
    ema50_4h  = ema(c4h, 50)
    ema200_4h = ema(c4h, min(200, len(c4h)))
    ema50_1d  = ema(c1d, min(50, len(c1d))) if c1d else 0
    ema200_1d = ema(c1d, min(200, len(c1d))) if c1d else 0

    atr1h = atr(h1h, l1h, c1h)
    atr4h = atr(h4h, l4h, c4h)

    adx4h = adx_value(h4h, l4h, c4h)

    # ── ADX gate: skip choppy/ranging markets ────────────────────────────────
    if adx4h < 20:
        return None

    avg_vol   = sum(v1h[-20:]) / 20 if len(v1h) >= 20 else v1h[-1]
    vol_spike = v1h[-1] / avg_vol if avg_vol > 0 else 1

    trend_1h = market_structure(h1h, l1h)
    trend_4h = market_structure(h4h, l4h)
    trend_1d = market_structure(h1d, l1d) if h1d else "RANGING"

    # Use 4h S/R zones — better balance of recency and significance
    supports, resistances = find_sr_zones(h4h, l4h, c4h)

    # ── HTF trend gate ────────────────────────────────────────────────────────
    daily_bull = price > ema200_1d if ema200_1d else None
    daily_bear = price < ema200_1d if ema200_1d else None
    if daily_bull is not None:
        if tv_rating > 0 and daily_bear:
            return None
        if tv_rating < 0 and daily_bull:
            return None

    # ── Funding rate gate ─────────────────────────────────────────────────────
    if tv_rating > 0 and funding > 0.05:
        return None
    if tv_rating < 0 and funding < -0.05:
        return None

    # ── Candle structure gate ─────────────────────────────────────────────────
    bull_candles, bear_candles = candle_structure(o1h, c1h)
    if tv_rating > 0 and bull_candles < 2:
        return None
    if tv_rating < 0 and bear_candles < 2:
        return None

    # ── Pattern detectors (score bonuses) ────────────────────────────────────
    bb_expanding, bb_width_pct = bb_squeeze_state(c1h)
    bull_sweep, bear_sweep     = liquidity_sweep(h1h, l1h, c1h, o1h)

    fear_greed = market.get("fear_greed", 50)
    btc_chg    = market.get("btc_chg", 0)

    long_score  = 0
    short_score = 0
    long_reasons  = []
    short_reasons = []

    # 1. TradingView rating (max 35 pts)
    if tv_rating >= 0.5:
        long_score += 35; long_reasons.append("TV STRONG BUY (rating %.2f)" % tv_rating)
    elif tv_rating >= 0.2:
        long_score += 20; long_reasons.append("TV BUY (rating %.2f)" % tv_rating)
    elif tv_rating >= 0.1:
        long_score += 10

    if tv_rating <= -0.5:
        short_score += 35; short_reasons.append("TV STRONG SELL (rating %.2f)" % tv_rating)
    elif tv_rating <= -0.2:
        short_score += 20; short_reasons.append("TV SELL (rating %.2f)" % tv_rating)
    elif tv_rating <= -0.1:
        short_score += 10

    # TV MA sub-score (max 10)
    if tv_ma >= 0.3:
        long_score += 10; long_reasons.append("TV MA bullish (%.2f)" % tv_ma)
    elif tv_ma <= -0.3:
        short_score += 10; short_reasons.append("TV MA bearish (%.2f)" % tv_ma)

    # TV oscillator sub-score (max 10)
    if tv_osc >= 0.3:
        long_score += 10; long_reasons.append("TV oscillators bullish (%.2f)" % tv_osc)
    elif tv_osc <= -0.3:
        short_score += 10; short_reasons.append("TV oscillators bearish (%.2f)" % tv_osc)

    # 2. RSI confirmation (max 20)
    if rsi1h < 30:
        long_score += 12; long_reasons.append("RSI 1h oversold (%.1f)" % rsi1h)
    elif rsi1h < 40:
        long_score += 6;  long_reasons.append("RSI 1h low (%.1f)" % rsi1h)
    if rsi4h < 35:
        long_score += 8;  long_reasons.append("RSI 4h oversold (%.1f)" % rsi4h)

    if rsi1h > 70:
        short_score += 12; short_reasons.append("RSI 1h overbought (%.1f)" % rsi1h)
    elif rsi1h > 60:
        short_score += 6;  short_reasons.append("RSI 1h high (%.1f)" % rsi1h)
    if rsi4h > 65:
        short_score += 8;  short_reasons.append("RSI 4h overbought (%.1f)" % rsi4h)

    # 3. MACD multi-TF (max 15)
    if mh1h > 0 and mh4h > 0:
        long_score += 15; long_reasons.append("MACD bullish 1h + 4h")
    elif mh1h > 0:
        long_score += 8;  long_reasons.append("MACD bullish 1h")
    if mh1h < 0 and mh4h < 0:
        short_score += 15; short_reasons.append("MACD bearish 1h + 4h")
    elif mh1h < 0:
        short_score += 8;  short_reasons.append("MACD bearish 1h")

    # 4. EMA alignment (max 15)
    if price > ema21_1h > ema50_1h > ema200_1h:
        long_score += 15; long_reasons.append("EMA 21>50>200 bullish stack")
    elif price > ema21_1h > ema50_1h:
        long_score += 8;  long_reasons.append("EMA 21 > 50 bullish")
    if price < ema21_1h < ema50_1h < ema200_1h:
        short_score += 15; short_reasons.append("EMA 21<50<200 bearish stack")
    elif price < ema21_1h < ema50_1h:
        short_score += 8;  short_reasons.append("EMA 21 < 50 bearish")

    # 5. Trend structure (max 15)
    if trend_1d == "UPTREND" and trend_4h == "UPTREND" and trend_1h == "UPTREND":
        long_score += 15; long_reasons.append("Aligned uptrend daily+4h+1h")
    elif trend_4h == "UPTREND" and trend_1h == "UPTREND":
        long_score += 10; long_reasons.append("Market structure uptrend 4h+1h")
    elif trend_4h == "UPTREND":
        long_score += 5
    if trend_1d == "DOWNTREND" and trend_4h == "DOWNTREND" and trend_1h == "DOWNTREND":
        short_score += 15; short_reasons.append("Aligned downtrend daily+4h+1h")
    elif trend_4h == "DOWNTREND" and trend_1h == "DOWNTREND":
        short_score += 10; short_reasons.append("Market structure downtrend 4h+1h")
    elif trend_4h == "DOWNTREND":
        short_score += 5

    # Daily EMA bonus
    if daily_bull and ema50_1d and price > ema50_1d:
        long_score += 8; long_reasons.append("Price above Daily EMA 50 & 200 (with trend)")
    if daily_bear and ema50_1d and price < ema50_1d:
        short_score += 8; short_reasons.append("Price below Daily EMA 50 & 200 (with trend)")

    # 6. S/R proximity (max 10)
    if supports:
        near_sup = min(abs(price - s) / price for s in supports)
        if near_sup < 0.008:
            long_score += 10; long_reasons.append("Price sitting at key support")
        elif near_sup < 0.02:
            long_score += 5
    if resistances:
        near_res = min(abs(price - r) / price for r in resistances)
        if near_res < 0.008:
            short_score += 10; short_reasons.append("Price at key resistance")
        elif near_res < 0.02:
            short_score += 5

    # 7. Volume spike (max 8)
    if vol_spike > 2.5 and tv_rating > 0:
        long_score += 8; long_reasons.append("Volume surge %.1fx avg (bullish)" % vol_spike)
    elif vol_spike > 2.5 and tv_rating < 0:
        short_score += 8; short_reasons.append("Volume surge %.1fx avg (bearish)" % vol_spike)

    # 8. Macro / Fear & Greed (max 8)
    if fear_greed < 25:
        long_score += 8; long_reasons.append("Extreme Fear (FGI %d) = buy zone" % fear_greed)
    elif fear_greed < 40:
        long_score += 4
    if fear_greed > 80:
        short_score += 8; short_reasons.append("Extreme Greed (FGI %d) = sell zone" % fear_greed)
    elif fear_greed > 65:
        short_score += 4

    # 9. Funding rate score (max 8)
    if tv_rating > 0:
        if -0.02 <= funding <= 0.01:
            long_score += 8; long_reasons.append("Funding neutral %.3f%% (uncrowded long)" % funding)
        elif funding < -0.02:
            long_score += 5; long_reasons.append("Negative funding %.3f%% (shorts pay longs)" % funding)
    if tv_rating < 0:
        if -0.01 <= funding <= 0.02:
            short_score += 8; short_reasons.append("Funding neutral %.3f%% (uncrowded short)" % funding)
        elif funding > 0.02:
            short_score += 5; short_reasons.append("Positive funding %.3f%% (longs pay shorts)" % funding)

    # 10. Open Interest confirmation (max 10)
    if oi_chg > 5 and tv_rating > 0:
        long_score += 10; long_reasons.append("OI rising +%.1f%% confirms long momentum" % oi_chg)
    elif oi_chg > 2 and tv_rating > 0:
        long_score += 5
    elif oi_chg < -5 and tv_rating > 0:
        long_score -= 5
    if oi_chg > 5 and tv_rating < 0:
        short_score += 10; short_reasons.append("OI rising +%.1f%% confirms short momentum" % oi_chg)
    elif oi_chg > 2 and tv_rating < 0:
        short_score += 5
    elif oi_chg < -5 and tv_rating < 0:
        short_score -= 5

    # 11. Bollinger Band squeeze breakout (max 12)
    if bb_expanding:
        long_score  += 12; long_reasons.append("BB squeeze breakout (%.2f%% width)" % bb_width_pct)
        short_score += 12; short_reasons.append("BB squeeze breakout (%.2f%% width)" % bb_width_pct)

    # 12. Liquidity sweep / Smart Money entry (max 18)
    if bull_sweep and tv_rating > 0:
        long_score += 18; long_reasons.append("Liquidity sweep: buy-side swept, price recovered (SMC entry)")
    if bear_sweep and tv_rating < 0:
        short_score += 18; short_reasons.append("Liquidity sweep: sell-side swept, price rejected (SMC entry)")

    # 13. ADX trend strength bonus (max 10)
    if adx4h >= 35:
        long_score  += 10; long_reasons.append("ADX %.1f — very strong trend" % adx4h)
        short_score += 10; short_reasons.append("ADX %.1f — very strong trend" % adx4h)
    elif adx4h >= 25:
        long_score  += 5;  long_reasons.append("ADX %.1f — trending market" % adx4h)
        short_score += 5;  short_reasons.append("ADX %.1f — trending market" % adx4h)

    # 14. BTC correlation (max 5)
    if btc_chg > 3:
        long_score += 5; long_reasons.append("BTC +%.1f%% macro lift" % btc_chg)
    elif btc_chg < -3:
        short_score += 5; short_reasons.append("BTC %.1f%% macro drag" % btc_chg)

    # 15. Top-trader position ratio (max 12 pts)
    if top_trader_ratio >= 1.5 and tv_rating > 0:
        long_score += 12; long_reasons.append(
            "Smart money heavily LONG (top-trader ratio %.2f)" % top_trader_ratio)
    elif top_trader_ratio >= 1.2 and tv_rating > 0:
        long_score += 6; long_reasons.append(
            "Smart money leaning LONG (ratio %.2f)" % top_trader_ratio)
    elif top_trader_ratio >= 1.1 and tv_rating > 0:
        long_score += 3

    if top_trader_ratio <= 0.7 and tv_rating < 0:
        short_score += 12; short_reasons.append(
            "Smart money heavily SHORT (top-trader ratio %.2f)" % top_trader_ratio)
    elif top_trader_ratio <= 0.85 and tv_rating < 0:
        short_score += 6; short_reasons.append(
            "Smart money leaning SHORT (ratio %.2f)" % top_trader_ratio)
    elif top_trader_ratio <= 0.92 and tv_rating < 0:
        short_score += 3

    # 16. Taker buy/sell volume ratio (max 8 pts)
    if taker_ratio >= 1.3 and tv_rating > 0:
        long_score += 8; long_reasons.append(
            "Aggressive buyers dominate (taker ratio %.2f)" % taker_ratio)
    elif taker_ratio >= 1.1 and tv_rating > 0:
        long_score += 4; long_reasons.append(
            "Slight buyer taker dominance (%.2f)" % taker_ratio)

    if taker_ratio <= 0.77 and tv_rating < 0:
        short_score += 8; short_reasons.append(
            "Aggressive sellers dominate (taker ratio %.2f)" % taker_ratio)
    elif taker_ratio <= 0.91 and tv_rating < 0:
        short_score += 4; short_reasons.append(
            "Slight seller taker dominance (%.2f)" % taker_ratio)

    # 17. Order book imbalance (max 5 pts)
    if ob_imbalance >= 1.5 and tv_rating > 0:
        long_score += 5; long_reasons.append(
            "Order book heavily bid-side (%.2f bid/ask)" % ob_imbalance)
    elif ob_imbalance >= 1.2 and tv_rating > 0:
        long_score += 3

    if ob_imbalance <= 0.67 and tv_rating < 0:
        short_score += 5; short_reasons.append(
            "Order book heavily ask-side (%.2f bid/ask)" % ob_imbalance)
    elif ob_imbalance <= 0.83 and tv_rating < 0:
        short_score += 3

    # ── Normalise to 100 ────────────────────────────────────────────────────────
    max_pts = 228
    long_pct  = min(int(long_score  / max_pts * 100), 100)
    short_pct = min(int(short_score / max_pts * 100), 100)

    if long_pct >= MIN_SCORE and long_pct > short_pct + 8:
        direction  = "LONG"
        final      = long_pct
        reasons    = long_reasons[:8]
    elif short_pct >= MIN_SCORE and short_pct > long_pct + 8:
        direction  = "SHORT"
        final      = short_pct
        reasons    = short_reasons[:8]
    else:
        return None

    # ── ATR-based entry / SL / TP ──────────────────────────────────────────────
    atr_val = (atr1h + atr4h) / 2

    if direction == "LONG":
        if supports and abs(price - supports[0]) / price <= 0.015:
            entry = supports[0] * 1.001
        else:
            entry = price

        sl  = entry - atr_val * 1.8
        if supports:
            structural_sl = supports[0] * 0.997
            sl = max(sl, structural_sl) if structural_sl > sl else sl
            if sl >= entry: sl = entry - atr_val * 1.8

        tp1 = entry + atr_val * 1.5
        tp2 = entry + atr_val * 3.0
        tp3 = entry + atr_val * 5.0
        if resistances:
            for res in resistances:
                if tp1 < res <= tp2 * 1.05:
                    tp2 = res * 0.998
                    break
    else:
        if resistances and abs(price - resistances[0]) / price <= 0.015:
            entry = resistances[0] * 0.999
        else:
            entry = price

        sl  = entry + atr_val * 1.8
        if resistances:
            structural_sl = resistances[0] * 1.003
            sl = min(sl, structural_sl) if structural_sl < sl else sl
            if sl <= entry: sl = entry + atr_val * 1.8

        tp1 = entry - atr_val * 1.5
        tp2 = entry - atr_val * 3.0
        tp3 = entry - atr_val * 5.0
        if supports:
            for sup in supports:
                if tp1 > sup >= tp2 * 0.95:
                    tp2 = sup * 1.002
                    break

    risk   = abs(entry - sl)
    reward = abs(tp2 - entry)
    rr     = reward / risk if risk > 0 else 0

    if rr < MIN_RR:
        return None

    if final >= 88 and rr >= 3.0:  tier = "S-TIER (PREMIUM)"
    elif final >= 80 and rr >= 2.5: tier = "A-TIER (HIGH CONF)"
    else:                            tier = "B-TIER (STANDARD)"

    lev = calculate_leverage_and_sizing(final, atr_val, price, rr)

    return {
        "symbol":           tv["symbol"],
        "direction":        direction,
        "score":            final,
        "long_score":       long_pct,
        "short_score":      short_pct,
        "tier":             tier,
        "leverage":         lev["lev_label"],
        "leverage_max":     lev["leverage"],
        "alloc_pct":        lev["alloc_pct"],
        "atr_pct":          lev["atr_pct"],
        "sl_pct":           lev["sl_pct"],
        "price":            price,
        "entry":            entry,
        "sl":               sl,
        "tp1":              tp1,
        "tp2":              tp2,
        "tp3":              tp3,
        "rr":               rr,
        "atr":              atr_val,
        "rsi1h":            rsi1h,
        "rsi4h":            rsi4h,
        "macd_1h":          mh1h,
        "ema21":            ema21_1h,
        "ema50":            ema50_1h,
        "vol_spike":        vol_spike,
        "tv_rating":        tv_rating,
        "tv_rating_lbl":    tv_rating_label(tv_rating),
        "tv_ma":            tv_ma,
        "tv_osc":           tv_osc,
        "trend_1h":         trend_1h,
        "trend_4h":         trend_4h,
        "trend_1d":         trend_1d,
        "rsi1d":            rsi1d,
        "adx4h":            adx4h,
        "supports":         supports,
        "resistances":      resistances,
        "fear_greed":       fear_greed,
        "btc_chg":          btc_chg,
        "change_24h":       tv["change"],
        "volume_24h":       tv["volume"],
        "funding":          funding,
        "oi_chg":           oi_chg,
        "bb_expanding":     bb_expanding,
        "bb_width":         bb_width_pct,
        "bull_sweep":       bull_sweep,
        "bear_sweep":       bear_sweep,
        "top_trader_ratio": top_trader_ratio,
        "taker_ratio":      taker_ratio,
        "ob_imbalance":     ob_imbalance,
        "reasons":          reasons,
    }

# ════════════════════════════════════════════════════════════════════════════════
# TV-ONLY SCORING (forex / stocks — no exchange klines needed)
# ════════════════════════════════════════════════════════════════════════════════

def score_setup_tv_only(tv, market):
    """
    Score a forex/stock setup using only TradingView pre-computed indicators.
    No exchange klines required — all data comes from the TV screener dict.
    Returns a result dict or None.
    """
    tv_rating = tv["tv_rating"]
    tv_ma     = tv["tv_ma"]
    tv_osc    = tv["tv_osc"]
    rsi_val   = tv["rsi"]
    rsi_prev  = tv["rsi_prev"]
    macd_val  = tv["macd"]
    macd_sig  = tv["macd_sig"]
    mom       = tv["momentum"]
    ema20     = tv["ema20"]
    ema50     = tv["ema50"]
    ema200    = tv["ema200"]
    atr_val   = tv["atr"]
    stoch_k   = tv["stoch_k"]
    stoch_d   = tv["stoch_d"]
    adx_val   = tv["adx"]
    cci_val   = tv["cci"]
    wr_val    = tv["williams_r"]
    price     = tv["close"]

    if price == 0 or atr_val == 0:
        return None

    # ADX gate: skip choppy markets
    if adx_val < 20:
        return None

    fear_greed = market.get("fear_greed", 50)
    long_score  = 0
    short_score = 0
    long_reasons  = []
    short_reasons = []

    # 1. TV Overall rating (max 35)
    if tv_rating >= 0.5:
        long_score += 35; long_reasons.append("TV STRONG BUY (%.2f)" % tv_rating)
    elif tv_rating >= 0.2:
        long_score += 20; long_reasons.append("TV BUY (%.2f)" % tv_rating)
    elif tv_rating >= 0.1:
        long_score += 10
    if tv_rating <= -0.5:
        short_score += 35; short_reasons.append("TV STRONG SELL (%.2f)" % tv_rating)
    elif tv_rating <= -0.2:
        short_score += 20; short_reasons.append("TV SELL (%.2f)" % tv_rating)
    elif tv_rating <= -0.1:
        short_score += 10

    # 2. TV MA sub-score (max 10)
    if tv_ma >= 0.3:
        long_score += 10; long_reasons.append("MA bullish (%.2f)" % tv_ma)
    elif tv_ma <= -0.3:
        short_score += 10; short_reasons.append("MA bearish (%.2f)" % tv_ma)

    # 3. TV Oscillator sub-score (max 10)
    if tv_osc >= 0.3:
        long_score += 10; long_reasons.append("Oscillators bullish (%.2f)" % tv_osc)
    elif tv_osc <= -0.3:
        short_score += 10; short_reasons.append("Oscillators bearish (%.2f)" % tv_osc)

    # 4. RSI (max 15)
    if rsi_val < 30:
        long_score += 12; long_reasons.append("RSI oversold (%.1f)" % rsi_val)
    elif rsi_val < 40:
        long_score += 6;  long_reasons.append("RSI low (%.1f)" % rsi_val)
    if rsi_val > 70:
        short_score += 12; short_reasons.append("RSI overbought (%.1f)" % rsi_val)
    elif rsi_val > 60:
        short_score += 6;  short_reasons.append("RSI high (%.1f)" % rsi_val)
    if rsi_val > rsi_prev and rsi_val < 50 and tv_rating > 0:
        long_score += 3
    if rsi_val < rsi_prev and rsi_val > 50 and tv_rating < 0:
        short_score += 3

    # 5. MACD (max 12)
    macd_hist_val = macd_val - macd_sig
    if macd_hist_val > 0:
        long_score += 12; long_reasons.append("MACD bullish")
    elif macd_hist_val < 0:
        short_score += 12; short_reasons.append("MACD bearish")

    # 6. EMA alignment (max 15)
    if ema20 and ema50 and ema200 and price > 0:
        if price > ema20 > ema50 > ema200:
            long_score += 15; long_reasons.append("EMA 20>50>200 bullish stack")
        elif price > ema20 > ema50:
            long_score += 8;  long_reasons.append("EMA 20 > 50 bullish")
        if price < ema20 < ema50 < ema200:
            short_score += 15; short_reasons.append("EMA 20<50<200 bearish stack")
        elif price < ema20 < ema50:
            short_score += 8;  short_reasons.append("EMA 20 < 50 bearish")

    # 7. ADX trend strength (max 10)
    if adx_val >= 35:
        long_score  += 10; long_reasons.append("ADX %.1f — very strong trend" % adx_val)
        short_score += 10; short_reasons.append("ADX %.1f — very strong trend" % adx_val)
    elif adx_val >= 25:
        long_score  += 5;  long_reasons.append("ADX %.1f — trending" % adx_val)
        short_score += 5;  short_reasons.append("ADX %.1f — trending" % adx_val)

    # 8. Stochastic (max 8)
    if stoch_k < 20 and stoch_d < 20:
        long_score += 8; long_reasons.append("Stoch oversold K=%.1f D=%.1f" % (stoch_k, stoch_d))
    elif stoch_k > 80 and stoch_d > 80:
        short_score += 8; short_reasons.append("Stoch overbought K=%.1f D=%.1f" % (stoch_k, stoch_d))

    # 9. Williams %R (max 5)
    if wr_val < -80:
        long_score += 5; long_reasons.append("Williams %%R oversold (%.1f)" % wr_val)
    elif wr_val > -20:
        short_score += 5; short_reasons.append("Williams %%R overbought (%.1f)" % wr_val)

    # 10. Momentum (max 5)
    if mom > 0 and tv_rating > 0:
        long_score += 5; long_reasons.append("Positive momentum")
    elif mom < 0 and tv_rating < 0:
        short_score += 5; short_reasons.append("Negative momentum")

    # 11. CCI (max 5)
    if cci_val < -100:
        long_score += 5; long_reasons.append("CCI oversold (%.0f)" % cci_val)
    elif cci_val > 100:
        short_score += 5; short_reasons.append("CCI overbought (%.0f)" % cci_val)

    # ── Normalise to 100 (max raw = 130) ────────────────────────────────────
    max_pts = 130
    long_pct  = min(int(long_score  / max_pts * 100), 100)
    short_pct = min(int(short_score / max_pts * 100), 100)

    if long_pct >= MIN_SCORE and long_pct > short_pct + 8:
        direction = "LONG"
        final     = long_pct
        reasons   = long_reasons[:6]
    elif short_pct >= MIN_SCORE and short_pct > long_pct + 8:
        direction = "SHORT"
        final     = short_pct
        reasons   = short_reasons[:6]
    else:
        return None

    # ATR-based levels
    if direction == "LONG":
        entry = price
        sl    = entry - atr_val * 1.5
        tp1   = entry + atr_val * 1.2
        tp2   = entry + atr_val * 2.5
        tp3   = entry + atr_val * 4.0
    else:
        entry = price
        sl    = entry + atr_val * 1.5
        tp1   = entry - atr_val * 1.2
        tp2   = entry - atr_val * 2.5
        tp3   = entry - atr_val * 4.0

    risk   = abs(entry - sl)
    reward = abs(tp2 - entry)
    rr     = reward / risk if risk > 0 else 0

    if rr < MIN_RR:
        return None

    if final >= 88:   tier = "S-TIER (PREMIUM)"
    elif final >= 80: tier = "A-TIER (HIGH CONF)"
    else:             tier = "B-TIER (STANDARD)"

    return {
        "symbol":        tv["symbol"],
        "asset_class":   tv.get("asset_class", "forex"),
        "direction":     direction,
        "score":         final,
        "tier":          tier,
        "price":         price,
        "entry":         entry,
        "sl":            sl,
        "tp1":           tp1,
        "tp2":           tp2,
        "tp3":           tp3,
        "rr":            rr,
        "atr":           atr_val,
        "tv_rating":     tv_rating,
        "tv_rating_lbl": tv_rating_label(tv_rating),
        "tv_ma":         tv_ma,
        "tv_osc":        tv_osc,
        "rsi":           rsi_val,
        "adx":           adx_val,
        "stoch_k":       stoch_k,
        "stoch_d":       stoch_d,
        "ema20":         ema20,
        "ema50":         ema50,
        "ema200":        ema200,
        "macd_hist":     macd_hist_val,
        "change_24h":    tv["change"],
        "fear_greed":    fear_greed,
        "reasons":       reasons,
    }


# ════════════════════════════════════════════════════════════════════════════════
# MESSAGE BUILDER
# ════════════════════════════════════════════════════════════════════════════════

def fp(n):
    if n >= 1000: return "%.2f" % n
    if n >= 1:    return "%.4f" % n
    if n >= 0.01: return "%.6f" % n
    return "%.8f" % n

def fv(n):
    if n >= 1e9: return "$%.2fB" % (n / 1e9)
    if n >= 1e6: return "$%.1fM" % (n / 1e6)
    return "$%.0fK" % (n / 1e3)

def build_message(s):
    tier_icon = {
        "S-TIER (PREMIUM)":  "[S]",
        "A-TIER (HIGH CONF)":"[A]",
        "B-TIER (STANDARD)": "[B]",
    }.get(s["tier"], "[?]")

    score_bar = "#" * round(s["score"] / 10) + "-" * (10 - round(s["score"] / 10))
    dir_label = "LONG" if s["direction"] == "LONG" else "SHORT"
    dir_arrow = "LONG" if s["direction"] == "LONG" else "SHORT"

    fg_label = (
        "Extreme Fear" if s["fear_greed"] < 25 else
        "Fear"         if s["fear_greed"] < 45 else
        "Neutral"      if s["fear_greed"] < 55 else
        "Greed"        if s["fear_greed"] < 75 else
        "Extreme Greed"
    )

    sl_pct  = abs(s["entry"] - s["sl"])  / s["entry"] * 100
    tp1_pct = abs(s["tp1"]  - s["entry"]) / s["entry"] * 100
    tp2_pct = abs(s["tp2"]  - s["entry"]) / s["entry"] * 100
    tp3_pct = abs(s["tp3"]  - s["entry"]) / s["entry"] * 100

    sup_str = ", ".join(["$%s" % fp(z) for z in s["supports"][:2]]) or "None detected"
    res_str = ", ".join(["$%s" % fp(z) for z in s["resistances"][:2]]) or "None detected"

    reasons_text = "\n".join(["  [+] " + r for r in s["reasons"]])

    ttr = s["top_trader_ratio"]
    tkr = s["taker_ratio"]
    obi = s["ob_imbalance"]
    ttr_label = "LONG" if ttr >= 1.2 else "SHORT" if ttr <= 0.85 else "NEUTRAL"
    tkr_label = "BUYERS" if tkr >= 1.1 else "SELLERS" if tkr <= 0.91 else "BALANCED"
    obi_label = "BID HEAVY" if obi >= 1.2 else "ASK HEAVY" if obi <= 0.83 else "BALANCED"

    return (
        "%s %s SIGNAL | TradingView Scan\n"
        "Pair:  %s/USDT  |  Score: %d/100\n"
        "Tier:  %s\n"
        "[%s]\n"
        "\n"
        "=== TRADINGVIEW RATING ===\n"
        "Overall:     %s  (%.2f)\n"
        "MA Rating:   %.2f  |  Oscillators: %.2f\n"
        "\n"
        "=== TRADE SETUP ===\n"
        "Direction:  %s\n"
        "Entry:      $%s\n"
        "Stop Loss:  $%s  (-%.2f%%)\n"
        "TP1:        $%s  (+%.2f%%)  [take 40%%]\n"
        "TP2:        $%s  (+%.2f%%)  [take 35%%]\n"
        "TP3:        $%s  (+%.2f%%)  [let 25%% run]\n"
        "R/R Ratio:  %.2fx\n"
        "\n"
        "=== LEVERAGE & POSITION SIZING ===\n"
        "Suggested Leverage:  %s\n"
        "Max Safe Leverage:   %dx  (ATR %.2f%% volatility)\n"
        "Account Allocation:  %.1f%% of your account\n"
        "SL Distance:         %.2f%% from entry\n"
        "Risk Per Trade:      2%% of account (fixed rule)\n"
        "Example ($1000):     $%.0f in position at %dx = $%.0f notional\n"
        "\n"
        "=== ORDER FLOW (Live Smart Money) ===\n"
        "Top Traders (smart $): %.2f  [%s]\n"
        "Taker Volume Ratio:    %.2f  [%s]\n"
        "Order Book Imbalance:  %.2f  [%s]\n"
        "\n"
        "=== TECHNICAL CONFIRMATION ===\n"
        "RSI  1h: %.1f  |  4h: %.1f  |  1d: %.1f\n"
        "MACD 1h: %s\n"
        "ADX  4h: %.1f  (%s)\n"
        "Trend 1d: %s  |  4h: %s  |  1h: %s\n"
        "EMA 21: $%s  |  EMA 50: $%s\n"
        "Volume spike: %.1fx avg\n"
        "Support zones:    %s\n"
        "Resistance zones: %s\n"
        "\n"
        "=== WHY THIS TRADE ===\n"
        "%s\n"
        "\n"
        "=== MARKET CONTEXT ===\n"
        "Fear/Greed: %d (%s)\n"
        "BTC 24h:    %+.1f%%\n"
        "Pair 24h:   %+.2f%%\n"
        "Volume:     %s\n"
        "Funding:    %.4f%%\n"
        "OI Change:  %+.1f%%\n"
        "%s"
        "%s"
        "\n"
        "=== RISK RULES ===\n"
        "- Allocate %.1f%% of account (2%% risk rule)\n"
        "- Set SL immediately on entry — no exceptions\n"
        "- Move SL to breakeven once TP1 is hit\n"
        "- Never chase if entry zone passes\n"
        "- Lower leverage if coin is new or illiquid\n"
        "\n"
        "=== EXCHANGE CONFIRMATION ===\n"
        "%s\n"
        "\n"
        "Time: %s UTC\n"
        "Source: TradingView + Bybit + Binance + OKX\n"
        "Not financial advice - DYOR!"
    ) % (
        tier_icon, dir_arrow,
        s["symbol"].replace("USDT", ""), s["score"],
        s["tier"],
        score_bar,
        s["tv_rating_lbl"], s["tv_rating"],
        s["tv_ma"], s["tv_osc"],
        dir_label,
        fp(s["entry"]),
        fp(s["sl"]),   sl_pct,
        fp(s["tp1"]),  tp1_pct,
        fp(s["tp2"]),  tp2_pct,
        fp(s["tp3"]),  tp3_pct,
        s["rr"],
        s["leverage"],
        s["leverage_max"], s["atr_pct"],
        s["alloc_pct"],
        s["sl_pct"],
        1000 * s["alloc_pct"] / 100, s["leverage_max"],
        1000 * s["alloc_pct"] / 100 * s["leverage_max"],
        ttr, ttr_label,
        tkr, tkr_label,
        obi, obi_label,
        s["rsi1h"], s["rsi4h"], s["rsi1d"],
        "Bullish" if s["macd_1h"] > 0 else "Bearish",
        s["adx4h"],
        "Strong Trend" if s["adx4h"] >= 35 else "Trending" if s["adx4h"] >= 25 else "Weak",
        s["trend_1d"], s["trend_4h"], s["trend_1h"],
        fp(s["ema21"]), fp(s["ema50"]),
        s["vol_spike"],
        sup_str, res_str,
        reasons_text,
        s["fear_greed"], fg_label,
        s["btc_chg"],
        s["change_24h"],
        fv(s["volume_24h"]),
        s["funding"],
        s["oi_chg"],
        "BB Squeeze:  BREAKING OUT\n" if s["bb_expanding"] else "",
        "SMC Sweep:   LIQUIDITY SWEPT - PREMIUM ENTRY\n" if (s["bull_sweep"] or s["bear_sweep"]) else "",
        s["alloc_pct"],
        "\n".join(
            "  [OK] %s" % ex if ex in s.get("exchanges", ["Bybit"]) else "  [--] %s" % ex
            for ex in ["Bybit", "Binance", "OKX"]
        ),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def build_message_forex(s):
    tier_icon = {
        "S-TIER (PREMIUM)":  "[S]",
        "A-TIER (HIGH CONF)":"[A]",
        "B-TIER (STANDARD)": "[B]",
    }.get(s["tier"], "[?]")

    score_bar = "#" * round(s["score"] / 10) + "-" * (10 - round(s["score"] / 10))
    dir_label    = "LONG" if s["direction"] == "LONG" else "SHORT"
    asset_class  = s.get("asset_class", "FOREX").upper()

    fg_label = (
        "Extreme Fear" if s["fear_greed"] < 25 else
        "Fear"         if s["fear_greed"] < 45 else
        "Neutral"      if s["fear_greed"] < 55 else
        "Greed"        if s["fear_greed"] < 75 else
        "Extreme Greed"
    )

    sl_pct  = abs(s["entry"] - s["sl"])  / s["entry"] * 100 if s["entry"] else 0
    tp1_pct = abs(s["tp1"]  - s["entry"]) / s["entry"] * 100 if s["entry"] else 0
    tp2_pct = abs(s["tp2"]  - s["entry"]) / s["entry"] * 100 if s["entry"] else 0
    tp3_pct = abs(s["tp3"]  - s["entry"]) / s["entry"] * 100 if s["entry"] else 0

    reasons_text = "\n".join(["  [+] " + r for r in s["reasons"]])

    return (
        "%s %s SIGNAL | %s\n"
        "Pair:  %s  |  Score: %d/100\n"
        "Tier:  %s\n"
        "[%s]\n"
        "\n"
        "=== TRADINGVIEW RATING ===\n"
        "Overall:     %s  (%.2f)\n"
        "MA Rating:   %.2f  |  Oscillators: %.2f\n"
        "\n"
        "=== TRADE SETUP ===\n"
        "Direction:  %s\n"
        "Entry:      %s\n"
        "Stop Loss:  %s  (-%.2f%%)\n"
        "TP1:        %s  (+%.2f%%)  [take 40%%]\n"
        "TP2:        %s  (+%.2f%%)  [take 35%%]\n"
        "TP3:        %s  (+%.2f%%)  [let 25%% run]\n"
        "R/R Ratio:  %.2fx\n"
        "\n"
        "=== TECHNICAL CONFIRMATION ===\n"
        "RSI:    %.1f\n"
        "ADX:    %.1f  (%s)\n"
        "Stoch:  K=%.1f  D=%.1f\n"
        "EMA 20: %s  |  EMA 50: %s\n"
        "EMA 200: %s\n"
        "MACD:   %s\n"
        "\n"
        "=== WHY THIS TRADE ===\n"
        "%s\n"
        "\n"
        "=== MARKET CONTEXT ===\n"
        "Fear/Greed: %d (%s)\n"
        "Pair 24h:   %+.2f%%\n"
        "\n"
        "=== RISK RULES ===\n"
        "- Set SL immediately on entry — no exceptions\n"
        "- Move SL to breakeven once TP1 is hit\n"
        "- Risk 1-2%% of account per trade max\n"
        "- Never chase if entry zone passes\n"
        "\n"
        "Time: %s UTC\n"
        "Source: TradingView %s Screener\n"
        "Not financial advice - DYOR!"
    ) % (
        tier_icon, dir_label, asset_class,
        s["symbol"], s["score"],
        s["tier"],
        score_bar,
        s["tv_rating_lbl"], s["tv_rating"],
        s["tv_ma"], s["tv_osc"],
        dir_label,
        fp(s["entry"]),
        fp(s["sl"]),   sl_pct,
        fp(s["tp1"]),  tp1_pct,
        fp(s["tp2"]),  tp2_pct,
        fp(s["tp3"]),  tp3_pct,
        s["rr"],
        s["rsi"],
        s["adx"],
        "Strong Trend" if s["adx"] >= 35 else "Trending" if s["adx"] >= 25 else "Weak",
        s["stoch_k"], s["stoch_d"],
        fp(s["ema20"]), fp(s["ema50"]),
        fp(s["ema200"]),
        "Bullish" if s["macd_hist"] > 0 else "Bearish",
        reasons_text,
        s["fear_greed"], fg_label,
        s["change_24h"],
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        asset_class,
    )


# ════════════════════════════════════════════════════════════════════════════════
# MAIN SCAN LOOP
# ════════════════════════════════════════════════════════════════════════════════

async def main():
    log.info("TradingView Trade Setup Scanner starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "TradingView Trade Setup Scanner v5 Online!\n\n"
            "Asset Classes: Crypto + Forex + US Stocks\n"
            "Source: TradingView + Bybit + Binance + OKX\n"
            "Target Win Rate: 78-83%%\n\n"
            "CRYPTO (Bybit + Binance + OKX):\n"
            "  - All 3 exchanges scanned + deduplicated\n"
            "  - 17 scoring sections + 6 hard gates\n"
            "  - Real top-trader + taker ratios\n"
            "  - Cross-exchange RSI/EMA confirmation\n"
            "  - ATR Entry / SL / TP + leverage calc\n\n"
            "FOREX (TradingView):\n"
            "  - Major + minor FX pairs\n"
            "  - 11 scoring sections (RSI, MACD, EMA,\n"
            "    Stoch, ADX, CCI, W%%R, momentum)\n"
            "  - ATR-based Entry / SL / TP\n\n"
            "US STOCKS (NYSE + NASDAQ):\n"
            "  - High-volume stocks >$5 and >5M vol\n"
            "  - Same 11-section TV scoring as forex\n"
            "  - Only scans during market hours\n"
            "  - (09:30-16:00 ET = 13:30-20:00 UTC)\n\n"
            "6 Hard Gates (crypto — auto-reject on fail):\n"
            "  - Daily EMA 200 (no counter-trend)\n"
            "  - ADX > 20 (trending markets only)\n"
            "  - Candle structure (2/3 closes align)\n"
            "  - Funding rate (< +-0.05%% gate)\n"
            "  - London/NY session only (08-22 UTC)\n"
            "  - BTC spike pause (>2%% on 15m)\n\n"
            "Min Score: %d/100  |  Min R/R: %.1fx\n"
            "Scan every: %ds\n\n"
            "Not financial advice - DYOR!"
        ) % (MIN_SCORE, MIN_RR, SCAN_INTERVAL)
    )

    seen_signals = {}
    scan_count   = 0

    while True:
        scan_count += 1
        log.info("Scan #%d starting..." % scan_count)

        # ── Session gate ─────────────────────────────────────────────────────
        if not is_active_session():
            hour = datetime.now(timezone.utc).hour
            log.info("Outside active session (UTC %02d:xx) — skipping scan." % hour)
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        market = {
            "fear_greed": fetch_fear_greed(),
            "btc_chg":    fetch_btc_change(),
        }
        log.info("Market: FGI=%d  BTC=%+.2f%%" % (market["fear_greed"], market["btc_chg"]))

        # ── BTC spike gate ────────────────────────────────────────────────────
        if btc_is_spiking():
            log.info("BTC spiking on 15m — pausing signals this cycle.")
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        try:
            candidates = tv_scan_multi_exchange(filter_side="both", limit=50)
            log.info("TradingView returned %d candidates across 3 exchanges" % len(candidates))

            candidates.sort(key=lambda x: abs(x["tv_rating"]), reverse=True)

            signals_sent = 0

            for tv in candidates:
                if signals_sent >= MAX_SIGNALS:
                    break

                symbol = tv["symbol"]
                last   = seen_signals.get(symbol, 0)
                if time.time() - last < SIGNAL_COOLDOWN:
                    continue

                try:
                    # ── Primary data (Bybit) ─────────────────────────────────
                    k1h      = fetch_klines(symbol, "1h",  200); time.sleep(0.15)
                    k4h      = fetch_klines(symbol, "4h",  150); time.sleep(0.15)
                    k1d      = fetch_klines(symbol, "1d",   60); time.sleep(0.15)
                    funding  = fetch_funding_rate(symbol);       time.sleep(0.10)
                    oi_chg   = fetch_oi_change(symbol);          time.sleep(0.10)
                    ob_imbal = fetch_order_book_imbalance(symbol); time.sleep(0.10)

                    if not k1h or not k4h:
                        continue

                    result = score_setup(
                        tv,
                        parse_klines(k1h),
                        parse_klines(k4h),
                        parse_klines(k1d) if k1d else ([], [], [], [], []),
                        market,
                        funding=funding,
                        oi_chg=oi_chg,
                        top_trader_ratio=fetch_top_trader_ratio(symbol),
                        taker_ratio=fetch_taker_ratio(symbol),
                        ob_imbalance=ob_imbal,
                    )

                    if result:
                        direction = result["direction"]

                        # ── Cross-exchange confirmation ───────────────────────
                        k1h_bnb     = fetch_klines_bnb(symbol, "1h", 50); time.sleep(0.10)
                        k1h_okx     = fetch_klines_okx(symbol, "1h", 50); time.sleep(0.10)
                        funding_bnb = fetch_funding_bnb(symbol);           time.sleep(0.05)
                        funding_okx = fetch_funding_okx(symbol);           time.sleep(0.05)
                        ob_bnb      = fetch_ob_bnb(symbol);                time.sleep(0.05)

                        # Average funding rate across all 3 exchanges
                        valid_fundings = [f for f in [funding, funding_bnb, funding_okx] if f != 0.0]
                        avg_funding = sum(valid_fundings) / len(valid_fundings) if valid_fundings else funding

                        # Average order book imbalance (Bybit + Binance)
                        avg_ob = (ob_imbal + ob_bnb) / 2 if ob_bnb != 1.0 else ob_imbal

                        # Count exchange confirmations
                        exchanges = ["Bybit"]
                        bnb_ok = exchange_confirms(k1h_bnb, direction)
                        okx_ok = exchange_confirms(k1h_okx, direction)
                        if bnb_ok is True:  exchanges.append("Binance")
                        if okx_ok is True:  exchanges.append("OKX")

                        # Score boost: +15 for all 3, +8 for 2 of 3
                        boost = {3: 15, 2: 8}.get(len(exchanges), 0)
                        result["score"]        = min(100, result["score"] + boost)
                        result["exchanges"]    = exchanges
                        result["funding"]      = avg_funding
                        result["ob_imbalance"] = avg_ob

                        # Re-tier after boost
                        sc, rr = result["score"], result["rr"]
                        if sc >= 88 and rr >= 3.0:   result["tier"] = "S-TIER (PREMIUM)"
                        elif sc >= 80 and rr >= 2.5: result["tier"] = "A-TIER (HIGH CONF)"
                        else:                         result["tier"] = "B-TIER (STANDARD)"

                        if result["score"] < MIN_SCORE:
                            continue

                        msg = build_message(result)
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            disable_web_page_preview=True,
                        )
                        seen_signals[symbol] = time.time()
                        signals_sent += 1
                        log.info("Signal: %s %s score=%d tier=%s rr=%.2f exchanges=%s" % (
                            symbol, direction, result["score"],
                            result["tier"], result["rr"],
                            "+".join(result["exchanges"])
                        ))
                        await asyncio.sleep(2)

                except Exception as e:
                    log.error("Error analysing %s: %s" % (symbol, e))

            if signals_sent == 0:
                log.info("No qualifying setups this scan.")

            log.info("Scan #%d done. Sent %d signals." % (scan_count, signals_sent))

        except Exception as e:
            log.error("Scan error: %s" % e)

        # ── Forex scan ────────────────────────────────────────────────────────
        try:
            fx_candidates = tv_scan_forex(filter_side="both", limit=30)
            log.info("TradingView forex returned %d candidates" % len(fx_candidates))

            fx_candidates.sort(key=lambda x: abs(x["tv_rating"]), reverse=True)
            fx_sent = 0

            for tv in fx_candidates:
                if fx_sent >= 2:
                    break

                sym  = tv["symbol"]
                last = seen_signals.get("FX_" + sym, 0)
                if time.time() - last < SIGNAL_COOLDOWN:
                    continue

                result = score_setup_tv_only(tv, market)
                if result:
                    msg = build_message_forex(result)
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        disable_web_page_preview=True,
                    )
                    seen_signals["FX_" + sym] = time.time()
                    fx_sent += 1
                    log.info("Forex signal: %s %s score=%d" % (
                        sym, result["direction"], result["score"]))
                    await asyncio.sleep(2)

            if fx_sent == 0:
                log.info("No qualifying forex setups this scan.")

        except Exception as e:
            log.error("Forex scan error: %s" % e)

        # ── US Stocks scan (market hours only: 13:30-20:00 UTC) ───────────────
        if is_us_market_open():
            try:
                st_candidates = tv_scan_stocks(filter_side="both", limit=30)
                log.info("TradingView stocks returned %d candidates" % len(st_candidates))

                st_candidates.sort(key=lambda x: abs(x["tv_rating"]), reverse=True)
                st_sent = 0

                for tv in st_candidates:
                    if st_sent >= 2:
                        break

                    sym  = tv["symbol"]
                    last = seen_signals.get("ST_" + sym, 0)
                    if time.time() - last < SIGNAL_COOLDOWN:
                        continue

                    result = score_setup_tv_only(tv, market)
                    if result:
                        msg = build_message_forex(result)
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            disable_web_page_preview=True,
                        )
                        seen_signals["ST_" + sym] = time.time()
                        st_sent += 1
                        log.info("Stock signal: %s %s score=%d" % (
                            sym, result["direction"], result["score"]))
                        await asyncio.sleep(2)

                if st_sent == 0:
                    log.info("No qualifying stock setups this scan.")

            except Exception as e:
                log.error("Stocks scan error: %s" % e)
        else:
            log.info("US market closed — skipping stocks scan.")

        log.info("Next scan in %ds..." % SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
