"""
News Sentiment Bot — scans top crypto news RSS feeds every 15 minutes,
detects strongly bullish or bearish headlines for major coins, and
sends a Telegram alert before the market reacts.

Sources: CoinDesk, CoinTelegraph, Decrypt, CryptoSlate, Bitcoin Magazine
No API key required — uses public RSS feeds.
"""

import os
import json
import time
import logging
import requests
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from telegram import Bot

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID         = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")
SCAN_INTERVAL   = 900       # 15 minutes
SEEN_FILE       = "seen_news.json"
MAX_SEEN        = 500       # max headlines to remember

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── News sources (public RSS feeds) ──────────────────────────────────────────

RSS_FEEDS = [
    ("CoinDesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph",   "https://cointelegraph.com/rss"),
    ("Decrypt",         "https://decrypt.co/feed"),
    ("CryptoSlate",     "https://cryptoslate.com/feed/"),
    ("Bitcoin Magazine","https://bitcoinmagazine.com/feed"),
]

# ── Coin detection ────────────────────────────────────────────────────────────

COINS = {
    "BTC":  ["bitcoin", "btc"],
    "ETH":  ["ethereum", "eth", "ether"],
    "SOL":  ["solana", "sol"],
    "XRP":  ["xrp", "ripple"],
    "BNB":  ["bnb", "binance coin"],
    "ADA":  ["cardano", "ada"],
    "AVAX": ["avalanche", "avax"],
    "DOGE": ["dogecoin", "doge"],
    "LINK": ["chainlink", "link"],
    "DOT":  ["polkadot", "dot"],
    "MATIC":["polygon", "matic"],
    "NEAR": ["near protocol", "near"],
    "OP":   ["optimism", " op "],
    "ARB":  ["arbitrum", "arb"],
    "INJ":  ["injective", "inj"],
    "AAVE": ["aave"],
    "UNI":  ["uniswap", "uni"],
    "LTC":  ["litecoin", "ltc"],
    "ATOM": ["cosmos", "atom"],
    "APT":  ["aptos", "apt"],
}

# ── Sentiment keywords ────────────────────────────────────────────────────────

BULLISH_STRONG = [
    "all-time high", "ath", "record high", "new high", "surge",
    "institutional adoption", "etf approved", "etf approval",
    "sec approves", "major partnership", "mass adoption",
    "breakout", "short squeeze", "massive rally", "parabolic",
    "blackrock", "fidelity", "microstrategy buys",
]

BULLISH_MILD = [
    "rally", "gains", "rises", "bullish", "upgrade", "partnership",
    "launch", "adoption", "approved", "investment", "buys",
    "accumulation", "positive", "growth", "milestone",
    "listing", "integration", "support", "recovery",
]

BEARISH_STRONG = [
    "hack", "hacked", "exploit", "stolen", "fraud", "scam",
    "sec sues", "sec charges", "ban", "banned", "crash",
    "collapse", "bankrupt", "insolvency", "rug pull",
    "emergency shutdown", "critical vulnerability", "attack",
    "money laundering", "arrest", "indicted",
]

BEARISH_MILD = [
    "falls", "drops", "bearish", "warning", "concern", "risk",
    "regulation", "lawsuit", "investigation", "sell-off",
    "decline", "loss", "dump", "correction", "weakness",
    "delisting", "restrict", "probe", "fine",
]

# ── Seen headlines store ──────────────────────────────────────────────────────

def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(seen):
    items = list(seen)[-MAX_SEEN:]   # keep only last MAX_SEEN
    with open(SEEN_FILE, "w") as f:
        json.dump(items, f)

# ── RSS parser ────────────────────────────────────────────────────────────────

