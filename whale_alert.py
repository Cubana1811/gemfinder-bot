"""
Whale Alert Bot — monitors Binance futures every 5 minutes for:
  1. Single trades over $1M (institutional block trades)
  2. Open interest spikes > 8% in 1 hour (whales entering positions)
  3. Extreme funding rates (market heavily crowded one side)
  4. Volume anomalies (15m volume > 5x normal)

All data from free public Binance endpoints — no API key required.
"""

import os
import json
import time
import logging
import requests
import asyncio
from datetime import datetime, timezone
from telegram import Bot

TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID             = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
BINANCE_BASE        = "https://fapi.binance.com"
SCAN_INTERVAL       = 300       # 5 minutes

WHALE_TRADE_USD     = 1_000_000  # alert on trades > $1M
OI_SPIKE_PCT        = 8.0        # alert on OI change > 8% in 1h
FUNDING_EXTREME     = 0.08       # alert on funding > 0.08% or < -0.08%
VOLUME_SPIKE_X      = 5.0        # alert on volume > 5x the 1h average

COOLDOWN_FILE       = "whale_cooldowns.json"
COOLDOWN_SECONDS    = 3600       # 1 hour cooldown per symbol per alert type

COINS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "MATICUSDT",
    "LTCUSDT", "ATOMUSDT", "DOTUSDT", "NEARUSDT", "OPUSDT",
    "ARBUSDT", "INJUSDT",  "AAVEUSDT", "UNIUSDT",  "APTUSDT",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Cooldown store ────────────────────────────────────────────────────────────

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

def is_on_cooldown(cd, key):
    return time.time() - cd.get(key, 0) < COOLDOWN_SECONDS

def set_cooldown(cd, key):
    cd[key] = time.time()

# ── Binance helpers ───────────────────────────────────────────────────────────

