import os
import time
import math
import logging
import requests
import asyncio
from telegram import Bot
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID          = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
SCAN_INTERVAL    = 300        # 5 minutes
MIN_SCORE        = 75         # minimum confluence score
MIN_RR           = 2.0        # minimum risk/reward ratio
SIGNAL_COOLDOWN  = 7200       # 2 hours between signals per pair
BINANCE_BASE     = "https://fapi.binance.com"
SPOT_BASE        = "https://api.binance.com"
FEAR_GREED_URL   = "https://api.alternative.me/fng/?limit=1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ════════════════════════════════════════════════════════════════════════════

def safe_get(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("Request error %s: %s" % (url[:50], e))
    return None

def fetch_top_pairs(min_vol=50_000_000):
    data = safe_get("%s/fapi/v1/ticker/24hr" % BINANCE_BASE)
    if not data: return []
    pairs = [t for t in data if t.get("symbol","").endswith("USDT")]
    pairs = [t for t in pairs if float(t.get("quoteVolume",0)) >= min_vol]
    pairs.sort(key=lambda x: float(x.get("quoteVolume",0)), reverse=True)
    return pairs[:40]

def fetch_klines(symbol, interval, limit=200):
    data = safe_get("%s/fapi/v1/klines?symbol=%s&interval=%s&limit=%s" % (
        BINANCE_BASE, symbol, interval, limit))
    return data or []

def fetch_funding_rate(symbol):
    data = safe_get("%s/fapi/v1/fundingRate?symbol=%s&limit=3" % (BINANCE_BASE, symbol))
    if data and len(data) > 0:
        return float(data[-1].get("fundingRate", 0)) * 100
    return 0.0

def fetch_open_interest(symbol):
    data = safe_get("%s/fapi/v1/openInterest?symbol=%s" % (BINANCE_BASE, symbol))
    if data:
        return float(data.get("openInterest", 0))
    return 0.0

def fetch_oi_history(symbol):
    data = safe_get("%s/futures/data/openInterestHist?symbol=%s&period=1h&limit=24" % (
        BINANCE_BASE, symbol))
    if data and len(data) >= 2:
        old_oi = float(data[0].get("sumOpenInterest", 0))
        new_oi = float(data[-1].get("sumOpenInterest", 0))
        change = (new_oi - old_oi) / old_oi * 100 if old_oi > 0 else 0
        return change, new_oi
    return 0.0, 0.0

def fetch_long_short_ratio(symbol):
    data = safe_get("%s/futures/data/globalLongShortAccountRatio?symbol=%s&period=1h&limit=5" % (
        BINANCE_BASE, symbol))
    if data and len(data) > 0:
        return float(data[-1].get("longShortRatio", 1.0))
    return 1.0

def fetch_fear_greed():
    data = safe_get(FEAR_GREED_URL)
    if data and data.get("data"):
        return int(data["data"][0].get("value", 50))
    return 50

def fetch_btc_dominance():
    data = safe_get("https://api.coingecko.com/api/v3/global")
    if data and data.get("data"):
        dom = data["data"].get("market_cap_percentage", {})
        return float(dom.get("btc", 50))
    return 50.0

def fetch_btc_ticker():
    data = safe_get("%s/fapi/v1/ticker/24hr?symbol=BTCUSDT" % BINANCE_BASE)
    if data:
        return float(data.get("priceChangePercent", 0))
    return 0.0

# ════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ════════════════════════════════════════════════════════════════════════════

def parse_klines(klines):
    if not klines: return [], [], [], [], []
    opens   = [float(k[1]) for k in klines]
    highs   = [float(k[2]) for k in klines]
    lows    = [float(k[3]) for k in klines]
    closes  = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    return opens, highs, lows, closes, volumes

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
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    return 100 - (100 / (1 + ag/al))

def stoch_rsi(closes, period=14, smooth_k=3, smooth_d=3):
    if len(closes) < period * 2: return 50, 50
    rsi_values = []
    for i in range(period, len(closes)+1):
        rsi_values.append(rsi(closes[:i], period))
    if len(rsi_values) < period: return 50, 50
    recent = rsi_values[-period:]
    min_r, max_r = min(recent), max(recent)
    if max_r == min_r: return 50, 50
    raw_k = (rsi_values[-1] - min_r) / (max_r - min_r) * 100
    k_vals = [(r - min_r)/(max_r - min_r)*100 for r in rsi_values[-smooth_k:]]
    k = sum(k_vals) / len(k_vals)
    d = k  # simplified
    return k, d

def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow: return 0, 0, 0
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = ema_fast - ema_slow
    macd_hist = [ema(closes[:i], fast) - ema(closes[:i], slow)
                 for i in range(slow, len(closes)+1)]
    sig_line = sum(macd_hist[-signal:]) / len(macd_hist[-signal:]) if len(macd_hist) >= signal else macd_line
    hist = macd_line - sig_line
    return macd_line, sig_line, hist

def bollinger(closes, period=20, std_dev=2):
    if len(closes) < period: return closes[-1]*1.02, closes[-1], closes[-1]*0.98
    r = closes[-period:]
    mid = sum(r) / period
    std = (sum((x-mid)**2 for x in r) / period) ** 0.5
    return mid + std_dev*std, mid, mid - std_dev*std

def atr(highs, lows, closes, period=14):
    if len(closes) < 2: return closes[-1] * 0.02
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    return sum(trs[-period:]) / min(len(trs), period)

def williams_r(highs, lows, closes, period=14):
    if len(closes) < period: return -50
    h = max(highs[-period:])
    l = min(lows[-period:])
    if h == l: return -50
    return (h - closes[-1]) / (h - l) * -100

def obv(closes, volumes):
    o = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]: o += volumes[i]
        elif closes[i] < closes[i-1]: o -= volumes[i]
    return o

