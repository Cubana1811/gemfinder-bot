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

SCAN_INTERVAL    = 90
GEM_THRESHOLD    = 70
MAX_MCAP         = 2_000_000
MIN_LIQUIDITY    = 10_000
SIGNAL_COOLDOWN  = 3600

DS_BASE          = "https://api.dexscreener.com"
HL_API           = "https://api.hyperliquid.xyz/info"
FEAR_GREED_URL   = "https://api.alternative.me/fng/?limit=1"
BTC_URL          = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT"
RUGCHECK_BASE    = "https://api.rugcheck.xyz/v1"
BIRDEYE_BASE     = "https://public-api.birdeye.so"
PUMP_API         = "https://frontend-api.pump.fun"
SOLSCAN_BASE     = "https://pro-api.solscan.io/v2.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ════════════════════════════════════════════════════════════════════════════

def get(url, timeout=10, headers=None, json_body=None):
    try:
        if json_body:
            r = requests.post(url, json=json_body, timeout=timeout,
                              headers={"Content-Type": "application/json"})
        else:
            r = requests.get(url, timeout=timeout, headers=headers or {})
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("HTTP %s: %s" % (url[:55], e))
    return None

def fmt_usd(n):
    if not n or n == 0: return "--"
    if n >= 1e9:  return "$%.2fB" % (n/1e9)
    if n >= 1e6:  return "$%.2fM" % (n/1e6)
    if n >= 1e3:  return "$%.1fK" % (n/1e3)
    return "$%.0f" % n

def fmt_age(mins):
    if mins >= 1440: return "%dd" % int(mins/1440)
    if mins >= 60:   return "%dh%dm" % (int(mins/60), int(mins%60))
    return "%dm" % int(mins)

# ════════════════════════════════════════════════════════════════════════════
# MARKET CONTEXT
# ════════════════════════════════════════════════════════════════════════════

def fetch_market_context():
    ctx = {"fear_greed": 50, "btc_chg": 0.0, "btc_price": 0.0, "market_phase": "NEUTRAL"}
    fg = get(FEAR_GREED_URL)
    if fg and fg.get("data"):
        ctx["fear_greed"] = int(fg["data"][0].get("value", 50))
    btc = get(BTC_URL)
    if btc:
        ctx["btc_chg"]   = float(btc.get("priceChangePercent", 0))
        ctx["btc_price"] = float(btc.get("lastPrice", 0))
    fg_val = ctx["fear_greed"]
    if fg_val < 20:   ctx["market_phase"] = "EXTREME_FEAR"
    elif fg_val < 40: ctx["market_phase"] = "FEAR"
    elif fg_val < 60: ctx["market_phase"] = "NEUTRAL"
    elif fg_val < 80: ctx["market_phase"] = "GREED"
    else:             ctx["market_phase"] = "EXTREME_GREED"
    return ctx

# ════════════════════════════════════════════════════════════════════════════
# DEXSCREENER
# ════════════════════════════════════════════════════════════════════════════

def fetch_boosted():
    tokens = []
    for ep in ["/token-boosts/latest/v1", "/token-boosts/top/v1"]:
        data = get(DS_BASE + ep)
        if isinstance(data, list): tokens.extend(data)
    seen, out = set(), []
    for t in tokens:
        k = t.get("tokenAddress","")
        if k and k not in seen: seen.add(k); out.append(t)
    return out

def fetch_new_pairs(chain):
    data = get("%s/token-search/v1/search?q=&chainId=%s&sort=createdAt&order=desc&limit=30" % (DS_BASE, chain))
    return (data or {}).get("pairs", [])

def fetch_token_pairs(chain, addr):
    data = get("%s/token-pairs/v1/%s/%s" % (DS_BASE, chain, addr))
    return data if isinstance(data, list) else []

def fetch_pair_trades(chain, pair_addr):
    """Get recent trades for a pair to detect whale buys"""
    data = get("%s/token-pairs/v1/%s/%s" % (DS_BASE, chain, pair_addr))
    return data if isinstance(data, list) else []

# ════════════════════════════════════════════════════════════════════════════
# PUMP.FUN GRADUATION TRACKING
# ════════════════════════════════════════════════════════════════════════════

