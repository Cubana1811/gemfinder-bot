import time
import logging
import requests
import asyncio
from telegram import Bot

TELEGRAM_TOKEN = "8829673667:AAF0HtzNsyHslruE9kE5DDRiG09bWY2pv4M"
CHAT_ID = "6503316066"

SCAN_INTERVAL = 60
GEM_THRESHOLD = 60
MAX_MCAP = 1000000
MIN_LIQUIDITY = 10000
CHAINS = ["solana", "ethereum", "base", "bsc"]
DS_BASE = "https://api.dexscreener.com"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

def score_pair(pair):
    score = 0
    mcap = pair.get("marketCap") or pair.get("fdv") or 0
    vol24h = (pair.get("volume") or {}).get("h24") or 0
    price_chg = (pair.get("priceChange") or {}).get("h24") or 0
    liquidity = (pair.get("liquidity") or {}).get("usd") or 0
    txns = ((pair.get("txns") or {}).get("h24") or {})
    buys = txns.get("buys", 0)
    sells = txns.get("sells", 0)
    created = pair.get("pairCreatedAt")
    age_mins = (time.time() * 1000 - created) / 60000 if created else 9999
    vol_ratio = vol24h / mcap if mcap > 0 else 0
    if 0 < mcap < 200000: score += 30
    elif mcap < 500000: score += 20
    elif mcap < 1000000: score += 10
    if vol_ratio > 2: score += 25
    elif vol_ratio > 1: score += 18
    elif vol_ratio > 0.5: score += 10
    if price_chg > 100: score += 15
    elif price_chg > 50: score += 10
    elif price_chg > 20: score += 5
    if age_mins < 60: score += 20
    elif age_mins < 360: score += 12
    elif age_mins < 1440: score += 5
    if liquidity > 50000: score += 5
    elif liquidity > 10000: score += 3
    if (buys + sells) > 500: score += 5
    elif (buys + sells) > 100: score += 3
    return min(score, 100)

def fmt_usd(n):
    if not n: return "--"
    if n >= 1000000000: return "$%.2fB" % (n/1000000000)
    if n >= 1000000: return "$%.2fM" % (n/1000000)
    if n >= 1000: return "$%.1fK" % (n/1000)
    return "$%.0f" % n