def obv_trend(closes, volumes, period=20):
    if len(closes) < period + 1: return 0
    obvs = []
    o = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]: o += volumes[i]
        elif closes[i] < closes[i-1]: o -= volumes[i]
        obvs.append(o)
    if len(obvs) < period: return 0
    recent = obvs[-period:]
    slope = (recent[-1] - recent[0]) / period
    return slope

def vwap(highs, lows, closes, volumes):
    typical = [(h+l+c)/3 for h,l,c in zip(highs, lows, closes)]
    tp_vol = sum(t*v for t,v in zip(typical, volumes))
    total_vol = sum(volumes)
    return tp_vol / total_vol if total_vol > 0 else closes[-1]

# ════════════════════════════════════════════════════════════════════════════
# MARKET STRUCTURE ANALYSIS
# ════════════════════════════════════════════════════════════════════════════

def find_swing_points(highs, lows, lookback=5):
    swing_highs, swing_lows = [], []
    for i in range(lookback, len(highs)-lookback):
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows

def market_structure(highs, lows, closes):
    sh, sl = find_swing_points(highs, lows)
    if len(sh) < 2 or len(sl) < 2:
        return "NEUTRAL", False, False

    # Check HH/HL (uptrend) or LH/LL (downtrend)
    last_highs = [h for _,h in sh[-3:]]
    last_lows  = [l for _,l in sl[-3:]]

    hh = all(last_highs[i] > last_highs[i-1] for i in range(1, len(last_highs)))
    hl = all(last_lows[i]  > last_lows[i-1]  for i in range(1, len(last_lows)))
    lh = all(last_highs[i] < last_highs[i-1] for i in range(1, len(last_highs)))
    ll = all(last_lows[i]  < last_lows[i-1]  for i in range(1, len(last_lows)))

    if hh and hl: trend = "UPTREND"
    elif lh and ll: trend = "DOWNTREND"
    else: trend = "RANGING"

    # Break of Structure
    bos_bull = len(sh) >= 2 and closes[-1] > sh[-2][1]
    bos_bear = len(sl) >= 2 and closes[-1] < sl[-2][1]

    return trend, bos_bull, bos_bear

def find_sr_zones(highs, lows, closes, tolerance=0.005):
    levels = []
    for h in highs[-50:]: levels.append(h)
    for l in lows[-50:]:  levels.append(l)
    levels.sort()

    zones = []
    used  = set()
    for i, level in enumerate(levels):
        if i in used: continue
        cluster = [level]
        for j in range(i+1, len(levels)):
            if j in used: continue
            if abs(levels[j] - level) / level <= tolerance:
                cluster.append(levels[j])
                used.add(j)
        if len(cluster) >= 3:
            zones.append(sum(cluster)/len(cluster))
        used.add(i)

    price = closes[-1]
    supports    = sorted([z for z in zones if z < price], reverse=True)
    resistances = sorted([z for z in zones if z > price])
    return supports[:3], resistances[:3]