def fetch_pump_graduating():
    """Fetch tokens close to graduating from pump.fun bonding curve"""
    data = get("%s/coins?offset=0&limit=50&sort=market_cap&order=DESC&includeNsfw=false" % PUMP_API)
    if not isinstance(data, list): return []
    graduating = []
    for coin in data:
        mc = coin.get("usd_market_cap", 0)
        # Pump.fun graduates at ~$69K mcap
        if 50_000 <= mc <= 80_000:
            graduating.append({
                "name":     coin.get("name", "???"),
                "symbol":   coin.get("symbol", "???"),
                "mint":     coin.get("mint", ""),
                "mcap":     mc,
                "vol_24h":  coin.get("volume", 0),
                "replies":  coin.get("reply_count", 0),
                "king":     coin.get("is_currently_king", False),
                "source":   "pump.fun",
                "chain":    "solana",
                "graduating": True,
            })
    return graduating

def fetch_pump_latest():
    """Fetch newest pump.fun tokens"""
    data = get("%s/coins?offset=0&limit=50&sort=last_trade_timestamp&order=DESC&includeNsfw=false" % PUMP_API)
    if not isinstance(data, list): return []
    results = []
    for coin in data:
        mc = coin.get("usd_market_cap", 0)
        if mc > 200_000: continue  # too large
        results.append({
            "name":    coin.get("name", "???"),
            "symbol":  coin.get("symbol", "???"),
            "mint":    coin.get("mint", ""),
            "mcap":    mc,
            "vol_24h": coin.get("volume", 0),
            "replies": coin.get("reply_count", 0),
            "king":    coin.get("is_currently_king", False),
            "source":  "pump.fun",
            "chain":   "solana",
        })
    return results

# ════════════════════════════════════════════════════════════════════════════
# BIRDEYE - HOLDER ANALYSIS (Free tier, no API key)
# ════════════════════════════════════════════════════════════════════════════

def fetch_birdeye_token_overview(token_address):
    """Get token overview including holder count"""
    headers = {"X-Chain": "solana"}
    data = get(
        "%s/defi/token_overview?address=%s" % (BIRDEYE_BASE, token_address),
        headers=headers
    )
    return (data or {}).get("data", {})

def fetch_birdeye_top_traders(token_address):
    """Detect if smart/whale wallets are buying"""
    headers = {"X-Chain": "solana"}
    data = get(
        "%s/defi/v2/tokens/top_traders?address=%s&time_frame=24h&sort_type=desc&sort_by=volume&limit=10" % (
            BIRDEYE_BASE, token_address),
        headers=headers
    )
    traders = (data or {}).get("data", {}).get("items", [])
    total_buy_vol  = sum(float(t.get("volumeBuy", 0)) for t in traders)
    total_sell_vol = sum(float(t.get("volumeSell", 0)) for t in traders)
    whale_buys     = [t for t in traders if float(t.get("volumeBuy", 0)) > 5000]
    return {
        "buy_vol":    total_buy_vol,
        "sell_vol":   total_sell_vol,
        "whale_buys": len(whale_buys),
        "traders":    len(traders),
        "bs_ratio":   total_buy_vol / total_sell_vol if total_sell_vol > 0 else total_buy_vol,
    }

def fetch_birdeye_new_listings():
    """Get new token listings on Solana from Birdeye"""
    headers = {"X-Chain": "solana"}
    data = get(
        "%s/defi/v2/tokens/new_listing?limit=20&meme_platform_enabled=true" % BIRDEYE_BASE,
        headers=headers
    )
    return (data or {}).get("data", {}).get("items", [])

# ════════════════════════════════════════════════════════════════════════════
# WHALE DETECTION via DexScreener transaction data
# ════════════════════════════════════════════════════════════════════════════

def detect_whale_activity(pair):
    """
    Use available DexScreener data to infer whale activity
    Large avg tx size = whale interest
    """
    vol_h1   = (pair.get("volume") or {}).get("h1") or 0
    buys_h1  = (pair.get("txns") or {}).get("h1", {}).get("buys", 0)
    vol_h24  = (pair.get("volume") or {}).get("h24") or 0
    buys_h24 = (pair.get("txns") or {}).get("h24", {}).get("buys", 0)

    avg_tx_h1  = vol_h1  / buys_h1  if buys_h1  > 0 else 0
    avg_tx_h24 = vol_h24 / buys_h24 if buys_h24 > 0 else 0

    whale_score  = 0
    whale_signals = []

    if avg_tx_h1 > 10_000:
        whale_score += 25
        whale_signals.append("Whale avg tx $%s in last 1h" % fmt_usd(avg_tx_h1))
    elif avg_tx_h1 > 3_000:
        whale_score += 15
        whale_signals.append("Large avg tx $%s in last 1h" % fmt_usd(avg_tx_h1))
    elif avg_tx_h1 > 1_000:
        whale_score += 8

    if avg_tx_h24 > 5_000:
        whale_score += 15
        whale_signals.append("Strong 24h avg tx $%s" % fmt_usd(avg_tx_h24))
    elif avg_tx_h24 > 1_000:
        whale_score += 8

    # Volume concentration: >30% of 24h vol in last 1h = accumulation
    if vol_h24 > 0 and vol_h1 > 0:
        h1_pct = vol_h1 / vol_h24 * 100
        if h1_pct > 40:
            whale_score += 20
            whale_signals.append("Volume surging: %.0f%% of 24h vol in last 1h" % h1_pct)
        elif h1_pct > 25:
            whale_score += 10
            whale_signals.append("Volume accelerating: %.0f%% of 24h in last 1h" % h1_pct)

    return min(whale_score, 60), whale_signals