def fmt_age(pair):
    created = pair.get("pairCreatedAt")
    if not created: return "unknown"
    mins = int((time.time() * 1000 - created) / 60000)
    if mins < 60: return "%dm" % mins
    if mins < 1440: return "%dh %dm" % (mins//60, mins%60)
    return "%dd" % (mins//1440)

def fetch_boosted():
    tokens = []
    for url in [DS_BASE+"/token-boosts/latest/v1", DS_BASE+"/token-boosts/top/v1"]:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    tokens.extend(data)
        except Exception as e:
            log.warning("fetch error: %s" % e)
    seen = set()
    unique = []
    for t in tokens:
        k = t.get("tokenAddress","")
        if k and k not in seen:
            seen.add(k)
            unique.append(t)
    return unique

def fetch_pairs(chain_id, token_address):
    try:
        r = requests.get("%s/token-pairs/v1/%s/%s" % (DS_BASE, chain_id, token_address), timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("pair error: %s" % e)
    return []

def fetch_new_pairs(chain_id):
    try:
        r = requests.get("%s/token-search/v1/search?q=&chainId=%s&sort=createdAt&order=desc&limit=20" % (DS_BASE, chain_id), timeout=10)
        if r.status_code == 200:
            return r.json().get("pairs", [])
    except Exception as e:
        log.warning("new pairs error: %s" % e)
    return []

def scan(seen_pairs):
    gems = []
    for t in fetch_boosted()[:15]:
        pairs = fetch_pairs(t["chainId"], t["tokenAddress"])
        if pairs:
            best = max(pairs, key=lambda p: (p.get("volume") or {}).get("h24") or 0)
            addr = best.get("pairAddress","")
            if addr and addr not in seen_pairs:
                s = score_pair(best)
                mcap = best.get("marketCap") or best.get("fdv") or 0
                liq = (best.get("liquidity") or {}).get("usd") or 0
                if s >= GEM_THRESHOLD and (mcap == 0 or mcap <= MAX_MCAP) and liq >= MIN_LIQUIDITY:
                    best["_score"] = s
                    gems.append(best)
                seen_pairs.add(addr)
        time.sleep(0.3)
    for chain in CHAINS:
        for pair in fetch_new_pairs(chain):
            addr = pair.get("pairAddress","")
            if addr and addr not in seen_pairs:
                s = score_pair(pair)
                mcap = pair.get("marketCap") or pair.get("fdv") or 0
                liq = (pair.get("liquidity") or {}).get("usd") or 0
                if s >= GEM_THRESHOLD and (mcap == 0 or mcap <= MAX_MCAP) and liq >= MIN_LIQUIDITY:
                    pair["_score"] = s
                    gems.append(pair)
                seen_pairs.add(addr)
    gems.sort(key=lambda p: p["_score"], reverse=True)
    return gems

def build_msg(pair):
    score = pair["_score"]
    chain_id = pair.get("chainId", "unknown")
    symbol = (pair.get("baseToken") or {}).get("symbol", "???").upper()
    name = (pair.get("baseToken") or {}).get("name", "")
    mcap = pair.get("marketCap") or pair.get("fdv") or 0
    vol = (pair.get("volume") or {}).get("h24") or 0
    chg = (pair.get("priceChange") or {}).get("h24") or 0
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    buys = ((pair.get("txns") or {}).get("h24") or {}).get("buys", 0)
    sells = ((pair.get("txns") or {}).get("h24") or {}).get("sells", 0)
    addr = pair.get("pairAddress","")
    url = pair.get("url") or "https://dexscreener.com/%s/%s" % (chain_id, addr)
    age = fmt_age(pair)
    bar = "#"*round(score/10) + "-"*(10-round(score/10))
    label = "STRONG BUY" if score >= 80 else "GEM ALERT" if score >= 70 else "WATCH THIS"
    arrow = "UP" if chg > 0 else "DOWN"
    return (
        "%s\n"
        "====================\n"
        "$ %s %s\n"
        "Chain: %s\n\n"
        "Gem Score: %d/100\n"
        "[%s]\n\n"
        "MCap:      %s\n"
        "Volume:    %s\n"
        "Liquidity: %s\n"
        "24h Change: %s %.1f%%\n"
        "Age: %s\n"
        "Buys/Sells: %d/%d\n\n"
        "%s\n"
        "====================\n"
        "Not financial advice - DYOR"
    ) % (label, symbol, name, chain_id.upper(), score, bar,
         fmt_usd(mcap), fmt_usd(vol), fmt_usd(liq), arrow, chg,
         age, buys, sells, url)

async def main():
    log.info("GemFinder Bot starting...")
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="GemFinder Bot is online!\nScanning Solana, Ethereum, Base, BSC\nWill alert when gems are found!")
    seen_pairs = set()
    scan_count = 0
    while True:
        scan_count += 1
        log.info("Scan #%d started..." % scan_count)
        try:
            gems = scan(seen_pairs)
            log.info("Found %d gems" % len(gems))
            for gem in gems:
                msg = build_msg(gem)
                try:
                    await bot.send_message(chat_id=CHAT_ID, text=msg, disable_web_page_preview=True)
                    log.info("Sent alert for %s score=%d" % ((gem.get("baseToken") or {}).get("symbol","???"), gem["_score"]))
                    await asyncio.sleep(1)
                except Exception as e:
                    log.error("Send error: %s" % e)
        except Exception as e:
            log.error("Scan error: %s" % e)
        log.info("Next scan in %ds..." % SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