def detect_candlestick_patterns(opens, highs, lows, closes):
    patterns = []
    if len(closes) < 3: return patterns
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    po, ph, pl, pc = opens[-2], highs[-2], lows[-2], closes[-2]
    body = abs(c - o)
    full_range = h - l

    # Doji
    if full_range > 0 and body / full_range < 0.1:
        patterns.append("Doji (indecision)")

    # Hammer (bullish)
    lower_wick = min(o,c) - l
    upper_wick = h - max(o,c)
    if body > 0 and lower_wick >= 2*body and upper_wick <= 0.5*body and c > o:
        patterns.append("Hammer (bullish)")

    # Shooting Star (bearish)
    if body > 0 and upper_wick >= 2*body and lower_wick <= 0.5*body and c < o:
        patterns.append("Shooting Star (bearish)")

    # Bullish Engulfing
    if pc < po and c > o and c > po and o < pc:
        patterns.append("Bullish Engulfing")

    # Bearish Engulfing
    if pc > po and c < o and c < po and o > pc:
        patterns.append("Bearish Engulfing")

    # Morning Star (bullish reversal)
    if len(closes) >= 3:
        o2,c2 = opens[-3], closes[-3]
        if c2 < o2 and abs(o-c) < abs(o2-c2)*0.3 and c > (o2+c2)/2:
            patterns.append("Morning Star (bullish reversal)")

    # Evening Star (bearish reversal)
    if len(closes) >= 3:
        o2,c2 = opens[-3], closes[-3]
        if c2 > o2 and abs(o-c) < abs(o2-c2)*0.3 and c < (o2+c2)/2:
            patterns.append("Evening Star (bearish reversal)")

    return patterns

def detect_divergence(closes, rsi_vals, lookback=20):
    if len(closes) < lookback or len(rsi_vals) < lookback:
        return False, False
    price_slice = closes[-lookback:]
    rsi_slice   = rsi_vals[-lookback:]

    # Bullish divergence: price lower low, RSI higher low
    price_ll = price_slice[-1] < min(price_slice[:-5])
    rsi_hl   = rsi_slice[-1]   > min(rsi_slice[:-5])
    bull_div = price_ll and rsi_hl

    # Bearish divergence: price higher high, RSI lower high
    price_hh = price_slice[-1] > max(price_slice[:-5])
    rsi_lh   = rsi_slice[-1]   < max(rsi_slice[:-5])
    bear_div = price_hh and rsi_lh

    return bull_div, bear_div

# ════════════════════════════════════════════════════════════════════════════
# MASTER SIGNAL ENGINE
# ════════════════════════════════════════════════════════════════════════════