# ════════════════════════════════════════════════════════════════════════════
# INSIDER / COORDINATED WALLET DETECTION
# ════════════════════════════════════════════════════════════════════════════

def detect_insider_patterns(pair):
    """
    Detect signs of insider/coordinated activity using available data
    Red flags: very high top holder %, early concentrated buys
    """
    flags   = []
    penalty = 0

    # Very early volume with very few transactions = concentrated buying
    vol_h1   = (pair.get("volume") or {}).get("h1") or 0
    buys_h1  = (pair.get("txns") or {}).get("h1", {}).get("buys", 1)
    created  = pair.get("pairCreatedAt")
    age_mins = (time.time()*1000 - created)/60000 if created else 9999

    # If token is <30min old with <10 buys but high volume = insider
    if age_mins < 30 and buys_h1 < 8 and vol_h1 > 20_000:
        penalty += 20
        flags.append("Suspicious: high vol with few buyers (possible insider)")

    # Price change too fast too early
    chg_h1 = (pair.get("priceChange") or {}).get("h1") or 0
    if age_mins < 15 and chg_h1 > 500:
        penalty += 15
        flags.append("Extreme early pump >500%% (possible manipulation)")

    # Very low buy count relative to volume
    if buys_h1 > 0 and vol_h1 / buys_h1 > 50_000:
        penalty += 10
        flags.append("Very large avg tx size (whale concentration risk)")

    return penalty, flags

# ════════════════════════════════════════════════════════════════════════════
# RUGCHECK
# ════════════════════════════════════════════════════════════════════════════

def rugcheck(token_address, chain="solana"):
    if chain != "solana": return 75, []
    data = get("%s/tokens/%s/report/summary" % (RUGCHECK_BASE, token_address))
    if not data: return 65, ["Rugcheck unavailable"]
    score, risks = 100, []
    for r in (data.get("risks") or []):
        n = r.get("name","").lower()
        l = r.get("level","").lower()
        if l in ("danger","critical"):
            if any(k in n for k in ("honeypot","mint","freeze","blacklist","rug")):
                return 0, ["HARD REJECT: %s" % r.get("name")]
            score -= 25; risks.append(r.get("name","Risk"))
        elif l == "warn":
            score -= 8; risks.append(r.get("name","Warning"))
    holders = data.get("topHolders") or []
    if holders:
        top1  = holders[0].get("pct",0)
        top10 = sum(h.get("pct",0) for h in holders[:10])
        if top1 > 15: return 0, ["HARD REJECT: Top wallet %.1f%%" % top1]
        if top10 > 55: return 0, ["HARD REJECT: Top 10 hold %.1f%%" % top10]
        if top1 > 8:  score -= 15; risks.append("Top wallet %.1f%%" % top1)
        if top10 > 35: score -= 10; risks.append("Top 10 hold %.1f%%" % top10)
    if data.get("lpLocked"): score += 10
    return max(0, min(score,100)), risks

# ════════════════════════════════════════════════════════════════════════════
# HYPERLIQUID / HYPEREVM
# ════════════════════════════════════════════════════════════════════════════

def fetch_hl_spot():
    data = get(HL_API, json_body={"type":"spotMetaAndAssetCtxs"})
    if not data or len(data) < 2: return []
    tokens = data[0].get("tokens",[])
    pairs  = data[0].get("universe",[])
    ctxs   = data[1] if isinstance(data[1],list) else []
    results = []
    for i, pair in enumerate(pairs):
        ctx     = ctxs[i] if i < len(ctxs) else {}
        mark_px = float(ctx.get("markPx",0) or 0)
        prev_px = float(ctx.get("prevDayPx",0) or 0)
        vol_24h = float(ctx.get("dayNtlVlm",0) or 0)
        if mark_px == 0 or vol_24h < 3000: continue
        chg_24h = (mark_px - prev_px) / prev_px * 100 if prev_px > 0 else 0
        tidxs   = pair.get("tokens",[])
        base    = next((t for t in tokens if t.get("index") == tidxs[0]), {}) if tidxs else {}
        results.append({
            "name": base.get("name","???"), "symbol": base.get("name","???"),
            "chain": "hyperevm", "mark_px": mark_px, "prev_px": prev_px,
            "vol_24h": vol_24h, "chg_24h": chg_24h, "source": "hyperliquid",
        })
    return results

