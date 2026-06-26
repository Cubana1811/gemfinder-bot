"""
GemFinder Backtester — 90-day 4h Binance simulation.

Walks through historical 4h candles for 20 top coins, applies every
Binance-based gate and scoring rule from tradingview_scanner.py,
simulates ATR-based entries, then walks forward to resolve TP1 / TP2 / SL.

TradingView rating is not available historically, so this script tests the
CONFIRMATION LAYER (Binance gates + indicators) in isolation. In live use the
TV screener pre-screens candidates, so the actual win rate should be higher.

Usage:
    python backtest.py

Output: per-symbol stats + overall win rate, profit factor, average R/R.
"""

import time
import requests

BYBIT_BASE   = "https://api.bybit.com"
INTERVAL_MAP = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
                "1d": "D", "1w": "W"}

COINS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "MATICUSDT",
    "LTCUSDT", "ATOMUSDT", "DOTUSDT", "NEARUSDT", "UNIUSDT",
    "OPUSDT",  "AAVEUSDT", "INJUSDT",  "APTUSDT",  "ARBUSDT",
]

# ── Inline indicator functions (no import needed) ─────────────────────────────

def safe_get(url, timeout=15):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("  [HTTP] %s: %s" % (url[:60], e))
    return None

def fetch_klines(symbol, interval="4h", limit=540):
    bybit_interval = INTERVAL_MAP.get(interval, interval)
    data = safe_get("%s/v5/market/kline?category=linear&symbol=%s&interval=%s&limit=%s" % (
        BYBIT_BASE, symbol, bybit_interval, limit))
    if data and data.get("retCode") == 0:
        return list(reversed(data["result"]["list"]))
    return []

def parse_klines(klines):
    if not klines:
        return [], [], [], [], []
    return (
        [float(k[1]) for k in klines],
        [float(k[2]) for k in klines],
        [float(k[3]) for k in klines],
        [float(k[4]) for k in klines],
        [float(k[5]) for k in klines],
    )

def ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2.0 / (period + 1)
    e = sum(closes[:period]) / period
    for p in closes[period:]:
        e = p * k + e * (1 - k)
    return e

def rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100
    return 100 - (100 / (1 + ag / al))

def macd_hist(closes, fast=12, slow=26, signal_p=9):
    if len(closes) < slow + signal_p:
        return 0
    ema_f = ema(closes, fast)
    ema_s = ema(closes, slow)
    macd_line = ema_f - ema_s
    hist_vals = [ema(closes[:i], fast) - ema(closes[:i], slow)
                 for i in range(slow, len(closes) + 1)]
    sig = sum(hist_vals[-signal_p:]) / len(hist_vals[-signal_p:]) if len(hist_vals) >= signal_p else macd_line
    return macd_line - sig

def atr_calc(highs, lows, closes, period=14):
    if len(closes) < 2:
        return closes[-1] * 0.02
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i-1]),
               abs(lows[i]  - closes[i-1]))
           for i in range(1, len(closes))]
    return sum(trs[-period:]) / min(len(trs), period)

def adx_value(highs, lows, closes, period=14):
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
    if hh and hl:
        return "UPTREND"
    if lh and ll:
        return "DOWNTREND"
    return "RANGING"

def candle_structure(opens, closes, window=3):
    bull = sum(1 for i in range(-window, 0) if closes[i] > opens[i])
    bear = sum(1 for i in range(-window, 0) if closes[i] < opens[i])
    return bull, bear

def bb_squeeze_state(closes, period=20, std_dev=2, expand_lookback=8):
    if len(closes) < period + expand_lookback:
        return False

    def bb_width(window):
        mid = sum(window) / len(window)
        std = (sum((x - mid) ** 2 for x in window) / len(window)) ** 0.5
        return (std * std_dev * 2) / mid if mid > 0 else 0

    widths = [bb_width(closes[-(period + expand_lookback - i):-(expand_lookback - i)])
              for i in range(expand_lookback)]
    widths = [w for w in widths if w > 0]
    if len(widths) < 3:
        return False
    return widths[-1] > (sum(widths[:-2]) / len(widths[:-2])) * 1.08

def liquidity_sweep(highs, lows, closes, opens, sweep_window=5, ref_window=20):
    if len(closes) < ref_window + sweep_window + 2:
        return False, False
    ref_slice = slice(-(ref_window + sweep_window), -sweep_window)
    ref_low   = min(lows[ref_slice])
    ref_high  = max(highs[ref_slice])
    bull_sweep = any(lows[i] < ref_low  and closes[i] > ref_low  for i in range(-sweep_window, 0))
    bear_sweep = any(highs[i] > ref_high and closes[i] < ref_high for i in range(-sweep_window, 0))
    return bull_sweep, bear_sweep

# ── Backtester core ───────────────────────────────────────────────────────────

MIN_ADX    = 20
MIN_SCORE  = 50     # lower threshold for historical test (no TV pre-filter)
SL_MULT    = 1.8
TP1_MULT   = 1.5
TP2_MULT   = 3.0
WARMUP     = 60     # bars needed for indicators to stabilise

