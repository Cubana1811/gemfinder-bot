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

BINANCE_BASE    = "https://fapi.binance.com"
FEAR_GREED_URL  = "https://api.alternative.me/fng/?limit=1"
TV_SCAN_URL     = "https://scanner.tradingview.com/crypto/scan"

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

def tv_scan(filter_side="both", limit=50):
    """
    Query TradingView's public screener for BINANCE crypto futures pairs.
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
        {"left": "exchange", "operation": "equal", "right": "BINANCE"},
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

            # Normalise symbol to plain Binance futures format
            clean = sym.replace("BINANCE:", "").replace(".P", "").replace(".F", "")
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
    data = safe_get("%s/fapi/v1/klines?symbol=%s&interval=%s&limit=%s" % (
        BINANCE_BASE, symbol, interval, limit))
    return data or []

def fetch_funding_rate(symbol):
    data = safe_get("%s/fapi/v1/fundingRate?symbol=%s&limit=3" % (BINANCE_BASE, symbol))
    if data:
        return float(data[-1].get("fundingRate", 0)) * 100
    return 0.0

def fetch_oi_change(symbol):
    data = safe_get("%s/futures/data/openInterestHist?symbol=%s&period=1h&limit=8" % (
        BINANCE_BASE, symbol))
    if data and len(data) >= 2:
        old = float(data[0].get("sumOpenInterest", 1))
        new = float(data[-1].get("sumOpenInterest", 1))
        return (new - old) / old * 100 if old else 0
    return 0.0

def fetch_fear_greed():
    data = safe_get(FEAR_GREED_URL)
    if data and data.get("data"):
        return int(data["data"][0].get("value", 50))
    return 50

def fetch_btc_change():
    data = safe_get("%s/fapi/v1/ticker/24hr?symbol=BTCUSDT" % BINANCE_BASE)
    if data:
        return float(data.get("priceChangePercent", 0))
    return 0.0

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

def score_setup(tv, k1h_data, k4h_data, k1d_data, market):
    """
    Score a symbol using TradingView ratings + Binance candle confirmation.
    Daily candles are used as the HTF trend filter — no counter-trend trades.
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

    # ── Binance indicators ────────────────────────────────────────────────────
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

    avg_vol   = sum(v1h[-20:]) / 20 if len(v1h) >= 20 else v1h[-1]
    vol_spike = v1h[-1] / avg_vol if avg_vol > 0 else 1

    trend_1h = market_structure(h1h, l1h)
    trend_4h = market_structure(h4h, l4h)
    trend_1d = market_structure(h1d, l1d) if h1d else "RANGING"

    # Use 4h S/R zones — better balance of recency and significance
    supports, resistances = find_sr_zones(h4h, l4h, c4h)

    # ── HTF trend gate: reject counter-trend trades ───────────────────────────
    # Daily EMA 200 is the definitive bull/bear dividing line
    daily_bull = price > ema200_1d if ema200_1d else None
    daily_bear = price < ema200_1d if ema200_1d else None
    if daily_bull is not None:
        if tv_rating > 0 and daily_bear:
            return None   # trying to LONG below daily EMA 200 — counter-trend
        if tv_rating < 0 and daily_bull:
            return None   # trying to SHORT above daily EMA 200 — counter-trend

    fear_greed = market.get("fear_greed", 50)
    btc_chg    = market.get("btc_chg", 0)

    long_score  = 0
    short_score = 0
    long_reasons  = []
    short_reasons = []

    # 1. TradingView rating (max 35 pts — the anchor signal)
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

    # 2. Binance RSI confirmation (max 20)
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

    # Daily EMA bonus (high-conviction with-trend trades only)
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

    # 9. BTC correlation (max 5)
    if btc_chg > 3:
        long_score += 5; long_reasons.append("BTC +%.1f%% macro lift" % btc_chg)
    elif btc_chg < -3:
        short_score += 5; short_reasons.append("BTC %.1f%% macro drag" % btc_chg)

    # ── Normalise to 100 ────────────────────────────────────────────────────────
    max_pts = 136
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
        # Ideal entry: current price OR nearest support zone (whichever is closer
        # and within 1.5% — avoids entering deep into an already-extended move)
        if supports and abs(price - supports[0]) / price <= 0.015:
            entry = supports[0] * 1.001   # just above support as limit entry
        else:
            entry = price

        sl  = entry - atr_val * 1.8
        # Anchor SL below nearest confirmed support (3-touch zone)
        if supports:
            structural_sl = supports[0] * 0.997
            sl = max(sl, structural_sl) if structural_sl > sl else sl
            if sl >= entry: sl = entry - atr_val * 1.8   # safety fallback

        tp1 = entry + atr_val * 1.5
        tp2 = entry + atr_val * 3.0
        tp3 = entry + atr_val * 5.0
        # Snap TP2/TP3 to resistance zones if they exist nearby
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

    if final >= 88:   leverage = "5-8x"
    elif final >= 80: leverage = "3-5x"
    else:              leverage = "2-3x"

    return {
        "symbol":       tv["symbol"],
        "direction":    direction,
        "score":        final,
        "long_score":   long_pct,
        "short_score":  short_pct,
        "tier":         tier,
        "leverage":     leverage,
        "price":        price,
        "entry":        entry,
        "sl":           sl,
        "tp1":          tp1,
        "tp2":          tp2,
        "tp3":          tp3,
        "rr":           rr,
        "atr":          atr_val,
        "rsi1h":        rsi1h,
        "rsi4h":        rsi4h,
        "macd_1h":      mh1h,
        "ema21":        ema21_1h,
        "ema50":        ema50_1h,
        "vol_spike":    vol_spike,
        "tv_rating":    tv_rating,
        "tv_rating_lbl": tv_rating_label(tv_rating),
        "tv_ma":        tv_ma,
        "tv_osc":       tv_osc,
        "trend_1h":     trend_1h,
        "trend_4h":     trend_4h,
        "trend_1d":     trend_1d,
        "rsi1d":        rsi1d,
        "supports":     supports,
        "resistances":  resistances,
        "fear_greed":   fear_greed,
        "btc_chg":      btc_chg,
        "change_24h":   tv["change"],
        "volume_24h":   tv["volume"],
        "reasons":      reasons,
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
        "Leverage:   %s  (use responsibly)\n"
        "\n"
        "=== TECHNICAL CONFIRMATION ===\n"
        "RSI  1h: %.1f  |  4h: %.1f  |  1d: %.1f\n"
        "MACD 1h: %s\n"
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
        "\n"
        "=== RISK RULES ===\n"
        "- Max 3-5%% of portfolio per trade\n"
        "- Set SL immediately on entry\n"
        "- Move SL to entry once TP1 is hit\n"
        "- Never chase after entry zone passes\n"
        "\n"
        "Time: %s UTC\n"
        "Source: TradingView Scanner + Binance\n"
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
        s["rr"], s["leverage"],
        s["rsi1h"], s["rsi4h"], s["rsi1d"],
        "Bullish" if s["macd_1h"] > 0 else "Bearish",
        s["trend_1d"], s["trend_4h"], s["trend_1h"],
        fp(s["ema21"]), fp(s["ema50"]),
        s["vol_spike"],
        sup_str, res_str,
        reasons_text,
        s["fear_greed"], fg_label,
        s["btc_chg"],
        s["change_24h"],
        fv(s["volume_24h"]),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
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
            "TradingView Trade Setup Scanner Online!\n\n"
            "Source: TradingView Screener + Binance Futures\n\n"
            "Method:\n"
            "  1. TV screener finds strongest BUY/SELL signals\n"
            "  2. Binance klines confirm with indicators\n"
            "  3. ATR-based Entry / SL / TP calculated\n\n"
            "Indicators Used:\n"
            "  - TradingView Overall + MA + Oscillator rating\n"
            "  - RSI (1h + 4h)\n"
            "  - MACD (1h + 4h)\n"
            "  - EMA 21 / 50 / 200 alignment\n"
            "  - Market Structure (HH/HL)\n"
            "  - Support & Resistance zones\n"
            "  - Volume spike detection\n"
            "  - Fear & Greed + BTC correlation\n\n"
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

        market = {
            "fear_greed": fetch_fear_greed(),
            "btc_chg":    fetch_btc_change(),
        }
        log.info("Market: FGI=%d  BTC=%+.2f%%" % (market["fear_greed"], market["btc_chg"]))

        try:
            # Pull strong candidates from TradingView (both sides)
            candidates = tv_scan(filter_side="both", limit=60)
            log.info("TradingView returned %d candidates" % len(candidates))

            # Sort by absolute rating strength so we analyse the most opinionated signals first
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
                    k1h = fetch_klines(symbol, "1h",  200); time.sleep(0.15)
                    k4h = fetch_klines(symbol, "4h",  150); time.sleep(0.15)
                    k1d = fetch_klines(symbol, "1d",   60); time.sleep(0.15)

                    if not k1h or not k4h:
                        continue

                    result = score_setup(
                        tv,
                        parse_klines(k1h),
                        parse_klines(k4h),
                        parse_klines(k1d) if k1d else ([], [], [], [], []),
                        market,
                    )

                    if result:
                        msg = build_message(result)
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            disable_web_page_preview=True,
                        )
                        seen_signals[symbol] = time.time()
                        signals_sent += 1
                        log.info("Signal: %s %s score=%d tier=%s rr=%.2f" % (
                            symbol, result["direction"], result["score"],
                            result["tier"], result["rr"]
                        ))
                        await asyncio.sleep(2)

                except Exception as e:
                    log.error("Error analysing %s: %s" % (symbol, e))

            if signals_sent == 0:
                log.info("No qualifying setups this scan.")

            log.info("Scan #%d done. Sent %d signals." % (scan_count, signals_sent))

        except Exception as e:
            log.error("Scan error: %s" % e)

        log.info("Next scan in %ds..." % SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