# ════════════════════════════════════════════════════════════════════════════
# PUMP.FUN GEM SCORER
# ════════════════════════════════════════════════════════════════════════════

def score_pump_token(coin, ctx):
    score   = 0
    signals = []
    mc      = coin.get("mcap", 0)
    vol     = coin.get("vol_24h", 0)
    replies = coin.get("replies", 0)
    king    = coin.get("king", False)
    graduating = coin.get("graduating", False)

    # Market cap range
    if 30_000 <= mc <= 80_000:
        score += 25
        signals.append("Pump.fun prime mcap range %s" % fmt_usd(mc))
    elif mc < 30_000:
        score += 15

    # Volume signal
    if vol > 0 and mc > 0:
        vr = vol / mc
        if vr > 2:   score += 25; signals.append("Vol/MCap %.1fx (explosive)" % vr)
        elif vr > 1: score += 15; signals.append("Vol/MCap %.1fx (strong)" % vr)
        elif vr > 0.5: score += 8

    # Community engagement
    if replies > 100: score += 20; signals.append("%d community replies (viral)" % replies)
    elif replies > 50: score += 12; signals.append("%d community replies (active)" % replies)
    elif replies > 20: score += 6

    # King of the hill
    if king: score += 15; signals.append("King of the Hill on Pump.fun")

    # Graduating = about to hit Raydium
    if graduating: score += 20; signals.append("GRADUATING to Raydium soon!")

    # Market context
    fg = ctx.get("fear_greed", 50)
    if fg < 30: score += 10; signals.append("Extreme Fear = buy zone")
    elif fg > 70: score -= 5

    btc_chg = ctx.get("btc_chg", 0)
    if btc_chg > 2: score += 5
    elif btc_chg < -4: score -= 10

    return min(score, 100), signals

# ════════════════════════════════════════════════════════════════════════════
# DEXSCREENER GEM SCORER
# ════════════════════════════════════════════════════════════════════════════

