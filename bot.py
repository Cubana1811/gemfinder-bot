import time
import logging
import requests
import asyncio
from telegram import Bot

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8829673667:AAHA12D1jwgyKZFz6AcuBrwfQHBMpwIaZfQ"
CHAT_ID = "6503316066E"

SCAN_INTERVAL = 120
MIN_OPPORTUNITY_SCORE = 75
MAX_RISK_SCORE = 40
CHAINS = ["solana", "ethereum", "base", "bsc"]
DS_BASE = "https://api.dexscreener.com"
RUGCHECK_BASE = "https://api.rugcheck.xyz/v1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Rugcheck Safety Analysis ──────────────────────────────────────────────────
def check_rugcheck(token_address, chain="solana"):
    try:
        r = requests.get("%s/tokens/%s/report/summary" % (RUGCHECK_BASE, token_address), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("Rugcheck error: %s" % e)
    return None

def get_safety_score(pair, rug_data):
    score = 100
    risks = []
    warnings = []

    # Liquidity checks
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    if liq < 20000:
        return 0, ["REJECT: Liquidity below $20K"]
    elif liq < 50000:
        score -= 20
        warnings.append("Low liquidity ($%sK)" % round(liq/1000, 1))
    elif liq >= 100000:
        score += 5

    # Holder concentration
    if rug_data:
        top_holders = rug_data.get("topHolders") or []
        if top_holders:
            top1 = top_holders[0].get("pct", 0) if top_holders else 0
            top10 = sum(h.get("pct", 0) for h in top_holders[:10])
            if top1 > 10:
                return 0, ["REJECT: Top wallet holds %.1f%%" % top1]
            elif top1 > 5:
                score -= 15
                warnings.append("Top wallet %.1f%%" % top1)
            if top10 > 40:
                return 0, ["REJECT: Top 10 holders own %.1f%%" % top10]
            elif top10 > 25:
                score -= 10
                warnings.append("Top 10 own %.1f%%" % top10)

        # Mint/freeze checks
        risks_data = rug_data.get("risks") or []
        for risk in risks_data:
            name = risk.get("name", "").lower()
            level = risk.get("level", "").lower()
            if "mint" in name or "freeze" in name or "honeypot" in name:
                if level in ["danger", "critical"]:
                    return 0, ["REJECT: %s detected" % risk.get("name")]
                else:
                    score -= 20
                    warnings.append(risk.get("name","Unknown risk"))

    return max(0, min(score, 100)), warnings

# ── Momentum Analysis ─────────────────────────────────────────────────────────
def get_momentum_score(pair):
    score = 0
    signals = []

    vol_h1  = (pair.get("volume") or {}).get("h1") or 0
    vol_h6  = (pair.get("volume") or {}).get("h6") or 0
    vol_h24 = (pair.get("volume") or {}).get("h24") or 0
    mcap    = pair.get("marketCap") or pair.get("fdv") or 0
    liq     = (pair.get("liquidity") or {}).get("usd") or 0

    chg_h1  = (pair.get("priceChange") or {}).get("h1") or 0
    chg_h6  = (pair.get("priceChange") or {}).get("h6") or 0
    chg_h24 = (pair.get("priceChange") or {}).get("h24") or 0

    txns    = (pair.get("txns") or {})
    buys_h1 = (txns.get("h1") or {}).get("buys", 0)
    sells_h1 = (txns.get("h1") or {}).get("sells", 0)
    buys_h24 = (txns.get("h24") or {}).get("buys", 0)
    sells_h24 = (txns.get("h24") or {}).get("sells", 0)

    # Volume/MCap ratio
    vol_ratio = vol_h24 / mcap if mcap > 0 else 0
    if vol_ratio > 3:
        score += 25
        signals.append("Extreme volume (%.1fx mcap)" % vol_ratio)
    elif vol_ratio > 1.5:
        score += 18
        signals.append("High volume (%.1fx mcap)" % vol_ratio)
    elif vol_ratio > 0.5:
        score += 10

    # Buy/sell ratio
    bs_ratio_h1 = buys_h1 / sells_h1 if sells_h1 > 0 else buys_h1
    bs_ratio_h24 = buys_h24 / sells_h24 if sells_h24 > 0 else buys_h24
    if bs_ratio_h1 > 3:
        score += 20
        signals.append("Strong buy pressure (%.1fx buys vs sells)" % bs_ratio_h1)
    elif bs_ratio_h1 > 2:
        score += 12
        signals.append("Good buy/sell ratio (%.1fx)" % bs_ratio_h1)

    # Price momentum
    if chg_h1 > 50:
        score += 15
        signals.append("1h price +%.0f%%" % chg_h1)
    elif chg_h1 > 20:
        score += 8
    if chg_h24 > 0 and chg_h1 > 0:
        score += 5
        signals.append("Sustained uptrend")

    # Volume acceleration (h1 vs h6 average)
    if vol_h6 > 0:
        h1_vs_avg = vol_h1 / (vol_h6 / 6) if vol_h6 > 0 else 1
        if h1_vs_avg > 3:
            score += 15
            signals.append("Volume accelerating (%.1fx avg)" % h1_vs_avg)
        elif h1_vs_avg > 1.5:
            score += 8

    return min(score, 100), signals, bs_ratio_h1

# ── Smart Money Detection ─────────────────────────────────────────────────────
def get_smart_money_score(pair):
    score = 0
    signals = []

    # Use transaction patterns as proxy for smart money
    txns = (pair.get("txns") or {})
    buys_h1 = (txns.get("h1") or {}).get("buys", 0)
    buys_h6 = (txns.get("h6") or {}).get("buys", 0)
    buys_h24 = (txns.get("h24") or {}).get("buys", 0)

    vol_h1 = (pair.get("volume") or {}).get("h1") or 0
    vol_h24 = (pair.get("volume") or {}).get("h24") or 0

    # Large average transaction size = whale interest
    avg_tx_size = vol_h1 / buys_h1 if buys_h1 > 0 else 0
    if avg_tx_size > 5000:
        score += 30
        signals.append("Large avg tx $%.0f (whale activity)" % avg_tx_size)
    elif avg_tx_size > 1000:
        score += 20
        signals.append("Medium avg tx $%.0f" % avg_tx_size)
    elif avg_tx_size > 500:
        score += 10

    # Consistent buying across timeframes
    if buys_h6 > 0 and buys_h24 > 0:
        h1_pct = buys_h1 / buys_h24 * 100 if buys_h24 > 0 else 0
        if h1_pct > 20:
            score += 20
            signals.append("Buying accelerating (%.0f%% of 24h in last 1h)" % h1_pct)
        elif h1_pct > 10:
            score += 10

    # Volume distribution
    if vol_h24 > 0:
        recent_vol_pct = vol_h1 / vol_h24 * 100
        if recent_vol_pct > 25:
            score += 20
            signals.append("Recent volume surge (%.0f%% of 24h in last 1h)" % recent_vol_pct)

    if not signals:
        signals.append("No smart money signals detected")

    return min(score, 100), signals

# ── Liquidity Quality ─────────────────────────────────────────────────────────
def get_liquidity_score(pair):
    score = 0
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    mcap = pair.get("marketCap") or pair.get("fdv") or 0

    if liq >= 100000:
        score += 40
    elif liq >= 50000:
        score += 25
    elif liq >= 20000:
        score += 10

    # Liquidity/MCap ratio (higher = safer)
    liq_ratio = liq / mcap if mcap > 0 else 0
    if liq_ratio > 0.3:
        score += 40
    elif liq_ratio > 0.15:
        score += 25
    elif liq_ratio > 0.05:
        score += 10

    # Bonus for growing liquidity
    vol_h24 = (pair.get("volume") or {}).get("h24") or 0
    if vol_h24 > liq:
        score += 20

    return min(score, 100)

# ── Risk Score ────────────────────────────────────────────────────────────────
def get_risk_score(pair, rug_data, safety_score):
    risk = 100 - safety_score

    liq = (pair.get("liquidity") or {}).get("usd") or 0
    mcap = pair.get("marketCap") or pair.get("fdv") or 0
    created = pair.get("pairCreatedAt")
    age_hours = (time.time() * 1000 - created) / 3600000 if created else 999

    # Age risk
    if age_hours < 1:
        risk += 20
    elif age_hours < 6:
        risk += 10
    elif age_hours < 24:
        risk += 5

    # Low liquidity risk
    if liq < 30000:
        risk += 15
    elif liq < 50000:
        risk += 8

    # Very small mcap risk
    if mcap > 0 and mcap < 50000:
        risk += 10

    return min(risk, 100)

# ── Conviction Tier ───────────────────────────────────────────────────────────
def get_conviction_tier(opp_score, risk_score):
    if opp_score >= 85 and risk_score <= 25:
        return "S-TIER", "INSTANT ALERT"
    elif opp_score >= 75 and risk_score <= 35:
        return "A-TIER", "HIGH CONVICTION"
    elif opp_score >= 60 and risk_score <= 40:
        return "B-TIER", "MODERATE"
    elif opp_score >= 45:
        return "C-TIER", "WEAK"
    else:
        return "REJECT", "NO ALERT"

# ── Token Age Formatter ───────────────────────────────────────────────────────
def fmt_age(pair):
    created = pair.get("pairCreatedAt")
    if not created: return "Unknown"
    mins = int((time.time() * 1000 - created) / 60000)
    if mins < 60: return "%dm" % mins
    if mins < 1440: return "%dh %dm" % (mins//60, mins%60)
    return "%dd" % (mins//1440)

def fmt_usd(n):
    if not n or n == 0: return "--"
    if n >= 1000000000: return "$%.2fB" % (n/1000000000)
    if n >= 1000000: return "$%.2fM" % (n/1000000)
    if n >= 1000: return "$%.1fK" % (n/1000)
    return "$%.0f" % n

def risk_label(score):
    if score <= 20: return "LOW RISK"
    if score <= 40: return "MODERATE RISK"
    if score <= 60: return "ELEVATED RISK"
    if score <= 80: return "HIGH RISK"
    return "EXTREME RISK"

# ── DexScreener API ───────────────────────────────────────────────────────────
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
            log.warning("Fetch error: %s" % e)
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
        log.warning("Pairs error: %s" % e)
    return []

def fetch_new_pairs(chain_id):
    try:
        url = "%s/token-search/v1/search?q=&chainId=%s&sort=createdAt&order=desc&limit=25" % (DS_BASE, chain_id)
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json().get("pairs", [])
    except Exception as e:
        log.warning("New pairs error: %s" % e)
    return []

# ── Full Analysis ─────────────────────────────────────────────────────────────
def analyze_token(pair):
    chain_id = pair.get("chainId", "")
    token_addr = (pair.get("baseToken") or {}).get("address", "")

    # Age filter — max 24h
    created = pair.get("pairCreatedAt")
    if created:
        age_hours = (time.time() * 1000 - created) / 3600000
        if age_hours > 24:
            return None

    # Liquidity filter
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    if liq < 20000:
        return None

    # Get rugcheck data for Solana tokens
    rug_data = None
    if chain_id == "solana" and token_addr:
        rug_data = check_rugcheck(token_addr)
        time.sleep(0.3)

    # Run all scoring
    safety_score, safety_warnings = get_safety_score(pair, rug_data)
    if safety_score == 0:
        return None  # Hard reject

    momentum_score, momentum_signals, bs_ratio = get_momentum_score(pair)
    smart_score, smart_signals = get_smart_money_score(pair)
    liq_score = get_liquidity_score(pair)

    # Community score (basic proxy)
    community_score = 50  # baseline

    # Weighted total opportunity score
    opp_score = int(
        safety_score    * 0.30 +
        smart_score     * 0.30 +
        momentum_score  * 0.20 +
        community_score * 0.10 +
        liq_score       * 0.10
    )

    risk_score = get_risk_score(pair, rug_data, safety_score)
    tier, tier_label = get_conviction_tier(opp_score, risk_score)

    if tier == "REJECT":
        return None

    mcap = pair.get("marketCap") or pair.get("fdv") or 0
    symbol = (pair.get("baseToken") or {}).get("symbol", "???").upper()
    name = (pair.get("baseToken") or {}).get("name", "")
    pair_addr = pair.get("pairAddress","")
    url = pair.get("url") or "https://dexscreener.com/%s/%s" % (chain_id, pair_addr)
    vol_h24 = (pair.get("volume") or {}).get("h24") or 0
    chg_h24 = (pair.get("priceChange") or {}).get("h24") or 0
    chg_h1  = (pair.get("priceChange") or {}).get("h1") or 0

    txns = (pair.get("txns") or {})
    buys  = (txns.get("h24") or {}).get("buys", 0)
    sells = (txns.get("h24") or {}).get("sells", 0)

    holders_est = buys  # proxy

    return {
        "symbol": symbol,
        "name": name,
        "chain": chain_id.upper(),
        "pair_addr": pair_addr,
        "token_addr": token_addr,
        "age": fmt_age(pair),
        "mcap": mcap,
        "liquidity": liq,
        "volume": vol_h24,
        "chg_h24": chg_h24,
        "chg_h1": chg_h1,
        "buys": buys,
        "sells": sells,
        "bs_ratio": bs_ratio,
        "holders_est": holders_est,
        "safety_score": safety_score,
        "smart_score": smart_score,
        "momentum_score": momentum_score,
        "liq_score": liq_score,
        "community_score": community_score,
        "opp_score": opp_score,
        "risk_score": risk_score,
        "risk_label": risk_label(risk_score),
        "tier": tier,
        "tier_label": tier_label,
        "url": url,
        "safety_warnings": safety_warnings,
        "momentum_signals": momentum_signals,
        "smart_signals": smart_signals,
    }

# ── Build Alert Message ───────────────────────────────────────────────────────
def build_message(t):
    tier_icon = {"S-TIER":"[S]","A-TIER":"[A]","B-TIER":"[B]","C-TIER":"[C]"}.get(t["tier"],"[?]")
    chg_arrow_h24 = "+" if t["chg_h24"] >= 0 else ""
    chg_arrow_h1  = "+" if t["chg_h1"] >= 0 else ""

    opp_bar = "#" * round(t["opp_score"]/10) + "-" * (10 - round(t["opp_score"]/10))
    risk_bar = "#" * round(t["risk_score"]/10) + "-" * (10 - round(t["risk_score"]/10))

    momentum_text = "\n".join(["  + " + s for s in t["momentum_signals"][:3]]) or "  None"
    smart_text = "\n".join(["  + " + s for s in t["smart_signals"][:2]]) or "  None"
    warning_text = "\n".join(["  ! " + w for w in t["safety_warnings"][:2]]) if t["safety_warnings"] else "  None"

    return (
        "%s %s ALERT - %s\n"
        "==================================================\n"
        "Token:     $%s (%s)\n"
        "Chain:     %s\n"
        "Age:       %s\n"
        "\n"
        "-- MARKET DATA --\n"
        "Market Cap:  %s\n"
        "Liquidity:   %s\n"
        "Volume 24h:  %s\n"
        "24h Change:  %s%.1f%%\n"
        "1h Change:   %s%.1f%%\n"
        "Buys/Sells:  %d / %d (%.1fx ratio)\n"
        "\n"
        "-- SCORES --\n"
        "Opportunity: %d/100  [%s]\n"
        "Risk:        %d/100  [%s]\n"
        "Safety:      %d/100\n"
        "Smart Money: %d/100\n"
        "Momentum:    %d/100\n"
        "Liquidity:   %d/100\n"
        "\n"
        "-- MOMENTUM SIGNALS --\n"
        "%s\n"
        "\n"
        "-- SMART MONEY --\n"
        "%s\n"
        "\n"
        "-- SAFETY NOTES --\n"
        "%s\n"
        "\n"
        "-- CONVICTION --\n"
        "Tier:      %s - %s\n"
        "Risk:      %s\n"
        "\n"
        "Chart: %s\n"
        "==================================================\n"
        "Not financial advice - DYOR. High risk asset."
    ) % (
        tier_icon, t["tier"], t["tier_label"],
        t["symbol"], t["name"],
        t["chain"],
        t["age"],
        fmt_usd(t["mcap"]),
        fmt_usd(t["liquidity"]),
        fmt_usd(t["volume"]),
        chg_arrow_h24, t["chg_h24"],
        chg_arrow_h1, t["chg_h1"],
        t["buys"], t["sells"], t["bs_ratio"],
        t["opp_score"], opp_bar,
        t["risk_score"], risk_bar,
        t["safety_score"],
        t["smart_score"],
        t["momentum_score"],
        t["liq_score"],
        momentum_text,
        smart_text,
        warning_text,
        t["tier"], t["tier_label"],
        t["risk_label"],
        t["url"]
    )

# ── Scanner ───────────────────────────────────────────────────────────────────
def scan(seen_pairs):
    results = []

    # Scan boosted tokens
    boosted = fetch_boosted()
    log.info("Analyzing %d boosted tokens..." % len(boosted[:20]))
    for t in boosted[:20]:
        pairs = fetch_pairs(t["chainId"], t["tokenAddress"])
        if pairs:
            best = max(pairs, key=lambda p: (p.get("volume") or {}).get("h24") or 0)
            addr = best.get("pairAddress","")
            if addr and addr not in seen_pairs:
                seen_pairs.add(addr)
                result = analyze_token(best)
                if result and result["opp_score"] >= MIN_OPPORTUNITY_SCORE and result["risk_score"] <= MAX_RISK_SCORE:
                    results.append(result)
        time.sleep(0.5)

    # Scan new pairs on each chain
    for chain in CHAINS:
        new_pairs = fetch_new_pairs(chain)
        for pair in new_pairs:
            addr = pair.get("pairAddress","")
            if addr and addr not in seen_pairs:
                seen_pairs.add(addr)
                result = analyze_token(pair)
                if result and result["opp_score"] >= MIN_OPPORTUNITY_SCORE and result["risk_score"] <= MAX_RISK_SCORE:
                    results.append(result)
        time.sleep(0.5)

    # Sort by opportunity score
    results.sort(key=lambda x: x["opp_score"], reverse=True)
    return results

# ── Main Loop ─────────────────────────────────────────────────────────────────
async def main():
    log.info("Advanced GemFinder Bot starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    startup_msg = (
        "Advanced GemFinder Bot Online!\n\n"
        "Scanning: Solana, Ethereum, Base, BSC\n"
        "Min Opportunity Score: %d/100\n"
        "Max Risk Score: %d/100\n"
        "Scan Interval: %ds\n\n"
        "Conviction Tiers:\n"
        "[S] S-TIER: Score 85+ Risk under 25\n"
        "[A] A-TIER: Score 75+ Risk under 35\n"
        "[B] B-TIER: Score 60+ Risk under 40\n\n"
        "Alerts will include full analysis!\n"
        "Not financial advice - DYOR"
    ) % (MIN_OPPORTUNITY_SCORE, MAX_RISK_SCORE, SCAN_INTERVAL)

    await bot.send_message(chat_id=CHAT_ID, text=startup_msg)

    seen_pairs = set()
    scan_count = 0

    while True:
        scan_count += 1
        log.info("Scan #%d starting..." % scan_count)

        try:
            gems = scan(seen_pairs)
            log.info("Scan #%d complete. Found %d qualifying gems." % (scan_count, len(gems)))

            for gem in gems:
                msg = build_message(gem)
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        disable_web_page_preview=True
                    )
                    log.info("Alert sent: $%s %s score=%d risk=%d" % (
                        gem["symbol"], gem["tier"], gem["opp_score"], gem["risk_score"]
                    ))
                    await asyncio.sleep(2)
                except Exception as e:
                    log.error("Send error: %s" % e)

            if not gems:
                log.info("No qualifying gems this scan.")

        except Exception as e:
            log.error("Scan error: %s" % e)

        log.info("Next scan in %ds..." % SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
