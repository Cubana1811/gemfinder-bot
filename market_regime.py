"""
Market Regime Detector — runs every morning at 07:00 UTC and declares
the current market regime: BULL, BEAR, or SIDEWAYS.

All other bots read regime.json to adjust their behaviour:
  - BULL:     tv_scanner focuses on LONG signals only
  - BEAR:     tv_scanner focuses on SHORT signals only
  - SIDEWAYS: raise minimum score threshold, reduce signals

Sends a full morning briefing to Telegram every day at 07:00 UTC.
"""

import os
import json
import time
import logging
import requests
import asyncio
from datetime import datetime, timezone
from telegram import Bot

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID         = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
BYBIT_BASE      = "https://api.bybit.com"
FEAR_GREED_URL  = "https://api.alternative.me/fng/?limit=1"
REGIME_FILE     = "regime.json"
CHECK_INTERVAL  = 60   # check every 60 seconds if it's time to run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────────────────

def safe_get(url, timeout=15):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("HTTP %s: %s" % (url[:55], e))
    return None

INTERVAL_MAP = {"1d": "D", "1w": "W", "4h": "240", "1h": "60", "15m": "15"}

def fetch_klines(symbol, interval, limit):
    bybit_interval = INTERVAL_MAP.get(interval, interval)
    data = safe_get("%s/v5/market/kline?category=linear&symbol=%s&interval=%s&limit=%s" % (
        BYBIT_BASE, symbol, bybit_interval, limit))
    if data and data.get("retCode") == 0:
        candles = list(reversed(data["result"]["list"]))
        return candles
    return []

def fetch_fear_greed():
    data = safe_get(FEAR_GREED_URL)
    if data and data.get("data"):
        return int(data["data"][0].get("value", 50))
    return 50

def fetch_funding(symbol):
    data = safe_get("%s/v5/market/funding/history?category=linear&symbol=%s&limit=1" % (
        BYBIT_BASE, symbol))
    if data and data.get("retCode") == 0:
        entries = data["result"]["list"]
        if entries:
            return float(entries[0].get("fundingRate", 0)) * 100
    return 0.0

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
    if al == 0: return 100
    return 100 - (100 / (1 + ag / al))

def parse_closes(klines):
    return [float(k[4]) for k in klines] if klines else []

def save_regime(regime_data):
    with open(REGIME_FILE, "w") as f:
        json.dump(regime_data, f, indent=2)

def load_regime():
    if not os.path.exists(REGIME_FILE):
        return {"regime": "BULL", "updated": ""}
    try:
        with open(REGIME_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"regime": "BULL", "updated": ""}

# ── Regime analyser ─────────────────────────────────────────────────────────────────────────

