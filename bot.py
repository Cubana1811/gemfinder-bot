import os
import time
import logging
import requests
import asyncio
from telegram import Bot
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID          = os.environ.get("CHAT_ID",        "YOUR_CHAT_ID_HERE")

SCAN_INTERVAL    = 90          # seconds between scans
GEM_THRESHOLD    = 72          # minimum gem score (0-100)
MAX_MCAP         = 2_000_000   # max $2M mcap
MIN_LIQUIDITY    = 15_000      # min $15K liquidity
MIN_HOLDERS      = 50          # min holder proxy
SIGNAL_COOLDOWN  = 3600        # 1hr cooldown per token

DS_BASE          = "https://api.dexscreener.com"
HL_API           = "https://api.hyperliquid.xyz/info"
FEAR_GREED_URL   = "https://api.alternative.me/fng/?limit=1"
BTC_TICKER_URL   = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT"
RUGCHECK_BASE    = "https://api.rugcheck.xyz/v1"

CHAINS = ["solana", "ethereum", "base", "bsc", "hyperevm"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# SAFE HTTP
# ════════════════════════════════════════════════════════════════════════════

def get(url, timeout=10, json_body=None):
    try:
        if json_body:
            r = requests.post(url, json=json_body, timeout=timeout,
                              headers={"Content-Type": "application/json"})
        else:
            r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("HTTP error %s: %s" % (url[:60], e))
    return None

# ════════════════════════════════════════════════════════════════════════════
# MARKET CONTEXT
# ════════════════════════════════════════════════════════════════════════════

def fetch_market_context():
    ctx = {"fear_greed": 50, "btc_chg": 0.0, "btc_price": 0.0}
    fg = get(FEAR_GREED_URL)
    if fg and fg.get("data"):
        ctx["fear_greed"] = int(fg["data"][0].get("value", 50))
    btc = get(BTC_TICKER_URL)
    if btc:
        ctx["btc_chg"]   = float(btc.get("priceChangePercent", 0))
        ctx["btc_price"] = float(btc.get("lastPrice", 0))
    return ctx

# ════════════════════════════════════════════════════════════════════════════
# DEXSCREENER
# ════════════════════════════════════════════════════════════════════════════

def fetch_boosted_tokens():
    tokens = []
    for ep in ["/token-boosts/latest/v1", "/token-boosts/top/v1"]:
        data = get(DS_BASE + ep)
        if isinstance(data, list):
            tokens.extend(data)
    seen, out = set(), []
    for t in tokens:
        k = t.get("tokenAddress", "")
        if k and k not in seen:
            seen.add(k); out.append(t)
    return out

def fetch_new_pairs_chain(chain_id):
    data = get("%s/token-search/v1/search?q=&chainId=%s&sort=createdAt&order=desc&limit=25" % (DS_BASE, chain_id))
    return (data or {}).get("pairs", [])

def fetch_token_pairs(chain_id, token_address):
    data = get("%s/token-pairs/v1/%s/%s" % (DS_BASE, chain_id, token_address))
    return data if isinstance(data, list) else []

# ════════════════════════════════════════════════════════════════════════════
# HYPERLIQUID / HYPEREVM
# ════════════════════════════════════════════════════════════════════════════

def fetch_hl_spot_tokens():
    data = get(HL_API, json_body={"type": "spotMetaAndAssetCtxs"})
    if not data or len(data) < 2:
        return []
    tokens  = data[0].get("tokens", [])
    pairs   = data[0].get("universe", [])
    ctxs    = data[1] if isinstance(data[1], list) else []

    results = []
    for i, pair in enumerate(pairs):
        ctx = ctxs[i] if i < len(ctxs) else {}
        mark_px   = float(ctx.get("markPx", 0) or 0)
        prev_px   = float(ctx.get("prevDayPx", 0) or 0)
        vol_24h   = float(ctx.get("dayNtlVlm", 0) or 0)
        if mark_px == 0 or vol_24h < 5000:
            continue
        chg_24h = (mark_px - prev_px) / prev_px * 100 if prev_px > 0 else 0
        token_idxs = pair.get("tokens", [])
        base_token = next((t for t in tokens if t.get("index") == token_idxs[0]), {}) if token_idxs else {}
        name = base_token.get("name", "???")
        results.append({
            "name":       name,
            "symbol":     name,
            "chain":      "hyperevm",
            "mark_px":    mark_px,
            "prev_px":    prev_px,
            "vol_24h":    vol_24h,
            "chg_24h":    chg_24h,
            "pair_index": i,
            "source":     "hyperliquid",
        })
    return results

def fetch_hl_token_details(token_id):
    return get(HL_API, json_body={"type": "tokenDetails", "tokenId": token_id})

# ════════════════════════════════════════════════════════════════════════════
# RUGCHECK
# ════════════════════════════════════════════════════════════════════════════

def rugcheck(token_address, chain="solana"):
    if chain != "solana":
        return None, []
    data = get("%s/tokens/%s/report/summary" % (RUGCHECK_BASE, token_address))
    if not data:
        return None, []
    risks = []
    score = 100
    for r in (data.get("risks") or []):
        name  = r.get("name", "").lower()
        level = r.get("level", "").lower()
        if level in ("danger", "critical"):
            if any(k in name for k in ("honeypot", "mint", "freeze", "blacklist", "rug")):
                return 0, ["HARD REJECT: %s" % r.get("name")]
            score -= 25
            risks.append(r.get("name", "Unknown"))
        elif level == "warn":
            score -= 10
            risks.append(r.get("name", "Warning"))
    holders = data.get("topHolders") or []
    if holders:
        top1  = holders[0].get("pct", 0)
        top10 = sum(h.get("pct", 0) for h in holders[:10])
        if top1 > 15:
            return 0, ["HARD REJECT: Top wallet %.1f%%" % top1]
        if top10 > 50:
            return 0, ["HARD REJECT: Top 10 hold %.1f%%" % top10]
        if top1 > 8:
            score -= 15; risks.append("Top wallet %.1f%%" % top1)
        if top10 > 35:
            score -= 10; risks.append("Top 10 hold %.1f%%" % top10)
    lp_locked = data.get("lpLocked", False)
    if lp_locked:
        score += 10
    return max(0, min(score, 100)), risks

# ════════════════════════════════════════════════════════════════════════════
# TECHNICAL SCORING (price-based, no candle data needed)
# ════════════════════════════════════════════════════════════════════════════

def score_momentum(pair):
    score   = 0
    signals = []

    mcap      = pair.get("marketCap") or pair.get("fdv") or 0
    vol_24h   = (pair.get("volume") or {}).get("h24") or pair.get("vol_24h") or 0
    vol_h1    = (pair.get("volume") or {}).get("h1") or 0
    vol_h6    = (pair.get("volume") or {}).get("h6") or 0
    chg_24h   = (pair.get("priceChange") or {}).get("h24") or pair.get("chg_24h") or 0
    chg_h1    = (pair.get("priceChange") or {}).get("h1") or 0
    chg_h6    = (pair.get("priceChange") or {}).get("h6") or 0
    liq       = (pair.get("liquidity") or {}).get("usd") or 0
    txns      = (pair.get("txns") or {})
    buys_h1   = (txns.get("h1") or {}).get("buys", 0)
    sells_h1  = (txns.get("h1") or {}).get("sells", 0)
    buys_h24  = (txns.get("h24") or {}).get("buys", 0)
    sells_h24 = (txns.get("h24") or {}).get("sells", 0)
    created   = pair.get("pairCreatedAt")
    age_mins  = (time.time()*1000 - created)/60000 if created else 9999

    vol_ratio = vol_24h / mcap if mcap > 0 else 0
    bs_ratio  = buys_h1 / sells_h1 if sells_h1 > 0 else buys_h1

    # Volume/MCap ratio
    if vol_ratio > 3:   score += 25; signals.append("Vol/MCap ratio %.1fx (extreme)" % vol_ratio)
    elif vol_ratio > 1.5: score += 18; signals.append("Vol/MCap ratio %.1fx (high)" % vol_ratio)
    elif vol_ratio > 0.5: score += 10

    # Buy/Sell ratio
    if bs_ratio > 4:  score += 20; signals.append("Buy/Sell ratio %.1fx (strong buyers)" % bs_ratio)
    elif bs_ratio > 2.5: score += 14; signals.append("Buy/Sell ratio %.1fx" % bs_ratio)
    elif bs_ratio > 1.5: score += 8

    # Price momentum multi-timeframe
    if chg_h1 > 30:  score += 15; signals.append("1h price +%.1f%% (strong pump)" % chg_h1)
    elif chg_h1 > 15: score += 8
    if chg_24h > 50: score += 10; signals.append("24h price +%.1f%%" % chg_24h)
    elif chg_24h > 20: score += 5
    if chg_h1 > 0 and chg_h6 > 0 and chg_24h > 0:
        score += 8; signals.append("Sustained uptrend all timeframes")

    # Volume acceleration
    if vol_h6 > 0 and vol_h1 > 0:
        h1_vs_avg = vol_h1 / (vol_h6 / 6)
        if h1_vs_avg > 4:  score += 15; signals.append("Volume acceleration %.1fx avg" % h1_vs_avg)
        elif h1_vs_avg > 2: score += 8

    # Freshness bonus
    if age_mins < 30:    score += 20; signals.append("Very new token (%dm old)" % int(age_mins))
    elif age_mins < 90:  score += 13; signals.append("New token (%dm old)" % int(age_mins))
    elif age_mins < 360: score += 6

    # Transaction activity
    total_txns = buys_h24 + sells_h24
    if total_txns > 1000: score += 8; signals.append("%d transactions 24h" % total_txns)
    elif total_txns > 300: score += 4

    # Liquidity health
    if liq > 100_000: score += 8; signals.append("Strong liquidity %s" % fmt_usd(liq))
    elif liq > 50_000: score += 5
    elif liq > 15_000: score += 2

    return min(score, 100), signals, bs_ratio, age_mins

def score_safety(pair, rug_score, rug_risks):
    score    = 50
    warnings = list(rug_risks)

    if rug_score == 0:
        return 0, warnings

    liq     = (pair.get("liquidity") or {}).get("usd") or 0
    mcap    = pair.get("marketCap") or pair.get("fdv") or 0
    chain   = pair.get("chainId", "")

    # Rugcheck result
    if rug_score >= 90: score += 30
    elif rug_score >= 70: score += 20
    elif rug_score >= 50: score += 10
    else: score -= 10

    # Liquidity/MCap ratio
    if mcap > 0 and liq > 0:
        liq_ratio = liq / mcap
        if liq_ratio > 0.3: score += 15; 
        elif liq_ratio > 0.15: score += 8
        elif liq_ratio < 0.03: score -= 15; warnings.append("Low liq/mcap ratio")

    # Chain bonus
    if chain in ("ethereum", "base"): score += 5
    elif chain == "solana": score += 3

    return max(0, min(score, 100)), warnings

def score_market_context(ctx, chg_24h):
    score   = 0
    signals = []
    fg      = ctx.get("fear_greed", 50)
    btc_chg = ctx.get("btc_chg", 0)

    if fg < 20:   score += 15; signals.append("Extreme Fear FGI=%d (buy zone)" % fg)
    elif fg < 35: score += 8;  signals.append("Fear FGI=%d" % fg)
    elif fg > 80: score -= 10; signals.append("Extreme Greed FGI=%d (caution)" % fg)
    elif fg > 65: score -= 5

    if btc_chg > 3:  score += 10; signals.append("BTC +%.1f%% (bullish macro)" % btc_chg)
    elif btc_chg > 1: score += 5
    elif btc_chg < -5: score -= 15; signals.append("BTC %.1f%% (bearish macro)" % btc_chg)
    elif btc_chg < -2: score -= 8

    if chg_24h > 0 and btc_chg > 0: score += 5

    return max(0, min(score, 50)), signals

# ════════════════════════════════════════════════════════════════════════════
# MASTER GEM ANALYZER
# ════════════════════════════════════════════════════════════════════════════

def analyze_gem(pair, ctx):
    chain   = pair.get("chainId", pair.get("chain", "unknown"))
    symbol  = (pair.get("baseToken") or {}).get("symbol", pair.get("symbol", "???")).upper()
    name    = (pair.get("baseToken") or {}).get("name", pair.get("name", ""))
    mcap    = pair.get("marketCap") or pair.get("fdv") or 0
    liq     = (pair.get("liquidity") or {}).get("usd") or 0
    vol_24h = (pair.get("volume") or {}).get("h24") or pair.get("vol_24h") or 0
    chg_24h = (pair.get("priceChange") or {}).get("h24") or pair.get("chg_24h") or 0
    price   = float((pair.get("priceUsd") or pair.get("mark_px") or 0))
    addr    = (pair.get("baseToken") or {}).get("address", pair.get("tokenAddress", ""))
    pair_addr = pair.get("pairAddress", addr)
    url     = pair.get("url") or "https://dexscreener.com/%s/%s" % (chain, pair_addr)
    created = pair.get("pairCreatedAt")
    age_mins = (time.time()*1000 - created)/60000 if created else 9999

    # Hard filters
    if mcap > MAX_MCAP and mcap > 0:   return None
    if liq < MIN_LIQUIDITY and liq > 0: return None
    if age_mins > 1440:                 return None  # max 24h old

    # Rugcheck (Solana only)
    rug_score, rug_risks = 75, []  # default for non-Solana
    if chain == "solana" and addr:
        rug_score, rug_risks = rugcheck(addr, chain)
        time.sleep(0.3)
        if rug_score == 0:
            return None

    # Score components
    mom_score, mom_signals, bs_ratio, age_m = score_momentum(pair)
    saf_score, saf_warnings                 = score_safety(pair, rug_score, rug_risks)
    ctx_score, ctx_signals                  = score_market_context(ctx, chg_24h)

    # Catapult/HyperEVM bonus
    catapult_bonus = 0
    catapult_note  = ""
    if chain == "hyperevm":
        catapult_bonus = 12
        catapult_note  = "HyperEVM/Catapult ecosystem token"

    # Weighted final score
    final_score = int(
        mom_score * 0.45 +
        saf_score * 0.30 +
        ctx_score * 0.15 +
        catapult_bonus
    )
    final_score = min(final_score, 100)

    if final_score < GEM_THRESHOLD:
        return None

    # Tier
    if final_score >= 88:   tier = "S-TIER"
    elif final_score >= 80: tier = "A-TIER"
    elif final_score >= 72: tier = "B-TIER"
    else:                   tier = "WATCH"

    all_signals = mom_signals[:5] + ctx_signals[:2]
    all_warnings = saf_warnings[:3]

    return {
        "symbol":        symbol,
        "name":          name,
        "chain":         chain,
        "mcap":          mcap,
        "liq":           liq,
        "vol_24h":       vol_24h,
        "chg_24h":       chg_24h,
        "price":         price,
        "age_mins":      age_m,
        "bs_ratio":      bs_ratio,
        "rug_score":     rug_score,
        "mom_score":     mom_score,
        "saf_score":     saf_score,
        "ctx_score":     ctx_score,
        "final_score":   final_score,
        "tier":          tier,
        "signals":       all_signals,
        "warnings":      all_warnings,
        "catapult_note": catapult_note,
        "pair_addr":     pair_addr,
        "url":           url,
        "fear_greed":    ctx.get("fear_greed", 50),
        "btc_chg":       ctx.get("btc_chg", 0),
        "source":        pair.get("source", "dexscreener"),
    }

# ════════════════════════════════════════════════════════════════════════════
# MESSAGE BUILDER
# ════════════════════════════════════════════════════════════════════════════

def fmt_usd(n):
    if not n or n == 0: return "--"
    if n >= 1e9:  return "$%.2fB" % (n/1e9)
    if n >= 1e6:  return "$%.2fM" % (n/1e6)
    if n >= 1e3:  return "$%.1fK" % (n/1e3)
    return "$%.0f" % n

def fmt_age(mins):
    if mins >= 1440: return "%dd" % int(mins/1440)
    if mins >= 60:   return "%dh %dm" % (int(mins/60), int(mins%60))
    return "%dm" % int(mins)

def fg_label(v):
    if v < 20: return "Extreme Fear"
    if v < 40: return "Fear"
    if v < 60: return "Neutral"
    if v < 80: return "Greed"
    return "Extreme Greed"

def chain_label(c):
    return {"solana":"◎ Solana","ethereum":"Ξ Ethereum","base":"🔵 Base",
            "bsc":"🟡 BSC","hyperevm":"⚡ HyperEVM/Catapult"}.get(c, c.upper())

def build_gem_message(g):
    tier_icon = {"S-TIER":"[S]","A-TIER":"[A]","B-TIER":"[B]","WATCH":"[W]"}.get(g["tier"],"[?]")
    score_bar = "#" * round(g["final_score"]/10) + "-" * (10 - round(g["final_score"]/10))
    signals_text  = "\n".join(["  [+] " + s for s in g["signals"]])
    warnings_text = "\n".join(["  [!] " + w for w in g["warnings"]]) if g["warnings"] else "  None"

    chg_arrow = "UP" if g["chg_24h"] >= 0 else "DOWN"
    btc_arrow = "UP" if g["btc_chg"] >= 0 else "DOWN"

    catapult_line = "\n  [*] %s" % g["catapult_note"] if g["catapult_note"] else ""

    return (
        "%s GEM ALERT - %s\n"
        "==================================================\n"
        "Token:   $%s (%s)\n"
        "Chain:   %s\n"
        "Age:     %s\n"
        "\n"
        "=== GEM SCORE ===\n"
        "Overall:  %d/100  [%s]\n"
        "Tier:     %s\n"
        "Momentum: %d/100\n"
        "Safety:   %d/100\n"
        "Context:  %d/50\n"
        "Rugcheck: %d/100\n"
        "\n"
        "=== MARKET DATA ===\n"
        "Price:      $%s\n"
        "Market Cap: %s\n"
        "Liquidity:  %s\n"
        "Volume 24h: %s\n"
        "24h Change: %s %+.1f%%\n"
        "Buy/Sell:   %.1fx ratio\n"
        "\n"
        "=== WHY THIS GEM ===\n"
        "%s%s\n"
        "\n"
        "=== SAFETY NOTES ===\n"
        "%s\n"
        "\n"
        "=== MACRO CONTEXT ===\n"
        "Fear/Greed: %d (%s)\n"
        "BTC 24h:    %s %+.1f%%\n"
        "\n"
        "=== RISK MANAGEMENT ===\n"
        "- Only invest what you can afford to lose\n"
        "- Take partial profits early (50%% at 2-3x)\n"
        "- Set a mental stop loss\n"
        "- Never go all-in on one gem\n"
        "\n"
        "Chart: %s\n"
        "Signal: %s UTC\n"
        "==================================================\n"
        "Not financial advice - DYOR. Memecoins = HIGH RISK"
    ) % (
        tier_icon, g["tier"],
        g["symbol"], g["name"],
        chain_label(g["chain"]),
        fmt_age(g["age_mins"]),
        g["final_score"], score_bar,
        g["tier"],
        g["mom_score"], g["saf_score"],
        g["ctx_score"], g["rug_score"],
        ("%.8f" % g["price"]).rstrip("0").rstrip(".") if g["price"] < 0.01 else "%.4f" % g["price"],
        fmt_usd(g["mcap"]),
        fmt_usd(g["liq"]),
        fmt_usd(g["vol_24h"]),
        chg_arrow, g["chg_24h"],
        g["bs_ratio"],
        signals_text, catapult_line,
        warnings_text,
        g["fear_greed"], fg_label(g["fear_greed"]),
        btc_arrow, g["btc_chg"],
        g["url"],
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

# ════════════════════════════════════════════════════════════════════════════
# SCANNER
# ════════════════════════════════════════════════════════════════════════════

def run_scan(seen_pairs, ctx):
    gems = []

    # 1. DexScreener boosted tokens
    boosted = fetch_boosted_tokens()
    for t in boosted[:20]:
        pairs = fetch_token_pairs(t.get("chainId",""), t.get("tokenAddress",""))
        if pairs:
            best = max(pairs, key=lambda p: (p.get("volume") or {}).get("h24") or 0)
            addr = best.get("pairAddress","")
            if addr and addr not in seen_pairs:
                seen_pairs.add(addr)
                result = analyze_gem(best, ctx)
                if result: gems.append(result)
        time.sleep(0.4)

    # 2. New pairs on each EVM/Solana chain
    for chain in ["solana", "ethereum", "base", "bsc"]:
        pairs = fetch_new_pairs_chain(chain)
        for pair in pairs:
            addr = pair.get("pairAddress","")
            if addr and addr not in seen_pairs:
                seen_pairs.add(addr)
                result = analyze_gem(pair, ctx)
                if result: gems.append(result)
        time.sleep(0.5)

    # 3. HyperEVM / Catapult tokens
    hl_tokens = fetch_hl_spot_tokens()
    for ht in hl_tokens:
        key = "hl_%s" % ht.get("name","")
        if key not in seen_pairs:
            seen_pairs.add(key)
            result = analyze_gem(ht, ctx)
            if result: gems.append(result)
    time.sleep(0.5)

    # Sort by score
    gems.sort(key=lambda g: g["final_score"], reverse=True)
    return gems

# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

async def main():
    log.info("Advanced GemFinder Bot v2 starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Advanced GemFinder Bot v2 Online!\n\n"
            "Scanning 5 chains simultaneously:\n"
            "  Solana  Ethereum  Base  BSC  HyperEVM\n\n"
            "Data sources:\n"
            "  DexScreener (boosted + new pairs)\n"
            "  Hyperliquid API (HyperEVM/Catapult)\n"
            "  Rugcheck (Solana safety)\n"
            "  Fear & Greed Index\n"
            "  BTC macro correlation\n\n"
            "Gem scoring:\n"
            "  Momentum (45%%) - vol, buys, price\n"
            "  Safety   (30%%) - rugcheck, liquidity\n"
            "  Context  (15%%) - BTC, fear/greed\n"
            "  Catapult (10%%) - HyperEVM bonus\n\n"
            "Min Score:     %d/100\n"
            "Max MCap:      %s\n"
            "Min Liquidity: %s\n"
            "Scan Interval: %ds\n\n"
            "S-TIER = score 88+\n"
            "A-TIER = score 80-87\n"
            "B-TIER = score 72-79\n\n"
            "Not financial advice - DYOR!"
        ) % (GEM_THRESHOLD, fmt_usd(MAX_MCAP), fmt_usd(MIN_LIQUIDITY), SCAN_INTERVAL)
    )

    seen_pairs  = set()
    signal_times = {}
    scan_count  = 0

    while True:
        scan_count += 1
        log.info("Scan #%d starting..." % scan_count)

        try:
            ctx = fetch_market_context()
            log.info("Market: FGI=%d BTC=%+.1f%%" % (ctx["fear_greed"], ctx["btc_chg"]))

            gems = run_scan(seen_pairs, ctx)
            log.info("Scan #%d done. Found %d gems." % (scan_count, len(gems)))

            for gem in gems:
                key = gem["pair_addr"]
                last_sent = signal_times.get(key, 0)
                if time.time() - last_sent < SIGNAL_COOLDOWN:
                    continue

                msg = build_gem_message(gem)
                try:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        disable_web_page_preview=True
                    )
                    signal_times[key] = time.time()
                    log.info("Sent: $%s %s score=%d chain=%s" % (
                        gem["symbol"], gem["tier"],
                        gem["final_score"], gem["chain"]
                    ))
                    await asyncio.sleep(2)
                except Exception as e:
                    log.error("Send error: %s" % e)

        except Exception as e:
            log.error("Scan error: %s" % e)

        log.info("Next scan in %ds..." % SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