def fetch_headlines(source_name, url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        headlines = []
        for item in items[:20]:   # latest 20 articles
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = item.findtext("description", "").strip()
            if title:
                headlines.append({
                    "source": source_name,
                    "title":  title,
                    "link":   link,
                    "text":   (title + " " + desc).lower(),
                })
        return headlines
    except Exception as e:
        log.warning("RSS fetch error %s: %s" % (source_name, e))
        return []

# ── Sentiment scorer ──────────────────────────────────────────────────────────

def score_headline(text):
    """
    Returns (sentiment, strength, score) where:
    sentiment = 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    strength  = 'STRONG' | 'MILD'
    score     = numeric score
    """
    bull_score = 0
    bear_score = 0

    for kw in BULLISH_STRONG:
        if kw in text:
            bull_score += 3
    for kw in BULLISH_MILD:
        if kw in text:
            bull_score += 1
    for kw in BEARISH_STRONG:
        if kw in text:
            bear_score += 3
    for kw in BEARISH_MILD:
        if kw in text:
            bear_score += 1

    if bull_score == 0 and bear_score == 0:
        return "NEUTRAL", "NONE", 0

    if bull_score > bear_score:
        strength = "STRONG" if bull_score >= 3 else "MILD"
        return "BULLISH", strength, bull_score
    elif bear_score > bull_score:
        strength = "STRONG" if bear_score >= 3 else "MILD"
        return "BEARISH", strength, bear_score
    return "NEUTRAL", "NONE", 0

def detect_coins(text):
    """Return list of coin tickers mentioned in the text."""
    found = []
    for ticker, keywords in COINS.items():
        for kw in keywords:
            if kw in text:
                found.append(ticker)
                break
    return found

# ── Alert builder ─────────────────────────────────────────────────────────────

def build_alert(headline, sentiment, strength, coins):
    icon = "BULLISH NEWS" if sentiment == "BULLISH" else "BEARISH NEWS"
    impact = "HIGH IMPACT" if strength == "STRONG" else "MODERATE"
    coins_str = ", ".join(coins) if coins else "CRYPTO MARKET"

    action = ""
    if sentiment == "BULLISH" and strength == "STRONG":
        action = (
            "\nACTION: Watch for LONG setups on %s.\n"
            "Price may move UP before next signal scan." % coins_str
        )
    elif sentiment == "BEARISH" and strength == "STRONG":
        action = (
            "\nACTION: Watch for SHORT setups on %s.\n"
            "Price may move DOWN before next signal scan." % coins_str
        )
    elif sentiment == "BULLISH":
        action = "\nWatch %s for bullish momentum." % coins_str
    elif sentiment == "BEARISH":
        action = "\nWatch %s for bearish pressure." % coins_str

    return (
        "%s | %s\n"
        "\n"
        "Coins:   %s\n"
        "Source:  %s\n"
        "Impact:  %s\n"
        "\n"
        "\"%s\"\n"
        "%s\n"
        "\n"
        "Time: %s UTC"
    ) % (
        icon, impact,
        coins_str,
        headline["source"],
        impact,
        headline["title"],
        action,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    log.info("News Sentiment Bot starting...")
    bot  = Bot(token=TELEGRAM_TOKEN)
    seen = load_seen()

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "News Sentiment Bot Online!\n\n"
            "Scanning 5 crypto news sources every 15 minutes:\n"
            "  - CoinDesk\n"
            "  - CoinTelegraph\n"
            "  - Decrypt\n"
            "  - CryptoSlate\n"
            "  - Bitcoin Magazine\n\n"
            "I will alert you when STRONG bullish or bearish\n"
            "news breaks for any major coin — before the\n"
            "market fully reacts.\n\n"
            "Tracking 20 coins including BTC, ETH, SOL,\n"
            "XRP, BNB, ADA, AVAX, DOGE and more."
        )
    )

    while True:
        log.info("Scanning news feeds...")
        alerts_sent = 0

        for source_name, url in RSS_FEEDS:
            headlines = fetch_headlines(source_name, url)
            time.sleep(1)

            for h in headlines:
                # Skip if already seen
                uid = "%s|%s" % (source_name, h["title"][:80])
                if uid in seen:
                    continue

                seen.add(uid)

                sentiment, strength, score = score_headline(h["text"])

                # Only alert on STRONG signals — mild news is noise
                if strength != "STRONG":
                    continue

                coins = detect_coins(h["text"])

                # Must mention at least one tracked coin
                if not coins:
                    continue

                try:
                    msg = build_alert(h, sentiment, strength, coins)
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        disable_web_page_preview=True,
                    )
                    alerts_sent += 1
                    log.info("News alert: %s | %s | %s" % (
                        sentiment, ", ".join(coins), h["title"][:60]))
                    await asyncio.sleep(2)
                except Exception as e:
                    log.error("Alert send error: %s" % e)

        save_seen(seen)
        log.info("News scan done. %d alerts sent." % alerts_sent)
        await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