def analyse_regime():
    """
    Score the market across 8 dimensions.
    Returns (regime, score, details_dict).
    """
    bull_score = 0
    bear_score = 0
    details    = {}

    # ── BTC daily analysis ────────────────────────────────────────────────────────────────────────────
    btc_1d = fetch_klines("BTCUSDT", "1d", 60)
    btc_1w = fetch_klines("BTCUSDT", "1w", 20)
    time.sleep(0.2)

    if btc_1d:
        c1d        = parse_closes(btc_1d)
        price      = c1d[-1]
        ema21_1d   = ema(c1d, 21)
        ema50_1d   = ema(c1d, 50)
        ema200_1d  = ema(c1d, min(200, len(c1d)))
        rsi_1d     = rsi(c1d)

        details["btc_price"]   = price
        details["btc_ema21"]   = ema21_1d
        details["btc_ema50"]   = ema50_1d
        details["btc_ema200"]  = ema200_1d
        details["btc_rsi_1d"]  = rsi_1d

        # EMA alignment
        if price > ema21_1d > ema50_1d > ema200_1d:
            bull_score += 3
            details["ema_align"] = "BULLISH STACK"
        elif price < ema21_1d < ema50_1d < ema200_1d:
            bear_score += 3
            details["ema_align"] = "BEARISH STACK"
        elif price > ema200_1d:
            bull_score += 1
            details["ema_align"] = "ABOVE EMA200"
        else:
            bear_score += 1
            details["ema_align"] = "BELOW EMA200"

        # Daily RSI
        if rsi_1d > 55:
            bull_score += 2
            details["rsi_signal"] = "BULLISH (%.1f)" % rsi_1d
        elif rsi_1d < 45:
            bear_score += 2
            details["rsi_signal"] = "BEARISH (%.1f)" % rsi_1d
        else:
            details["rsi_signal"] = "NEUTRAL (%.1f)" % rsi_1d

        # 30-day price change
        if len(c1d) >= 30:
            change_30d = (c1d[-1] - c1d[-30]) / c1d[-30] * 100
            details["btc_30d_change"] = change_30d
            if change_30d > 10:
                bull_score += 2
            elif change_30d < -10:
                bear_score += 2
            elif change_30d > 3:
                bull_score += 1
            elif change_30d < -3:
                bear_score += 1

    # ── Weekly trend ─────────────────────────────────────────────────────────────────────────────
    if btc_1w:
        c1w      = parse_closes(btc_1w)
        ema10_1w = ema(c1w, min(10, len(c1w)))
        ema20_1w = ema(c1w, min(20, len(c1w)))

        details["btc_weekly_ema10"] = ema10_1w
        details["btc_weekly_ema20"] = ema20_1w

        if c1w[-1] > ema10_1w > ema20_1w:
            bull_score += 2
            details["weekly_trend"] = "BULLISH"
        elif c1w[-1] < ema10_1w < ema20_1w:
            bear_score += 2
            details["weekly_trend"] = "BEARISH"
        else:
            details["weekly_trend"] = "MIXED"

    # ── ETH confirmation ────────────────────────────────────────────────────────────────────────────
    eth_1d = fetch_klines("ETHUSDT", "1d", 60)
    time.sleep(0.2)

    if eth_1d:
        eth_c     = parse_closes(eth_1d)
        eth_price = eth_c[-1]
        eth_ema200 = ema(eth_c, min(200, len(eth_c)))

        details["eth_price"]  = eth_price
        details["eth_ema200"] = eth_ema200

        if eth_price > eth_ema200:
            bull_score += 1
            details["eth_signal"] = "ABOVE EMA200 (bullish)"
        else:
            bear_score += 1
            details["eth_signal"] = "BELOW EMA200 (bearish)"

    # ── Fear & Greed ────────────────────────────────────────────────────────────────────────────
    fgi = fetch_fear_greed()
    details["fear_greed"] = fgi

    if fgi >= 60:
        bull_score += 1
        details["fgi_signal"] = "GREED (%d) — momentum" % fgi
    elif fgi <= 30:
        bear_score += 1
        details["fgi_signal"] = "FEAR (%d) — caution" % fgi
    elif fgi <= 20:
        bull_score += 1   # extreme fear = contrarian buy
        details["fgi_signal"] = "EXTREME FEAR (%d) — contrarian buy zone" % fgi
    else:
        details["fgi_signal"] = "NEUTRAL (%d)" % fgi

    # ── BTC funding rate ────────────────────────────────────────────────────────────────────────────
    btc_funding = fetch_funding("BTCUSDT")
    details["btc_funding"] = btc_funding

    if -0.02 <= btc_funding <= 0.04:
        bull_score += 1
        details["funding_signal"] = "HEALTHY (%.3f%%)" % btc_funding
    elif btc_funding > 0.08:
        bear_score += 1
        details["funding_signal"] = "OVERCROWDED LONGS (%.3f%%)" % btc_funding
    elif btc_funding < -0.04:
        bull_score += 1
        details["funding_signal"] = "SHORTS PAYING LONGS (%.3f%%)" % btc_funding

    # ── Determine regime ────────────────────────────────────────────────────────────────────────────
    total = bull_score + bear_score
    bull_pct = bull_score / total * 100 if total > 0 else 50

    if bull_pct >= 65:
        regime   = "BULL"
        strength = "STRONG" if bull_pct >= 75 else "MODERATE"
    elif bull_pct <= 35:
        regime   = "BEAR"
        strength = "STRONG" if bull_pct <= 25 else "MODERATE"
    else:
        regime   = "SIDEWAYS"
        strength = "RANGING"

    details["bull_score"] = bull_score
    details["bear_score"] = bear_score
    details["bull_pct"]   = bull_pct
    details["strength"]   = strength

    return regime, strength, details