def score_dex_token(pair, ctx):
    score   = 0
    signals = []

    mcap     = pair.get("marketCap") or pair.get("fdv") or 0
    vol_24h  = (pair.get("volume") or {}).get("h24") or 0
    vol_h1   = (pair.get("volume") or {}).get("h1") or 0
    vol_h6   = (pair.get("volume") or {}).get("h6") or 0
    chg_24h  = (pair.get("priceChange") or {}).get("h24") or 0
    chg_h1   = (pair.get("priceChange") or {}).get("h1") or 0
    chg_h6   = (pair.get("priceChange") or {}).get("h6") or 0
    liq      = (pair.get("liquidity") or {}).get("usd") or 0
    buys_h1  = (pair.get("txns") or {}).get("h1",{}).get("buys",0)
    sells_h1 = (pair.get("txns") or {}).get("h1",{}).get("sells",0)
    buys_h24 = (pair.get("txns") or {}).get("h24",{}).get("buys",0)
    sells_h24= (pair.get("txns") or {}).get("h24",{}).get("sells",0)
    created  = pair.get("pairCreatedAt")
    age_mins = (time.time()*1000 - created)/60000 if created else 9999

    vol_ratio = vol_24h / mcap if mcap > 0 else 0
    bs_ratio  = buys_h1 / sells_h1 if sells_h1 > 0 else buys_h1

    # 1. Volume/MCap (max 25)
    if vol_ratio > 4:    score += 25; signals.append("Vol/MCap %.1fx (extreme activity)" % vol_ratio)
    elif vol_ratio > 2:  score += 18; signals.append("Vol/MCap %.1fx (high activity)" % vol_ratio)
    elif vol_ratio > 0.8: score += 10
    elif vol_ratio > 0.3: score += 5

    # 2. Buy/Sell pressure (max 20)
    if bs_ratio > 5:   score += 20; signals.append("Buy/Sell %.1fx (heavy accumulation)" % bs_ratio)
    elif bs_ratio > 3: score += 14; signals.append("Buy/Sell %.1fx (strong buying)" % bs_ratio)
    elif bs_ratio > 2: score += 8;  signals.append("Buy/Sell %.1fx (buyers winning)" % bs_ratio)
    elif bs_ratio > 1.2: score += 4

    # 3. Multi-timeframe momentum (max 18)
    if chg_h1 > 50:   score += 12; signals.append("1h +%.0f%% (strong pump)" % chg_h1)
    elif chg_h1 > 20: score += 7
    if chg_h1 > 0 and chg_h6 > 0 and chg_24h > 0:
        score += 6; signals.append("Sustained uptrend all TFs")
    elif chg_h1 > 0 and chg_24h > 0:
        score += 3

    # 4. Volume acceleration (max 15)
    if vol_h6 > 0 and vol_h1 > 0:
        accel = vol_h1 / (vol_h6/6)
        if accel > 5:   score += 15; signals.append("Volume acceleration %.1fx avg" % accel)
        elif accel > 3: score += 10; signals.append("Volume accelerating %.1fx avg" % accel)
        elif accel > 1.5: score += 5

    # 5. Token age freshness (max 20)
    if age_mins < 20:    score += 20; signals.append("Ultra fresh (%dm old)" % int(age_mins))
    elif age_mins < 60:  score += 14; signals.append("Very new (%dm old)" % int(age_mins))
    elif age_mins < 180: score += 8;  signals.append("New token (%dh old)" % int(age_mins/60))
    elif age_mins < 360: score += 4

    # 6. Liquidity quality (max 10)
    if liq > 100_000: score += 10; signals.append("Strong liquidity %s" % fmt_usd(liq))
    elif liq > 50_000: score += 7
    elif liq > 20_000: score += 4
    elif liq > 10_000: score += 2

    # 7. Transaction count (max 8)
    total_txns = buys_h24 + sells_h24
    if total_txns > 2000: score += 8; signals.append("%d txns (very high activity)" % total_txns)
    elif total_txns > 500: score += 5
    elif total_txns > 100: score += 2

    # 8. Market context (max 12)
    fg = ctx.get("fear_greed", 50)
    btc_chg = ctx.get("btc_chg", 0)
    if fg < 20:   score += 8; signals.append("Extreme Fear = gem hunting time")
    elif fg < 35: score += 4
    elif fg > 80: score -= 5
    if btc_chg > 3:  score += 4; signals.append("BTC +%.1f%% macro tailwind" % btc_chg)
    elif btc_chg < -5: score -= 8; signals.append("BTC %.1f%% macro headwind" % btc_chg)

    return min(score, 100), signals, bs_ratio, age_mins

# ════════════════════════════════════════════════════════════════════════════
# FULL ANALYSIS PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def analyze_dex_pair(pair, ctx):
    chain    = pair.get("chainId","unknown")
    symbol   = (pair.get("baseToken") or {}).get("symbol","???").upper()
    name     = (pair.get("baseToken") or {}).get("name","")
    mcap     = pair.get("marketCap") or pair.get("fdv") or 0
    liq      = (pair.get("liquidity") or {}).get("usd") or 0
    vol_24h  = (pair.get("volume") or {}).get("h24") or 0
    chg_24h  = (pair.get("priceChange") or {}).get("h24") or 0
    price    = float(pair.get("priceUsd") or 0)
    addr     = (pair.get("baseToken") or {}).get("address","")
    pair_addr = pair.get("pairAddress", addr)
    url      = pair.get("url") or "https://dexscreener.com/%s/%s" % (chain, pair_addr)
    created  = pair.get("pairCreatedAt")
    age_mins = (time.time()*1000 - created)/60000 if created else 9999

    # Hard filters
    if mcap > MAX_MCAP and mcap > 0: return None
    if liq < MIN_LIQUIDITY and liq > 0: return None
    if age_mins > 1440: return None

    # Rugcheck (Solana)
    rug_score, rug_risks = 75, []
    if chain == "solana" and addr:
        rug_score, rug_risks = rugcheck(addr, chain)
        time.sleep(0.25)
        if rug_score == 0: return None

    # Insider detection
    insider_penalty, insider_flags = detect_insider_patterns(pair)
    rug_risks.extend(insider_flags)

    # Whale detection
    whale_score, whale_signals = detect_whale_activity(pair)

    # Main scoring
    mom_score, mom_signals, bs_ratio, age_m = score_dex_token(pair, ctx)

    # Safety score
    saf_score = max(0, min(100, rug_score - insider_penalty))

    # Whale bonus
    whale_bonus = min(whale_score, 20)

    # Final weighted score
    final = int(
        mom_score  * 0.45 +
        saf_score  * 0.25 +
        whale_bonus * 0.15 +
        min(50, (ctx.get("fear_greed",50) < 35) * 10 + (ctx.get("btc_chg",0) > 2) * 5) * 0.15
    )
    final = min(final, 100)

    if final < GEM_THRESHOLD: return None

    if final >= 88:   tier = "S-TIER"
    elif final >= 80: tier = "A-TIER"
    elif final >= 72: tier = "B-TIER"
    else:             tier = "WATCH"

    all_signals  = mom_signals[:4] + whale_signals[:2]
    all_warnings = rug_risks[:3]

    # HyperEVM catapult bonus
    cat_note = "HyperEVM/Catapult ecosystem" if chain == "hyperevm" else ""

    return {
        "symbol": symbol, "name": name, "chain": chain,
        "mcap": mcap, "liq": liq, "vol_24h": vol_24h,
        "chg_24h": chg_24h, "price": price, "age_mins": age_m,
        "bs_ratio": bs_ratio, "rug_score": rug_score,
        "mom_score": mom_score, "saf_score": saf_score,
        "whale_score": whale_score, "final_score": final, "tier": tier,
        "signals": all_signals, "warnings": all_warnings,
        "cat_note": cat_note, "pair_addr": pair_addr, "url": url,
        "fear_greed": ctx.get("fear_greed",50), "btc_chg": ctx.get("btc_chg",0),
        "source": "dexscreener", "type": "gem",
    }