def analyze(symbol, ticker, market_data):
    price    = float(ticker.get("lastPrice", 0))
    vol_24h  = float(ticker.get("quoteVolume", 0))
    chg_24h  = float(ticker.get("priceChangePercent", 0))

    if price == 0 or vol_24h < 30_000_000:
        return None

    # Fetch multi-timeframe candles
    k15  = fetch_klines(symbol, "15m", 150); time.sleep(0.15)
    k1h  = fetch_klines(symbol, "1h",  200); time.sleep(0.15)
    k4h  = fetch_klines(symbol, "4h",  100); time.sleep(0.15)
    k1d  = fetch_klines(symbol, "1d",   60); time.sleep(0.15)

    if not k15 or not k1h or not k4h:
        return None

    o15,h15,l15,c15,v15 = parse_klines(k15)
    o1h,h1h,l1h,c1h,v1h = parse_klines(k1h)
    o4h,h4h,l4h,c4h,v4h = parse_klines(k4h)
    o1d,h1d,l1d,c1d,v1d = parse_klines(k1d) if k1d else ([],[],[],[],[])

    # ── Indicators ──────────────────────────────────────────────────────────
    rsi15  = rsi(c15);  rsi1h = rsi(c1h);  rsi4h = rsi(c4h)
    rsi1d  = rsi(c1d) if c1d else 50

    sk15,sd15 = stoch_rsi(c15)
    sk1h,sd1h = stoch_rsi(c1h)

    ml15,ms15,mh15 = macd(c15)
    ml1h,ms1h,mh1h = macd(c1h)
    ml4h,ms4h,mh4h = macd(c4h)

    ema8_1h   = ema(c1h, 8)
    ema21_1h  = ema(c1h, 21)
    ema50_1h  = ema(c1h, 50)
    ema100_1h = ema(c1h, 100)
    ema200_1h = ema(c1h, 200) if len(c1h) >= 200 else ema(c1h, len(c1h))

    ema50_4h  = ema(c4h, 50)
    ema200_4h = ema(c4h, 200) if len(c4h) >= 200 else ema(c4h, len(c4h))

    bbu1h,bbm1h,bbl1h = bollinger(c1h)
    bbu4h,bbm4h,bbl4h = bollinger(c4h)

    atr1h = atr(h1h, l1h, c1h)
    atr4h = atr(h4h, l4h, c4h)

    wr1h  = williams_r(h1h, l1h, c1h)
    wr4h  = williams_r(h4h, l4h, c4h)

    obv_s = obv_trend(c1h, v1h)
    vwap1h = vwap(h1h, l1h, c1h, v1h)

    # Volume analysis
    avg_vol_1h = sum(v1h[-20:]) / 20 if len(v1h) >= 20 else v1h[-1]
    vol_spike  = v1h[-1] / avg_vol_1h if avg_vol_1h > 0 else 1

    # Market structure
    trend_1h, bos_bull_1h, bos_bear_1h = market_structure(h1h, l1h, c1h)
    trend_4h, bos_bull_4h, bos_bear_4h = market_structure(h4h, l4h, c4h)

    # Support/Resistance zones
    supports, resistances = find_sr_zones(h1h, l1h, c1h)

    # Candlestick patterns
    candle_patterns_1h = detect_candlestick_patterns(o1h, h1h, l1h, c1h)
    candle_patterns_15m = detect_candlestick_patterns(o15, h15, l15, c15)

    # RSI history for divergence
    rsi_hist = [rsi(c1h[:i]) for i in range(20, len(c1h)+1)]
    bull_div, bear_div = detect_divergence(c1h, rsi_hist)

    # Market-wide data
    fear_greed = market_data.get("fear_greed", 50)
    btc_dom    = market_data.get("btc_dom", 50)
    btc_chg    = market_data.get("btc_chg", 0)

    # Funding & OI
    funding    = fetch_funding_rate(symbol);  time.sleep(0.1)
    oi_chg, oi = fetch_oi_history(symbol);   time.sleep(0.1)
    ls_ratio   = fetch_long_short_ratio(symbol); time.sleep(0.1)

    # ── Scoring Engine ───────────────────────────────────────────────────────
    long_score  = 0
    short_score = 0
    long_reasons  = []
    short_reasons = []

    # 1. RSI Multi-timeframe (max 30 pts)
    if rsi15 < 25:   long_score += 10; long_reasons.append("RSI 15m deeply oversold (%.1f)" % rsi15)
    elif rsi15 < 35: long_score += 6;  long_reasons.append("RSI 15m oversold (%.1f)" % rsi15)
    if rsi1h < 30:   long_score += 12; long_reasons.append("RSI 1h oversold (%.1f)" % rsi1h)
    elif rsi1h < 40: long_score += 7;  long_reasons.append("RSI 1h low (%.1f)" % rsi1h)
    if rsi4h < 35:   long_score += 8;  long_reasons.append("RSI 4h oversold (%.1f)" % rsi4h)

    if rsi15 > 75:   short_score += 10; short_reasons.append("RSI 15m deeply overbought (%.1f)" % rsi15)
    elif rsi15 > 65: short_score += 6;  short_reasons.append("RSI 15m overbought (%.1f)" % rsi15)
    if rsi1h > 70:   short_score += 12; short_reasons.append("RSI 1h overbought (%.1f)" % rsi1h)
    elif rsi1h > 60: short_score += 7;  short_reasons.append("RSI 1h high (%.1f)" % rsi1h)
    if rsi4h > 65:   short_score += 8;  short_reasons.append("RSI 4h overbought (%.1f)" % rsi4h)

    # 2. Stochastic RSI (max 15 pts)
    if sk1h < 20 and sd1h < 20:
        long_score += 15; long_reasons.append("Stoch RSI oversold (%.1f)" % sk1h)
    elif sk1h < 20:
        long_score += 8
    if sk1h > 80 and sd1h > 80:
        short_score += 15; short_reasons.append("Stoch RSI overbought (%.1f)" % sk1h)
    elif sk1h > 80:
        short_score += 8

    # 3. MACD Multi-TF (max 20 pts)
    if mh1h > 0 and mh15 > 0 and mh4h > 0:
        long_score += 20; long_reasons.append("MACD bullish all TFs")
    elif mh1h > 0 and mh15 > 0:
        long_score += 12; long_reasons.append("MACD bullish 1h+15m")
    elif mh1h > 0:
        long_score += 6

    if mh1h < 0 and mh15 < 0 and mh4h < 0:
        short_score += 20; short_reasons.append("MACD bearish all TFs")
    elif mh1h < 0 and mh15 < 0:
        short_score += 12; short_reasons.append("MACD bearish 1h+15m")
    elif mh1h < 0:
        short_score += 6

    # 4. EMA Alignment (max 20 pts)
    if price > ema8_1h > ema21_1h > ema50_1h > ema200_1h:
        long_score += 20; long_reasons.append("Perfect EMA alignment (bullish)")
    elif price > ema21_1h > ema50_1h:
        long_score += 12; long_reasons.append("EMA 21 > 50 (bullish trend)")
    elif price > ema50_1h > ema200_1h:
        long_score += 8; long_reasons.append("Above EMA 50 & 200")

    if price < ema8_1h < ema21_1h < ema50_1h:
        short_score += 20; short_reasons.append("Perfect EMA alignment (bearish)")
    elif price < ema21_1h < ema50_1h:
        short_score += 12; short_reasons.append("EMA 21 < 50 (bearish trend)")
    elif price < ema50_1h < ema200_1h:
        short_score += 8; short_reasons.append("Below EMA 50 & 200")

    # 5. Bollinger Bands (max 15 pts)
    bb_width = (bbu1h - bbl1h) / bbm1h
    if price <= bbl1h:
        long_score += 15; long_reasons.append("Price at/below lower BB")
    elif price <= bbl1h * 1.005:
        long_score += 8
    if price >= bbu1h:
        short_score += 15; short_reasons.append("Price at/above upper BB")
    elif price >= bbu1h * 0.995:
        short_score += 8

    # 6. Williams %R (max 10 pts)
    if wr1h < -80 and wr4h < -75:
        long_score += 10; long_reasons.append("Williams R oversold both TFs")
    elif wr1h < -80:
        long_score += 5
    if wr1h > -20 and wr4h > -25:
        short_score += 10; short_reasons.append("Williams R overbought both TFs")
    elif wr1h > -20:
        short_score += 5

    # 7. Market Structure (max 20 pts)
    if trend_4h == "UPTREND" and trend_1h == "UPTREND":
        long_score += 15; long_reasons.append("Uptrend confirmed 4h+1h")
    elif trend_4h == "UPTREND":
        long_score += 8; long_reasons.append("4h uptrend")
    if bos_bull_1h:
        long_score += 5; long_reasons.append("Break of structure (bullish)")

    if trend_4h == "DOWNTREND" and trend_1h == "DOWNTREND":
        short_score += 15; short_reasons.append("Downtrend confirmed 4h+1h")
    elif trend_4h == "DOWNTREND":
        short_score += 8; short_reasons.append("4h downtrend")
    if bos_bear_1h:
        short_score += 5; short_reasons.append("Break of structure (bearish)")

    # 8. Support/Resistance (max 15 pts)
    if supports:
        near_sup = min(abs(price - s)/price for s in supports)
        if near_sup < 0.008:
            long_score += 15; long_reasons.append("At key support zone")
        elif near_sup < 0.015:
            long_score += 8
    if resistances:
        near_res = min(abs(price - r)/price for r in resistances)
        if near_res < 0.008:
            short_score += 15; short_reasons.append("At key resistance zone")
        elif near_res < 0.015:
            short_score += 8

    # 9. Volume & OBV (max 15 pts)
    if vol_spike > 2.5 and chg_24h > 0:
        long_score += 10; long_reasons.append("Volume surge on bullish move (%.1fx)" % vol_spike)
    elif vol_spike > 1.5 and chg_24h > 0:
        long_score += 5
    if vol_spike > 2.5 and chg_24h < 0:
        short_score += 10; short_reasons.append("Volume surge on bearish move (%.1fx)" % vol_spike)
    elif vol_spike > 1.5 and chg_24h < 0:
        short_score += 5
    if obv_s > 0:
        long_score += 5; long_reasons.append("OBV trending up")
    elif obv_s < 0:
        short_score += 5; short_reasons.append("OBV trending down")

    # 10. VWAP (max 10 pts)
    if price > vwap1h * 1.002:
        long_score += 10; long_reasons.append("Price above VWAP")
    elif price < vwap1h * 0.998:
        short_score += 10; short_reasons.append("Price below VWAP")

    # 11. Candlestick Patterns (max 15 pts)
    bullish_candles = [p for p in candle_patterns_1h + candle_patterns_15m if "bullish" in p.lower() or "hammer" in p.lower() or "morning" in p.lower() or "engulfing" in p.lower() and "bearish" not in p.lower()]
    bearish_candles = [p for p in candle_patterns_1h + candle_patterns_15m if "bearish" in p.lower() or "shooting" in p.lower() or "evening" in p.lower()]
    if bullish_candles:
        long_score += min(15, len(bullish_candles) * 7)
        long_reasons.append("Pattern: %s" % bullish_candles[0])
    if bearish_candles:
        short_score += min(15, len(bearish_candles) * 7)
        short_reasons.append("Pattern: %s" % bearish_candles[0])

    # 12. RSI Divergence (max 15 pts)
    if bull_div:
        long_score += 15; long_reasons.append("Bullish RSI divergence detected")
    if bear_div:
        short_score += 15; short_reasons.append("Bearish RSI divergence detected")

    # 13. Funding Rate (max 10 pts)
    if funding < -0.05:
        long_score += 10; long_reasons.append("Negative funding rate (%.3f%%) - longs favored" % funding)
    elif funding < -0.02:
        long_score += 5
    if funding > 0.05:
        short_score += 10; short_reasons.append("High positive funding (%.3f%%) - shorts favored" % funding)
    elif funding > 0.02:
        short_score += 5

    # 14. Open Interest (max 10 pts)
    if oi_chg > 10 and chg_24h > 0:
        long_score += 10; long_reasons.append("OI rising with price (%.1f%%)" % oi_chg)
    elif oi_chg < -10 and chg_24h < 0:
        short_score += 10; short_reasons.append("OI rising with price drop (%.1f%%)" % oi_chg)

    # 15. Long/Short Ratio (max 8 pts)
    if ls_ratio < 0.8:
        long_score += 8; long_reasons.append("Majority short (%.2f ratio) - squeeze potential" % ls_ratio)
    elif ls_ratio > 1.5:
        short_score += 8; short_reasons.append("Majority long (%.2f ratio) - flush potential" % ls_ratio)

    # 16. Fear & Greed (max 8 pts)
    if fear_greed < 25:
        long_score += 8; long_reasons.append("Extreme Fear (FGI: %d) - buy opportunity" % fear_greed)
    elif fear_greed < 40:
        long_score += 4
    if fear_greed > 80:
        short_score += 8; short_reasons.append("Extreme Greed (FGI: %d) - sell opportunity" % fear_greed)
    elif fear_greed > 65:
        short_score += 4

    # 17. BTC Correlation (max 8 pts)
    if btc_chg > 3 and symbol != "BTCUSDT":
        long_score += 8; long_reasons.append("BTC pumping +%.1f%% (correlation)" % btc_chg)
    elif btc_chg < -3 and symbol != "BTCUSDT":
        short_score += 8; short_reasons.append("BTC dumping %.1f%% (correlation)" % btc_chg)

    # ── Normalize scores ─────────────────────────────────────────────────────
    max_possible = 219
    long_pct  = min(int(long_score  / max_possible * 100), 100)
    short_pct = min(int(short_score / max_possible * 100), 100)

    # ── Determine direction ──────────────────────────────────────────────────
    direction = None
    final_score = 0
    reasons = []

    if long_pct >= MIN_SCORE and long_pct > short_pct + 10:
        direction = "LONG"
        final_score = long_pct
        reasons = long_reasons
    elif short_pct >= MIN_SCORE and short_pct > long_pct + 10:
        direction = "SHORT"
        final_score = short_pct
        reasons = short_reasons

    if not direction:
        return None

    # ── Entry, SL, TP (ATR-based) ────────────────────────────────────────────
    atr_val = atr1h

    if direction == "LONG":
        entry = price
        sl    = entry - atr_val * 1.8
        tp1   = entry + atr_val * 1.5
        tp2   = entry + atr_val * 3.0
        tp3   = entry + atr_val * 5.0
        # Adjust SL to nearest support
        if supports and supports[0] > sl:
            sl = supports[0] * 0.998
    else:
        entry = price
        sl    = entry + atr_val * 1.8
        tp1   = entry - atr_val * 1.5
        tp2   = entry - atr_val * 3.0
        tp3   = entry - atr_val * 5.0
        if resistances and resistances[0] < sl:
            sl = resistances[0] * 1.002

    risk   = abs(entry - sl)
    reward = abs(tp2 - entry)
    rr     = reward / risk if risk > 0 else 0

    if rr < MIN_RR:
        return None

    # ── Leverage recommendation ──────────────────────────────────────────────
    if final_score >= 88:   leverage = "5-8x"
    elif final_score >= 80: leverage = "3-5x"
    else:                   leverage = "2-3x"

    # ── Signal quality tier ──────────────────────────────────────────────────
    if final_score >= 88 and rr >= 3.0:   tier = "S-TIER (PREMIUM)"
    elif final_score >= 80 and rr >= 2.5: tier = "A-TIER (HIGH CONF)"
    else:                                  tier = "B-TIER (STANDARD)"

    return {
        "symbol":       symbol,
        "direction":    direction,
        "score":        final_score,
        "tier":         tier,
        "price":        price,
        "entry":        entry,
        "sl":           sl,
        "tp1":          tp1,
        "tp2":          tp2,
        "tp3":          tp3,
        "rr":           rr,
        "leverage":     leverage,
        "rsi15":        rsi15,
        "rsi1h":        rsi1h,
        "rsi4h":        rsi4h,
        "rsi1d":        rsi1d,
        "macd_hist_1h": mh1h,
        "funding":      funding,
        "oi_chg":       oi_chg,
        "ls_ratio":     ls_ratio,
        "vol_spike":    vol_spike,
        "vol_24h":      vol_24h,
        "chg_24h":      chg_24h,
        "fear_greed":   fear_greed,
        "btc_dom":      btc_dom,
        "trend_4h":     trend_4h,
        "trend_1h":     trend_1h,
        "supports":     supports,
        "resistances":  resistances,
        "patterns":     candle_patterns_1h[:2],
        "bull_div":     bull_div,
        "bear_div":     bear_div,
        "reasons":      reasons[:8],
        "atr":          atr_val,
        "long_score":   long_pct,
        "short_score":  short_pct,
    }