# ── Morning briefing builder ──────────────────────────────────────────────────────────────────

def build_briefing(regime, strength, d):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    regime_icon = {
        "BULL":     "BULL MARKET",
        "BEAR":     "BEAR MARKET",
        "SIDEWAYS": "SIDEWAYS MARKET",
    }.get(regime, regime)

    scanner_mode = {
        "BULL":     "Scanning for LONG setups only",
        "BEAR":     "Scanning for SHORT setups only",
        "SIDEWAYS": "Selective mode — higher score required",
    }.get(regime, "")

    btc_30d = d.get("btc_30d_change", 0)
    btc_price = d.get("btc_price", 0)

    return (
        "MORNING MARKET BRIEFING — %s\n"
        "\n"
        "=== MARKET REGIME ===\n"
        "%s (%s)\n"
        "\n"
        "Scanner mode today:\n"
        "%s\n"
        "\n"
        "=== BTC ANALYSIS ===\n"
        "Price:      $%.2f\n"
        "30d Change: %+.1f%%\n"
        "EMA Align:  %s\n"
        "RSI Daily:  %s\n"
        "Weekly:     %s\n"
        "Funding:    %s\n"
        "\n"
        "=== ETH SIGNAL ===\n"
        "%s\n"
        "\n"
        "=== SENTIMENT ===\n"
        "Fear/Greed: %s\n"
        "\n"
        "=== SCORE ===\n"
        "Bull: %d pts  |  Bear: %d pts\n"
        "Bull confidence: %.0f%%\n"
        "\n"
        "Trade with the regime.\n"
        "Next briefing: tomorrow 07:00 UTC"
    ) % (
        now,
        regime_icon, strength,
        scanner_mode,
        btc_price,
        btc_30d,
        d.get("ema_align",      "N/A"),
        d.get("rsi_signal",     "N/A"),
        d.get("weekly_trend",   "N/A"),
        d.get("funding_signal", "N/A"),
        d.get("eth_signal",     "N/A"),
        d.get("fgi_signal",     "N/A"),
        d.get("bull_score", 0), d.get("bear_score", 0),
        d.get("bull_pct", 50),
    )

# ── Main loop ────────────────────────────────────────────────────────────────────────────────

async def main():
    log.info("Market Regime Detector starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Market Regime Detector Online!\n\n"
            "Every morning at 07:00 UTC I will:\n\n"
            "  - Analyse BTC weekly + daily trend\n"
            "  - Check ETH confirmation\n"
            "  - Read Fear & Greed index\n"
            "  - Check funding rates\n"
            "  - Declare BULL / BEAR / SIDEWAYS\n\n"
            "All other bots will adjust to the\n"
            "declared regime automatically.\n\n"
            "Running first analysis now..."
        )
    )

    # Run immediately on startup
    try:
        regime, strength, details = analyse_regime()
        regime_data = {
            "regime":    regime,
            "strength":  strength,
            "updated":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "bull_score": details.get("bull_score", 0),
            "bear_score": details.get("bear_score", 0),
        }
        save_regime(regime_data)
        briefing = build_briefing(regime, strength, details)
        await bot.send_message(chat_id=CHAT_ID, text=briefing)
        log.info("Regime: %s (%s)" % (regime, strength))
    except Exception as e:
        log.error("Initial analysis error: %s" % e)

    last_run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        now = datetime.now(timezone.utc)

        # Run every day at 07:00 UTC
        if now.hour == 7 and now.strftime("%Y-%m-%d") != last_run_date:
            try:
                log.info("Running daily regime analysis...")
                regime, strength, details = analyse_regime()
                regime_data = {
                    "regime":    regime,
                    "strength":  strength,
                    "updated":   now.strftime("%Y-%m-%d %H:%M"),
                    "bull_score": details.get("bull_score", 0),
                    "bear_score": details.get("bear_score", 0),
                }
                save_regime(regime_data)
                briefing = build_briefing(regime, strength, details)
                await bot.send_message(chat_id=CHAT_ID, text=briefing)
                last_run_date = now.strftime("%Y-%m-%d")
                log.info("Regime updated: %s (%s)" % (regime, strength))
            except Exception as e:
                log.error("Regime analysis error: %s" % e)


if __name__ == "__main__":
    asyncio.run(main())