def analyze_pump_coin(coin, ctx):
    mc   = coin.get("mcap",0)
    vol  = coin.get("vol_24h",0)
    mint = coin.get("mint","")

    if mc > MAX_MCAP and mc > 0: return None

    score, signals = score_pump_token(coin, ctx)
    if score < GEM_THRESHOLD: return None

    if score >= 85:   tier = "S-TIER"
    elif score >= 75: tier = "A-TIER"
    else:             tier = "B-TIER"

    url = "https://pump.fun/%s" % mint if mint else "https://pump.fun"
    graduating = coin.get("graduating", False)

    return {
        "symbol": coin.get("symbol","???").upper(),
        "name": coin.get("name",""),
        "chain": "solana", "mcap": mc, "liq": 0, "vol_24h": vol,
        "chg_24h": 0, "price": 0, "age_mins": 0,
        "bs_ratio": 0, "rug_score": 70,
        "mom_score": score, "saf_score": 70,
        "whale_score": 0, "final_score": score, "tier": tier,
        "signals": signals, "warnings": [],
        "cat_note": "GRADUATING to Raydium!" if graduating else "Pump.fun token",
        "pair_addr": mint, "url": url,
        "fear_greed": ctx.get("fear_greed",50), "btc_chg": ctx.get("btc_chg",0),
        "source": "pump.fun", "type": "pump",
    }

def analyze_hl_token(ht, ctx):
    vol   = ht.get("vol_24h",0)
    chg   = ht.get("chg_24h",0)
    price = ht.get("mark_px",0)

    score   = 0
    signals = []

    # Volume signal
    if vol > 500_000: score += 25; signals.append("High HyperEVM volume %s" % fmt_usd(vol))
    elif vol > 100_000: score += 15
    elif vol > 20_000: score += 8

    # Price momentum
    if chg > 30:  score += 20; signals.append("Price +%.1f%% (strong momentum)" % chg)
    elif chg > 15: score += 12; signals.append("Price +%.1f%%" % chg)
    elif chg > 5:  score += 6
    elif chg < -20: score -= 15

    # Catapult ecosystem bonus
    score += 12; signals.append("HyperEVM/Catapult ecosystem token")

    # Market context
    fg = ctx.get("fear_greed",50)
    if fg < 30: score += 8; signals.append("Extreme Fear = opportunity")
    btc_chg = ctx.get("btc_chg",0)
    if btc_chg > 2: score += 5

    score = min(score, 100)
    if score < GEM_THRESHOLD: return None

    tier = "A-TIER" if score >= 80 else "B-TIER"

    return {
        "symbol": ht.get("symbol","???").upper(),
        "name": ht.get("name",""),
        "chain": "hyperevm", "mcap": 0, "liq": 0, "vol_24h": vol,
        "chg_24h": chg, "price": price, "age_mins": 0,
        "bs_ratio": 0, "rug_score": 80,
        "mom_score": score, "saf_score": 80,
        "whale_score": 0, "final_score": score, "tier": tier,
        "signals": signals, "warnings": [],
        "cat_note": "Catapult/HyperEVM - Hyperliquid ecosystem",
        "pair_addr": ht.get("name",""), "url": "https://app.hyperliquid.xyz/trade/%sUSDC" % ht.get("symbol",""),
        "fear_greed": ctx.get("fear_greed",50), "btc_chg": ctx.get("btc_chg",0),
        "source": "hyperliquid", "type": "hyperevm",
    }