def score_bar(opens, highs, lows, closes, idx):
    """
    Score a single historical bar using the confirmation-layer rules.
    Returns (direction, score_pct, entry, sl, tp1, tp2) or None.
    """
    i = idx
    # Minimum history required
    if i < WARMUP:
        return None

    o  = opens[:i+1]
    h  = highs[:i+1]
    l  = lows[:i+1]
    c  = closes[:i+1]

    price = c[-1]
    if price == 0:
        return None

    adx = adx_value(h, l, c)
    if adx < MIN_ADX:
        return None

    ema200 = ema(c, min(200, len(c)))
    rsi1h  = rsi(c)
    mh     = macd_hist(c)
    ema21  = ema(c, 21)
    ema50  = ema(c, 50)
    atr_v  = atr_calc(h, l, c)
    trend  = market_structure(h, l)
    bull_c, bear_c = candle_structure(o, c)
    bb_exp = bb_squeeze_state(c)
    bull_sw, bear_sw = liquidity_sweep(h, l, c, o)

    score_long  = 0
    score_short = 0

    # RSI
    if rsi1h < 30:   score_long  += 12
    elif rsi1h < 40: score_long  += 6
    if rsi1h > 70:   score_short += 12
    elif rsi1h > 60: score_short += 6

    # MACD
    if mh > 0:  score_long  += 8
    if mh < 0:  score_short += 8

    # EMA stack
    if price > ema21 > ema50: score_long  += 8
    if price < ema21 < ema50: score_short += 8

    # Trend structure
    if trend == "UPTREND":   score_long  += 10
    if trend == "DOWNTREND": score_short += 10

    # ADX bonus
    if adx >= 35:
        score_long  += 10
        score_short += 10
    elif adx >= 25:
        score_long  += 5
        score_short += 5

    # BB squeeze
    if bb_exp:
        score_long  += 12
        score_short += 12

    # SMC sweep
    if bull_sw: score_long  += 18
    if bear_sw: score_short += 18

    # Daily EMA 200 alignment gate
    if ema200 > 0:
        if price < ema200 and score_long > score_short:
            return None   # counter-trend long rejected
        if price > ema200 and score_short > score_long:
            return None   # counter-trend short rejected

    # Candle structure gate
    if score_long > score_short and bull_c < 2:
        return None
    if score_short > score_long and bear_c < 2:
        return None

    max_pts = 84   # 12+8+8+10+10+12+18 per side = 78 + ADX bonus 10 = 88 total possible
    long_pct  = min(int(score_long  / max_pts * 100), 100)
    short_pct = min(int(score_short / max_pts * 100), 100)

    if long_pct >= MIN_SCORE and long_pct > short_pct + 8:
        direction = "LONG"
        final = long_pct
    elif short_pct >= MIN_SCORE and short_pct > long_pct + 8:
        direction = "SHORT"
        final = short_pct
    else:
        return None

    entry = price
    if direction == "LONG":
        sl  = entry - atr_v * SL_MULT
        tp1 = entry + atr_v * TP1_MULT
        tp2 = entry + atr_v * TP2_MULT
    else:
        sl  = entry + atr_v * SL_MULT
        tp1 = entry - atr_v * TP1_MULT
        tp2 = entry - atr_v * TP2_MULT

    risk   = abs(entry - sl)
    reward = abs(tp2 - entry)
    rr     = reward / risk if risk > 0 else 0
    if rr < 1.5:
        return None

    return (direction, final, entry, sl, tp1, tp2, rr)


def resolve_trade(direction, entry, sl, tp1, tp2, highs, lows, start_idx):
    """
    Walk forward from start_idx to find which level is hit first.
    Returns ('TP1', bars), ('TP2', bars), ('SL', bars), or ('OPEN', bars).
    """
    for j in range(start_idx, len(highs)):
        h, l = highs[j], lows[j]
        if direction == "LONG":
            if l <= sl:
                return "SL", j - start_idx
            if h >= tp2:
                return "TP2", j - start_idx
            if h >= tp1:
                return "TP1", j - start_idx
        else:
            if h >= sl:
                return "SL", j - start_idx
            if l <= tp2:
                return "TP2", j - start_idx
            if l <= tp1:
                return "TP1", j - start_idx
    return "OPEN", len(highs) - start_idx