# ════════════════════════════════════════════════════════════════════════════
# MESSAGE BUILDER
# ════════════════════════════════════════════════════════════════════════════

def build_message(s):
    def fp(n):
        if n >= 1000: return "%.2f" % n
        if n >= 1:    return "%.4f" % n
        if n >= 0.01: return "%.6f" % n
        return "%.8f" % n

    def fv(n):
        if n >= 1e9: return "$%.2fB" % (n/1e9)
        if n >= 1e6: return "$%.1fM" % (n/1e6)
        return "$%.0fK" % (n/1e3)

    dir_str = "LONG" if s["direction"] == "LONG" else "SHORT"
    tier_icon = {"S-TIER (PREMIUM)":"[S]","A-TIER (HIGH CONF)":"[A]","B-TIER (STANDARD)":"[B]"}.get(s["tier"],"[?]")
    score_bar = "#" * round(s["score"]/10) + "-" * (10 - round(s["score"]/10))

    fg_label = "Extreme Fear" if s["fear_greed"] < 25 else "Fear" if s["fear_greed"] < 45 else "Neutral" if s["fear_greed"] < 55 else "Greed" if s["fear_greed"] < 75 else "Extreme Greed"
    reasons_text = "\n".join(["  [+] " + r for r in s["reasons"]])
    patterns_text = ", ".join(s["patterns"]) if s["patterns"] else "None"

    sl_pct  = abs(s["entry"] - s["sl"])  / s["entry"] * 100
    tp1_pct = abs(s["tp1"]   - s["entry"]) / s["entry"] * 100
    tp2_pct = abs(s["tp2"]   - s["entry"]) / s["entry"] * 100
    tp3_pct = abs(s["tp3"]   - s["entry"]) / s["entry"] * 100

    return (
        "%s %s SIGNAL\n"
        "Pair: %s/USDT | Score: %d/100\n"
        "Tier: %s\n"
        "[%s]\n"
        "\n"
        "=== TRADE SETUP ===\n"
        "Direction: %s\n"
        "Entry:     $%s\n"
        "Stop Loss: $%s  (-%.2f%%)\n"
        "TP1:       $%s  (+%.2f%%)\n"
        "TP2:       $%s  (+%.2f%%)\n"
        "TP3:       $%s  (+%.2f%%)\n"
        "R/R Ratio: %.2fx\n"
        "Leverage:  %s (use responsibly)\n"
        "\n"
        "=== TECHNICAL ANALYSIS ===\n"
        "RSI  15m: %.1f | 1h: %.1f | 4h: %.1f | 1d: %.1f\n"
        "MACD 1h:  %s\n"
        "Trend 4h: %s | 1h: %s\n"
        "Patterns: %s\n"
        "%s\n"
        "\n"
        "=== MARKET DATA ===\n"
        "Volume 24h: %s (%.1fx avg)\n"
        "Price 24h:  %+.2f%%\n"
        "Funding:    %.4f%%\n"
        "OI Change:  %+.1f%%\n"
        "L/S Ratio:  %.2f\n"
        "Fear/Greed: %d (%s)\n"
        "BTC Dom:    %.1f%%\n"
        "\n"
        "=== WHY THIS SIGNAL ===\n"
        "%s\n"
        "\n"
        "=== RISK MANAGEMENT ===\n"
        "- Max 3-5%% portfolio per trade\n"
        "- Set SL immediately after entry\n"
        "- Take 40%% profit at TP1\n"
        "- Take 35%% profit at TP2\n"
        "- Let 25%% run to TP3\n"
        "- Move SL to entry after TP1 hit\n"
        "\n"
        "Signal Time: %s UTC\n"
        "Not financial advice - DYOR!"
    ) % (
        tier_icon, dir_str,
        s["symbol"].replace("USDT",""), s["score"],
        s["tier"], score_bar,
        dir_str,
        fp(s["entry"]),
        fp(s["sl"]), sl_pct,
        fp(s["tp1"]), tp1_pct,
        fp(s["tp2"]), tp2_pct,
        fp(s["tp3"]), tp3_pct,
        s["rr"], s["leverage"],
        s["rsi15"], s["rsi1h"], s["rsi4h"], s["rsi1d"],
        "Bullish" if s["macd_hist_1h"] > 0 else "Bearish",
        s["trend_4h"], s["trend_1h"],
        patterns_text,
        "[!] BULLISH DIVERGENCE" if s["bull_div"] else "[!] BEARISH DIVERGENCE" if s["bear_div"] else "",
        fv(s["vol_24h"]), s["vol_spike"],
        s["chg_24h"],
        s["funding"],
        s["oi_chg"],
        s["ls_ratio"],
        s["fear_greed"], fg_label,
        s["btc_dom"],
        reasons_text,
        datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
    )