# ════════════════════════════════════════════════════════════════════════════
# MESSAGE BUILDER
# ════════════════════════════════════════════════════════════════════════════

def build_message(g):
    tier_icon = {"S-TIER":"[S]","A-TIER":"[A]","B-TIER":"[B]","WATCH":"[W]"}.get(g["tier"],"[?]")
    score_bar = "#" * round(g["final_score"]/10) + "-" * (10-round(g["final_score"]/10))

    chain_map = {
        "solana":"Solana","ethereum":"Ethereum","base":"Base",
        "bsc":"BSC","hyperevm":"HyperEVM/Catapult"
    }
    chain_name = chain_map.get(g["chain"], g["chain"].upper())

    signals_text  = "\n".join(["  [+] " + s for s in g["signals"]]) or "  --"
    warnings_text = "\n".join(["  [!] " + w for w in g["warnings"]]) if g["warnings"] else "  None"

    source_line = ""
    if g["source"] == "pump.fun":
        source_line = "\n  [*] Source: Pump.fun"
    elif g["source"] == "hyperliquid":
        source_line = "\n  [*] Source: Hyperliquid/Catapult"

    cat_line = "\n  [*] %s" % g["cat_note"] if g["cat_note"] else ""

    fg_label = {
        "EXTREME_FEAR":"Extreme Fear","FEAR":"Fear","NEUTRAL":"Neutral",
        "GREED":"Greed","EXTREME_GREED":"Extreme Greed"
    }.get("EXTREME_FEAR" if g["fear_greed"]<20 else "FEAR" if g["fear_greed"]<40 else
          "NEUTRAL" if g["fear_greed"]<60 else "GREED" if g["fear_greed"]<80 else "EXTREME_GREED","Neutral")

    price_str = ("%.8f" % g["price"]).rstrip("0") if g["price"] < 0.001 else "%.4f" % g["price"] if g["price"] < 1 else "%.2f" % g["price"]

    return (
        "%s GEM ALERT - %s\n"
        "==================================================\n"
        "Token:    $%s (%s)\n"
        "Chain:    %s\n"
        "Age:      %s\n"
        "\n"
        "=== SCORES ===\n"
        "Overall:  %d/100  [%s]\n"
        "Tier:     %s\n"
        "Momentum: %d/100\n"
        "Safety:   %d/100\n"
        "Whale:    %d/60\n"
        "Rugcheck: %d/100\n"
        "\n"
        "=== MARKET DATA ===\n"
        "Price:      $%s\n"
        "Market Cap: %s\n"
        "Liquidity:  %s\n"
        "Volume 24h: %s\n"
        "24h Change: %+.1f%%\n"
        "Buy/Sell:   %.1fx\n"
        "\n"
        "=== SIGNALS ===\n"
        "%s%s%s\n"
        "\n"
        "=== SAFETY ===\n"
        "%s\n"
        "\n"
        "=== MACRO ===\n"
        "Fear/Greed: %d (%s)\n"
        "BTC 24h:    %+.1f%%\n"
        "\n"
        "=== RISK MANAGEMENT ===\n"
        "- Only invest what you can lose\n"
        "- Take 50%% profit at 2x\n"
        "- Take 25%% at 5x, let 25%% run\n"
        "- Set mental stop loss at -30%%\n"
        "- Never go all-in on one gem\n"
        "\n"
        "Chart: %s\n"
        "Time: %s UTC\n"
        "==================================================\n"
        "Not financial advice - DYOR!"
    ) % (
        tier_icon, g["tier"],
        g["symbol"], g["name"],
        chain_name,
        fmt_age(g["age_mins"]) if g["age_mins"] > 0 else "N/A",
        g["final_score"], score_bar, g["tier"],
        g["mom_score"], g["saf_score"],
        g["whale_score"], g["rug_score"],
        price_str,
        fmt_usd(g["mcap"]), fmt_usd(g["liq"]),
        fmt_usd(g["vol_24h"]),
        g["chg_24h"], g["bs_ratio"],
        signals_text, cat_line, source_line,
        warnings_text,
        g["fear_greed"], fg_label,
        g["btc_chg"],
        g["url"],
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )

# ════════════════════════════════════════════════════════════════════════════
# MAIN SCANNER
# ════════════════════════════════════════════════════════════════════════════

def run_scan(seen, ctx):
    gems = []

    # 1. DexScreener boosted
    for t in fetch_boosted()[:20]:
        pairs = fetch_token_pairs(t.get("chainId",""), t.get("tokenAddress",""))
        if pairs:
            best = max(pairs, key=lambda p: (p.get("volume") or {}).get("h24") or 0)
            addr = best.get("pairAddress","")
            if addr and addr not in seen:
                seen.add(addr)
                r = analyze_dex_pair(best, ctx)
                if r: gems.append(r)
        time.sleep(0.35)

    # 2. New pairs on EVM chains + Solana
    for chain in ["solana","ethereum","base","bsc"]:
        for pair in fetch_new_pairs(chain):
            addr = pair.get("pairAddress","")
            if addr and addr not in seen:
                seen.add(addr)
                r = analyze_dex_pair(pair, ctx)
                if r: gems.append(r)
        time.sleep(0.4)

    # 3. Pump.fun graduating tokens
    for coin in fetch_pump_graduating():
        key = "pump_%s" % coin.get("mint","")
        if key not in seen:
            seen.add(key)
            r = analyze_pump_coin(coin, ctx)
            if r: gems.append(r)
    time.sleep(0.3)

    # 4. Pump.fun latest (high activity)
    for coin in fetch_pump_latest():
        key = "pump_%s" % coin.get("mint","")
        if key not in seen:
            seen.add(key)
            r = analyze_pump_coin(coin, ctx)
            if r: gems.append(r)
    time.sleep(0.3)

    # 5. HyperEVM / Catapult
    for ht in fetch_hl_spot():
        key = "hl_%s" % ht.get("name","")
        if key not in seen:
            seen.add(key)
            r = analyze_hl_token(ht, ctx)
            if r: gems.append(r)
    time.sleep(0.3)

    gems.sort(key=lambda g: g["final_score"], reverse=True)
    return gems

# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

async def main():
    log.info("Ultimate GemFinder Bot v3 starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "Ultimate GemFinder Bot v3 Online!\n\n"
            "Data Sources (6 total):\n"
            "  DexScreener - boosted + new pairs\n"
            "  Pump.fun - graduating + trending\n"
            "  Hyperliquid - HyperEVM/Catapult\n"
            "  Rugcheck - safety analysis\n"
            "  Birdeye - whale detection\n"
            "  Fear & Greed + BTC macro\n\n"
            "Chains (5):\n"
            "  Solana  Ethereum  Base  BSC  HyperEVM\n\n"
            "Scoring (100pt system):\n"
            "  Momentum   45%% - vol, buys, price\n"
            "  Safety     25%% - rugcheck, liquidity\n"
            "  Whale Data 15%% - large tx detection\n"
            "  Macro      15%% - BTC, fear/greed\n\n"
            "New features:\n"
            "  Pump.fun graduation alerts\n"
            "  Whale/large buy detection\n"
            "  Insider pattern detection\n"
            "  Catapult/HyperEVM tracking\n\n"
            "Min Score: %d/100\n"
            "Scan every: %ds\n\n"
            "Not financial advice - DYOR!"
        ) % (GEM_THRESHOLD, SCAN_INTERVAL)
    )

    seen         = set()
    signal_times = {}
    scan_count   = 0

    while True:
        scan_count += 1
        log.info("Scan #%d..." % scan_count)
        try:
            ctx = fetch_market_context()
            log.info("FGI=%d BTC=%+.1f%% Phase=%s" % (
                ctx["fear_greed"], ctx["btc_chg"], ctx["market_phase"]))
            gems = run_scan(seen, ctx)
            log.info("Found %d gems" % len(gems))
            for gem in gems:
                key  = gem["pair_addr"]
                last = signal_times.get(key, 0)
                if time.time() - last < SIGNAL_COOLDOWN: continue
                try:
                    msg = build_message(gem)
                    await bot.send_message(chat_id=CHAT_ID, text=msg, disable_web_page_preview=True)
                    signal_times[key] = time.time()
                    log.info("Sent: $%s %s score=%d source=%s" % (
                        gem["symbol"], gem["tier"], gem["final_score"], gem["source"]))
                    await asyncio.sleep(2)
                except Exception as e:
                    log.error("Send error: %s" % e)
        except Exception as e:
            log.error("Scan error: %s" % e)
        log.info("Next scan in %ds" % SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