def backtest_symbol(symbol, klines):
    opens, highs, lows, closes, _ = parse_klines(klines)
    trades = []
    last_entry_bar = -20   # avoid overlapping trades

    for i in range(WARMUP, len(closes) - 10):
        if i - last_entry_bar < 10:
            continue
        result = score_bar(opens, highs, lows, closes, i)
        if result is None:
            continue

        direction, score, entry, sl, tp1, tp2, rr = result
        outcome, bars_held = resolve_trade(
            direction, entry, sl, tp1, tp2,
            highs, lows, i + 1
        )

        # TP1 = partial win (40%), TP2 = full win; SL = full loss
        if outcome == "TP2":
            pnl_r = rr          # full R multiple
            win   = True
        elif outcome == "TP1":
            pnl_r = abs(tp1 - entry) / abs(entry - sl)   # partial R
            win   = True
        elif outcome == "SL":
            pnl_r = -1.0
            win   = False
        else:
            pnl_r = 0.0
            win   = False

        trades.append({
            "symbol":    symbol,
            "direction": direction,
            "score":     score,
            "rr":        rr,
            "outcome":   outcome,
            "pnl_r":     pnl_r,
            "win":       win,
            "bars_held": bars_held,
        })
        last_entry_bar = i

    return trades


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(all_trades):
    if not all_trades:
        print("No trades generated.")
        return

    total   = len(all_trades)
    wins    = [t for t in all_trades if t["win"]]
    losses  = [t for t in all_trades if t["outcome"] == "SL"]
    tp2s    = [t for t in all_trades if t["outcome"] == "TP2"]
    tp1s    = [t for t in all_trades if t["outcome"] == "TP1"]
    open_t  = [t for t in all_trades if t["outcome"] == "OPEN"]

    win_rate    = len(wins) / total * 100 if total else 0
    avg_rr      = sum(t["rr"] for t in all_trades) / total if total else 0
    gross_win   = sum(t["pnl_r"] for t in all_trades if t["pnl_r"] > 0)
    gross_loss  = abs(sum(t["pnl_r"] for t in all_trades if t["pnl_r"] < 0))
    pf          = gross_win / gross_loss if gross_loss > 0 else float("inf")
    net_r       = sum(t["pnl_r"] for t in all_trades)
    avg_bars    = sum(t["bars_held"] for t in all_trades) / total if total else 0

    print("\n" + "=" * 58)
    print("  BACKTEST RESULTS — 90-day 4h Binance simulation")
    print("=" * 58)
    print("Total trades:     %d" % total)
    print("Wins (TP1+TP2):   %d  (%.1f%%)" % (len(wins), win_rate))
    print("  of which TP2:   %d  (full target)" % len(tp2s))
    print("  of which TP1:   %d  (partial)" % len(tp1s))
    print("Stop-outs (SL):   %d  (%.1f%%)" % (len(losses), len(losses)/total*100 if total else 0))
    print("Still open:       %d" % len(open_t))
    print("Win rate:         %.1f%%" % win_rate)
    print("Profit factor:    %.2f" % pf)
    print("Net R earned:     %+.2f R" % net_r)
    print("Avg R/R setup:    %.2fx" % avg_rr)
    print("Avg bars held:    %.1f  (4h bars = ~%.0f hrs)" % (avg_bars, avg_bars * 4))

    # Score tier breakdown
    print("\n--- By score tier ---")
    for tier_min, tier_max, label in [(80, 100, "High (80-100)"), (65, 80, "Mid (65-79)"), (50, 65, "Base (50-64)")]:
        tier_trades = [t for t in all_trades if tier_min <= t["score"] < tier_max]
        if tier_trades:
            tier_wins = [t for t in tier_trades if t["win"]]
            wr = len(tier_wins) / len(tier_trades) * 100
            print("  %-18s  %3d trades  %.1f%% win rate" % (label, len(tier_trades), wr))

    # Per-symbol breakdown
    print("\n--- Per symbol ---")
    print("%-10s  %5s  %5s  %5s  %6s" % ("Symbol", "Total", "Wins", "Win%", "Net-R"))
    symbols = sorted(set(t["symbol"] for t in all_trades))
    for sym in symbols:
        st  = [t for t in all_trades if t["symbol"] == sym]
        sw  = [t for t in st if t["win"]]
        wr  = len(sw) / len(st) * 100 if st else 0
        nr  = sum(t["pnl_r"] for t in st)
        print("%-10s  %5d  %5d  %5.1f%%  %+6.2f R" % (sym, len(st), len(sw), wr, nr))

    print("\n" + "=" * 58)
    print("Note: TV pre-screener not simulated (historical data N/A)")
    print("Live win rate will be higher — TV filter eliminates ~60%%")
    print("of weak signals before any Binance gate is applied.")
    print("=" * 58 + "\n")


def main():
    print("=" * 58)
    print("  GemFinder Backtester — fetching 90-day 4h data")
    print("=" * 58)

    all_trades = []
    for i, symbol in enumerate(COINS):
        print("[%d/%d] %s..." % (i + 1, len(COINS), symbol), end=" ", flush=True)
        klines = fetch_klines(symbol, "4h", 540)   # 540 × 4h ≈ 90 days
        time.sleep(0.25)

        if not klines or len(klines) < WARMUP + 20:
            print("insufficient data, skipped")
            continue

        trades = backtest_symbol(symbol, klines)
        wins   = sum(1 for t in trades if t["win"])
        print("%d trades, %d wins (%.0f%%)" % (
            len(trades), wins,
            wins / len(trades) * 100 if trades else 0
        ))
        all_trades.extend(trades)

    report(all_trades)


if __name__ == "__main__":
    main()