def safe_get(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("HTTP %s: %s" % (url[:55], e))
    return None

def fetch_agg_trades(symbol, limit=100):
    return safe_get("%s/fapi/v1/aggTrades?symbol=%s&limit=%d" % (
        BINANCE_BASE, symbol, limit)) or []

def fetch_oi_history(symbol):
    return safe_get("%s/futures/data/openInterestHist?symbol=%s&period=1h&limit=3" % (
        BINANCE_BASE, symbol)) or []

def fetch_funding(symbol):
    data = safe_get("%s/fapi/v1/fundingRate?symbol=%s&limit=1" % (BINANCE_BASE, symbol))
    if data:
        return float(data[-1].get("fundingRate", 0)) * 100
    return 0.0

def fetch_klines_15m(symbol, limit=10):
    return safe_get("%s/fapi/v1/klines?symbol=%s&interval=15m&limit=%d" % (
        BINANCE_BASE, symbol, limit)) or []

def fetch_price(symbol):
    data = safe_get("%s/fapi/v1/ticker/price?symbol=%s" % (BINANCE_BASE, symbol))
    return float(data.get("price", 0)) if data else 0.0

# ── Alert builders ────────────────────────────────────────────────────────────

def fv(n):
    if n >= 1e9: return "$%.2fB" % (n / 1e9)
    if n >= 1e6: return "$%.1fM" % (n / 1e6)
    return "$%.0fK" % (n / 1e3)

def whale_trade_alert(symbol, usd_value, price, side):
    coin = symbol.replace("USDT", "")
    side_label = "BUY" if not side else "SELL"
    implication = (
        "Large buyer absorbing supply — bullish pressure." if side_label == "BUY"
        else "Large seller dumping into bids — bearish pressure."
    )
    return (
        "WHALE TRADE DETECTED\n"
        "\n"
        "Coin:    %s/USDT\n"
        "Size:    %s in one trade\n"
        "Side:    %s\n"
        "Price:   $%.4f\n"
        "\n"
        "%s\n"
        "\n"
        "This is institutional-size money moving.\n"
        "Watch for follow-through in next 15-30 mins.\n"
        "\n"
        "Time: %s UTC"
    ) % (
        coin, fv(usd_value), side_label, price,
        implication,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def oi_spike_alert(symbol, oi_chg, price):
    coin = symbol.replace("USDT", "")
    direction = "LONG" if oi_chg > 0 else "SHORT"
    implication = (
        "New money entering LONG positions — bullish accumulation." if oi_chg > 0
        else "New money entering SHORT positions — bearish positioning."
    )
    return (
        "WHALE OI SPIKE — %s\n"
        "\n"
        "Coin:      %s/USDT\n"
        "OI Change: %+.1f%% in 1 hour\n"
        "Direction: New %s positions opened\n"
        "Price:     $%.4f\n"
        "\n"
        "%s\n"
        "\n"
        "Large OI spikes = smart money entering.\n"
        "Watch for a directional move soon.\n"
        "\n"
        "Time: %s UTC"
    ) % (
        coin,
        coin, oi_chg, direction, price,
        implication,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def funding_alert(symbol, funding, price):
    coin = symbol.replace("USDT", "")
    if funding > 0:
        side    = "LONGS paying SHORTS"
        meaning = "Market is overcrowded with longs — short squeeze risk or long liquidation cascade incoming."
        watch   = "Watch for a sudden DROP to flush overleveraged longs."
    else:
        side    = "SHORTS paying LONGS"
        meaning = "Market is overcrowded with shorts — short squeeze risk incoming."
        watch   = "Watch for a sudden PUMP to squeeze overleveraged shorts."
    return (
        "EXTREME FUNDING RATE — %s\n"
        "\n"
        "Coin:     %s/USDT\n"
        "Funding:  %+.4f%%\n"
        "Meaning:  %s\n"
        "Price:    $%.4f\n"
        "\n"
        "%s\n"
        "\n"
        "%s\n"
        "\n"
        "Time: %s UTC"
    ) % (
        coin,
        coin, funding, side, price,
        meaning, watch,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

def volume_spike_alert(symbol, spike_x, price):
    coin = symbol.replace("USDT", "")
    return (
        "VOLUME SPIKE — %s\n"
        "\n"
        "Coin:    %s/USDT\n"
        "Volume:  %.1fx above normal\n"
        "Price:   $%.4f\n"
        "\n"
        "Abnormal volume = someone big is moving.\n"
        "Could precede a breakout or breakdown.\n"
        "Wait for direction confirmation.\n"
        "\n"
        "Time: %s UTC"
    ) % (
        coin,
        coin, spike_x, price,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

# ── Scanner ───────────────────────────────────────────────────────────────────

async def scan_coin(symbol, cd, bot):
    alerts = []

    price = fetch_price(symbol)
    if price == 0:
        return

    # 1. Large single trade detection
    cd_key_trade = "%s_trade" % symbol
    if not is_on_cooldown(cd, cd_key_trade):
        trades = fetch_agg_trades(symbol, 200)
        time.sleep(0.05)
        for t in trades:
            usd_val = float(t.get("p", 0)) * float(t.get("q", 0))
            if usd_val >= WHALE_TRADE_USD:
                side = t.get("m", True)   # m=True means buyer was maker (sell)
                msg  = whale_trade_alert(symbol, usd_val, price, side)
                alerts.append(("TRADE", msg))
                set_cooldown(cd, cd_key_trade)
                log.info("Whale trade: %s %s" % (symbol, fv(usd_val)))
                break   # one alert per coin per scan

    # 2. OI spike detection
    cd_key_oi = "%s_oi" % symbol
    if not is_on_cooldown(cd, cd_key_oi):
        oi_data = fetch_oi_history(symbol)
        time.sleep(0.05)
        if len(oi_data) >= 2:
            old_oi = float(oi_data[0].get("sumOpenInterest", 1))
            new_oi = float(oi_data[-1].get("sumOpenInterest", 1))
            oi_chg = (new_oi - old_oi) / old_oi * 100 if old_oi else 0
            if abs(oi_chg) >= OI_SPIKE_PCT:
                msg = oi_spike_alert(symbol, oi_chg, price)
                alerts.append(("OI", msg))
                set_cooldown(cd, cd_key_oi)
                log.info("OI spike: %s %+.1f%%" % (symbol, oi_chg))

    # 3. Extreme funding rate
    cd_key_fund = "%s_funding" % symbol
    if not is_on_cooldown(cd, cd_key_fund):
        funding = fetch_funding(symbol)
        time.sleep(0.05)
        if abs(funding) >= FUNDING_EXTREME:
            msg = funding_alert(symbol, funding, price)
            alerts.append(("FUNDING", msg))
            set_cooldown(cd, cd_key_fund)
            log.info("Extreme funding: %s %.4f%%" % (symbol, funding))

    # 4. Volume spike (15m)
    cd_key_vol = "%s_vol" % symbol
    if not is_on_cooldown(cd, cd_key_vol):
        klines = fetch_klines_15m(symbol, 10)
        time.sleep(0.05)
        if len(klines) >= 5:
            vols     = [float(k[5]) for k in klines]
            avg_vol  = sum(vols[:-1]) / len(vols[:-1])
            last_vol = vols[-1]
            spike_x  = last_vol / avg_vol if avg_vol > 0 else 1
            if spike_x >= VOLUME_SPIKE_X:
                msg = volume_spike_alert(symbol, spike_x, price)
                alerts.append(("VOLUME", msg))
                set_cooldown(cd, cd_key_vol)
                log.info("Volume spike: %s %.1fx" % (symbol, spike_x))

    for _, msg in alerts:
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=msg,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(1.5)
        except Exception as e:
            log.error("Alert send error %s: %s" % (symbol, e))

# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    log.info("Whale Alert Bot starting...")
    bot = Bot(token=TELEGRAM_TOKEN)
    cd  = load_cooldowns()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Whale Alert Bot Online!\n\n"
            "Monitoring %d coins every 5 minutes for:\n\n"
            "  1. Single trades > $1M\n"
            "     (institutional block trades)\n\n"
            "  2. OI spikes > 8%% in 1 hour\n"
            "     (whales entering positions)\n\n"
            "  3. Extreme funding rates (>0.08%%)\n"
            "     (market heavily crowded)\n\n"
            "  4. Volume spikes > 5x normal\n"
            "     (abnormal activity detected)\n\n"
            "All alerts include what it means\n"
            "and what to watch for."
        ) % len(COINS)
    )

    scan_count = 0
    while True:
        scan_count += 1
        log.info("Whale scan #%d..." % scan_count)

        for symbol in COINS:
            await scan_coin(symbol, cd, bot)
            save_cooldowns(cd)
            await asyncio.sleep(0.3)

        log.info("Whale scan #%d done." % scan_count)
        await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