# ════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════════════════════════════

async def main():
    log.info("Professional Futures Signal Bot starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Professional Futures Signal Bot Online!\n\n"
            "Scanning: Top 40 high-volume USDT pairs\n"
            "Timeframes: 15m + 1h + 4h + 1d\n\n"
            "Indicators:\n"
            "- RSI (all TFs) + Stochastic RSI\n"
            "- MACD (multi-TF confluence)\n"
            "- EMA 8/21/50/100/200\n"
            "- Bollinger Bands\n"
            "- Williams %R\n"
            "- ATR-based SL/TP\n"
            "- VWAP + OBV\n"
            "- Market Structure (HH/HL/LH/LL)\n"
            "- S/R Zone Detection\n"
            "- Candlestick Patterns\n"
            "- RSI Divergence\n"
            "- Funding Rate\n"
            "- Open Interest\n"
            "- Long/Short Ratio\n"
            "- Fear & Greed Index\n"
            "- BTC Correlation\n\n"
            "Min Score: %d/100\n"
            "Min R/R: %.1fx\n"
            "Scan every: %ds\n\n"
            "Not financial advice - DYOR!"
        ) % (MIN_SCORE, MIN_RR, SCAN_INTERVAL)
    )

    seen_signals = {}
    scan_count   = 0

    while True:
        scan_count += 1
        log.info("Scan #%d starting..." % scan_count)

        # Fetch market-wide data once per scan
        market_data = {
            "fear_greed": fetch_fear_greed(),
            "btc_dom":    fetch_btc_dominance(),
            "btc_chg":    fetch_btc_ticker(),
        }
        log.info("Market: FGI=%d BTC_DOM=%.1f%% BTC_CHG=%.2f%%" % (
            market_data["fear_greed"], market_data["btc_dom"], market_data["btc_chg"]))

        try:
            pairs = fetch_top_pairs()
            log.info("Analyzing %d pairs..." % len(pairs))
            signals_sent = 0

            for ticker in pairs:
                symbol = ticker.get("symbol","")
                if not symbol: continue

                last = seen_signals.get(symbol, 0)
                if time.time() - last < SIGNAL_COOLDOWN:
                    continue

                try:
                    result = analyze(symbol, ticker, market_data)
                    if result:
                        msg = build_message(result)
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            disable_web_page_preview=True
                        )
                        seen_signals[symbol] = time.time()
                        signals_sent += 1
                        log.info("Signal: %s %s score=%d tier=%s rr=%.2f" % (
                            symbol, result["direction"], result["score"],
                            result["tier"], result["rr"]
                        ))
                        await asyncio.sleep(2)
                except Exception as e:
                    log.error("Error analyzing %s: %s" % (symbol, e))

            log.info("Scan #%d done. Sent %d signals." % (scan_count, signals_sent))

        except Exception as e:
            log.error("Scan error: %s" % e)

        log.info("Next scan in %ds..." % SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
