# DARK FILES TREND INTELLIGENCE SYSTEM v2.0
# Scans: Google Trends + YouTube + Reddit
# Output: Ranked topic opportunities + Full metadata package
import json, time, re, random
from datetime import datetime
from collections import Counter
import requests

DF_KEYWORDS = [
    'true crime', 'unsolved mystery', 'classified documents',
    'government cover up', 'missing persons case', 'cold case',
    'serial killer documentary', 'declassified files',
    'unexplained disappearance', 'dark history',
]

DF_SUBREDDITS = [
    'UnresolvedMysteries', 'TrueCrime', 'conspiracy',
    'Missing411', 'ColdCases', 'ClassifiedDocuments',
    'Paranormal', 'MurderMystery',
]

# ── 1. REDDIT SCANNER (no API key needed) ────────────────────────
def scan_reddit():
    print("  Scanning Reddit trending posts...")
    topics = []
    headers = {'User-Agent': 'DarkFilesResearch/2.0'}
    for sub in DF_SUBREDDITS:
        try:
            r = requests.get(
                f'https://www.reddit.com/r/{sub}/hot.json?limit=20',
                headers=headers, timeout=10
            )
            if r.status_code == 200:
                for p in r.json()['data']['children']:
                    d = p['data']
                    if d['score'] > 50 and not d.get('stickied'):
                        topics.append({
                            'title'    : d['title'],
                            'score'    : d['score'],
                            'comments' : d['num_comments'],
                            'subreddit': sub,
                            'url'      : f"https://reddit.com{d['permalink']}",
                            'source'   : 'Reddit',
                        })
            time.sleep(0.4)
        except Exception as e:
            print(f"    Warning r/{sub}: {str(e)[:40]}")
    topics.sort(key=lambda x: x['score'] + x['comments'] * 3, reverse=True)
    print(f"    {len(topics)} trending posts found")
    return topics

# ── 2. GOOGLE TRENDS SCANNER ────────────────────────────────────
def scan_google_trends():
    print("  Scanning Google Trends...")
    trend_scores, rising_topics = {}, []
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='en-US', tz=0, timeout=(10, 30))
        batches = [DF_KEYWORDS[i:i+5] for i in range(0, len(DF_KEYWORDS), 5)]
        for batch in batches:
            try:
                pytrends.build_payload(batch, timeframe='now 7-d', geo='')
                df = pytrends.interest_over_time()
                if not df.empty:
                    for kw in batch:
                        if kw in df.columns:
                            vals = df[kw].values
                            trend_scores[kw] = {
                                'avg'     : int(vals.mean()),
                                'peak'    : int(vals.max()),
                                'velocity': int(vals[-1]) - int(vals[0]),
                            }
                time.sleep(1.5)
            except Exception as e:
                print(f"    Trends batch warning: {str(e)[:40]}")
        try:
            pytrends.build_payload(['true crime', 'unsolved mystery'], timeframe='now 7-d')
            related = pytrends.related_queries()
            for kw in related:
                if related[kw].get('rising') is not None:
                    rising_topics += related[kw]['rising']['query'].head(5).tolist()
        except Exception:
            pass
        print(f"    {len(trend_scores)} keyword trends + {len(rising_topics)} rising queries found")
    except Exception as e:
        print(f"    Google Trends limited: {str(e)[:50]}")
    return trend_scores, list(set(rising_topics))

# ── 3. YOUTUBE COMPETITION ANALYZER ─────────────────────────────
def analyze_youtube(topic):
    try:
        from youtubesearchpython import VideosSearch
        results = VideosSearch(f"{topic} documentary", limit=10).result()
        videos  = results.get('result', [])
        titles  = [v.get('title','') for v in videos]
        views   = []
        for v in videos:
            vc   = v.get('viewCount', {})
            text = (vc.get('text','0') if isinstance(vc, dict) else str(vc))
            text = re.sub(r'[^0-9]', '', text)
            try: views.append(int(text))
            except: pass
        avg_views = int(sum(views)/len(views)) if views else 0
        comp      = 'HIGH' if len(videos) >= 8 else ('MEDIUM' if len(videos) >= 4 else 'LOW')
        return {'count': len(videos), 'avg_views': avg_views, 'titles': titles, 'competition': comp}
    except Exception:
        return {'count': 0, 'avg_views': 0, 'titles': [], 'competition': 'UNKNOWN'}

# ── 4. UNIQUE ANGLE ENGINE ───────────────────────────────────────
ANGLE_TEMPLATES = [
    "the classified evidence that was immediately sealed",
    "the witness statement that contradicts the official timeline",
    "the government document released under FOIA that changes everything",
    "the detail every mainstream outlet buried",
    "the investigator who was removed before they could testify",
    "the second victim nobody talks about",
    "the agency that was present but never mentioned in the report",
    "the 48-hour window the official story cannot account for",
    "the forensic anomaly the coroner flagged but was overruled",
    "the survivor who gave one interview and was never heard from again",
    "the files that were destroyed three days before the trial",
    "the location connection every documentary ignored",
]

HOOK_TEMPLATES = [
    "Every documentary told you the story. Nobody told you {a}.",
    "Mainstream media covered the case. They forgot to mention {a}.",
    "The official report runs 847 pages. {a} appears nowhere in it.",
    "Three networks. Four documentaries. Zero mention of {a}.",
    "You have seen the headlines. Here is {a} -- the part they cut.",
]

def generate_angle(topic, yt_titles):
    title_blob = ' '.join(yt_titles).lower()
    covered = []
    if any(w in title_blob for w in ['solved','caught','arrested','found']):
        covered.append("the resolution")
    if any(w in title_blob for w in ['story','explained','happened','truth']):
        covered.append("the surface narrative")
    if any(w in title_blob for w in ['documentary','investigation','case']):
        covered.append("the official investigation")
    angle = random.choice(ANGLE_TEMPLATES)
    hook  = random.choice(HOOK_TEMPLATES).replace('{a}', angle)
    return {
        'what_mainstream_covered': covered or ["the official story"],
        'dark_files_angle'       : angle,
        'opening_hook'           : hook,
    }

# ── 5. SCRIPT OUTLINE GENERATOR ──────────────────────────────────
def generate_outline(topic, angle_data):
    angle = angle_data['dark_files_angle']
    hook  = angle_data['opening_hook']
    lines = [
        f"DARK FILES SCRIPT OUTLINE -- {topic.upper()}",
        "",
        "[00:00 - HOOK]",
        hook,
        "Open with the most disturbing suppressed detail. No context yet.",
        "",
        "[01:30 - SETUP]",
        "Walk through the official narrative calmly. Specific dates, names, locations.",
        "",
        f"[05:00 - THE BURIED DETAIL]",
        f"Introduce: {angle}",
        "Present the evidence. Be specific. Cite sources.",
        "",
        "[10:00 - THE PATTERN]",
        "Show the pattern. Other cases. Other files. Connect the dots.",
        "",
        "[16:00 - WHAT IT MEANS]",
        f"What does {angle} tell us about what really happened?",
        "Present logical conclusion from evidence only. No speculation.",
        "",
        "[20:00 - SIGN OFF]",
        '"The file is still open. Subscribe to Dark Files."',
        "",
        "CLAUDE RESEARCH PROMPT:",
        f'"Research {angle} related to {topic}.',
        "Find specific facts, dates, names and source documents",
        'that mainstream media did not cover. Information gain only."',
    ]
    return '\n'.join(lines)

# ── 6. METADATA GENERATOR ───────────────────────────────────────
def generate_metadata(topic, angle_data, trend_score=50):
    t     = topic.title()
    angle = angle_data['dark_files_angle']

    titles = [
        f"The {t}: {angle.title()} -- Dark Files",
        f"What Every Documentary Got Wrong About {t}",
        f"{t}: The File They Never Wanted Public",
        f"Declassified: {t} & {angle.title()}",
        f"The REAL {t} -- {angle.title()} (Classified)",
    ]

    description = (
        f"DARK FILES -- {t}\n\n"
        f"{angle_data['opening_hook']}\n\n"
        f"In this episode, Dark Files uncovers {angle} surrounding {t}. "
        "Every mainstream documentary covered the surface story. "
        "We go deeper -- into the evidence buried, the witnesses silenced "
        "and the files sealed.\n\n"
        "This is information gain. Details no other channel has covered.\n\n"
        "Sources and documents referenced in this video are cited below.\n\n"
        "CHAPTERS\n"
        "00:00 -- The Detail Nobody Covered\n"
        "01:30 -- What You Were Told\n"
        f"05:00 -- {angle.title()}\n"
        "10:00 -- The Pattern\n"
        "16:00 -- What It Means\n"
        "20:00 -- The File Stays Open\n\n"
        "Subscribe to DARK FILES -- classified content every week.\n"
        f"#DarkFiles #TrueCrime #ClassifiedSecrets #{t.replace(' ','')} "
        "#UnsolvedMystery #Documentary #Conspiracy #Declassified #ColdCase"
    )

    tags = [
        topic.lower(), f"{topic.lower()} documentary", f"{topic.lower()} true crime",
        f"{topic.lower()} unsolved", f"{topic.lower()} explained", f"{topic.lower()} 2026",
        "true crime", "unsolved mystery", "classified documents", "dark files",
        "government cover up", "conspiracy", "declassified", "cold case",
        "missing persons", "dark history", "secret history", "suppressed evidence",
        "what really happened", "documentary 2026", "true crime documentary",
        "scary true stories", "classified secrets", "fbi files", "cia documents",
    ]

    return {
        'best_title'   : titles[0],
        'title_options': titles,
        'description'  : description,
        'tags'         : tags,
        'thumbnail'    : {
            'main' : t.upper(),
            'sub'  : 'THEY HID THIS',
            'style': 'Black bg, blood-red accent, white bold text, FBI redaction stamp',
        },
        'upload_day'   : 'Thursday or Friday',
        'upload_time'  : '6PM - 9PM viewer local time',
        'trend_score'  : trend_score,
    }

# ── 7. OPPORTUNITY SCORER ────────────────────────────────────────
def score_opp(reddit_engagement, trend_avg, trend_velocity, competition):
    reddit_pts   = min(reddit_engagement / 2000 * 30, 30)
    trend_pts    = min(trend_avg / 100 * 25, 25)
    velocity_pts = min(max(trend_velocity, 0) / 50 * 15, 15)
    comp_pts     = {'LOW': 30, 'MEDIUM': 18, 'HIGH': 8, 'UNKNOWN': 12}.get(competition, 12)
    return int(reddit_pts + trend_pts + velocity_pts + comp_pts)

# ── 8. MASTER SCAN ───────────────────────────────────────────────
print("\n" + "=" * 65)
print("DARK FILES TREND INTELLIGENCE SYSTEM")
print("Scanning: Google Trends | YouTube | Reddit")
print("=" * 65 + "\n")

reddit_topics         = scan_reddit()
trend_data, rising    = scan_google_trends()

print("  Analyzing YouTube competition + generating angles...")
opportunities = []

for post in reddit_topics[:10]:
    topic = re.sub(r'[^a-zA-Z0-9 ]', '', post['title'])[:70].strip()
    if len(topic) < 8:
        continue
    yt       = analyze_youtube(topic)
    angle    = generate_angle(topic, yt['titles'])
    t_info   = trend_data.get(topic.lower().split()[0], {})
    t_avg    = t_info.get('avg', 20)
    t_vel    = t_info.get('velocity', 0)
    opp      = score_opp(post['score'], t_avg, t_vel, yt['competition'])
    opportunities.append({
        'topic'       : topic,
        'source'      : f"Reddit r/{post['subreddit']}",
        'engagement'  : post['score'],
        'opportunity' : opp,
        'competition' : yt['competition'],
        'trend_vel'   : t_vel,
        'angle'       : angle,
        'metadata'    : generate_metadata(topic, angle, t_avg),
        'outline'     : generate_outline(topic, angle),
        'yt_count'    : yt['count'],
        'yt_avg_views': yt['avg_views'],
    })
    time.sleep(0.3)

for rt in rising[:4]:
    if len(rt) < 6:
        continue
    yt    = analyze_youtube(rt)
    angle = generate_angle(rt, yt['titles'])
    opp   = score_opp(600, 75, 40, yt['competition'])
    opportunities.append({
        'topic': rt, 'source': 'Google Trends (Rising)', 'engagement': 600,
        'opportunity': opp, 'competition': yt['competition'], 'trend_vel': 40,
        'angle': angle, 'metadata': generate_metadata(rt, angle, 75),
        'outline': generate_outline(rt, angle),
        'yt_count': yt['count'], 'yt_avg_views': yt['avg_views'],
    })
    time.sleep(0.3)

opportunities.sort(key=lambda x: x['opportunity'], reverse=True)

# ── DISPLAY RESULTS ──────────────────────────────────────────────
print("\n" + "=" * 65)
print("TOP DARK FILES EPISODE OPPORTUNITIES THIS WEEK")
print("=" * 65)

for i, o in enumerate(opportunities[:5]):
    s   = o['opportunity']
    vel = o['trend_vel']
    tag = "HOT"    if s >= 70 else ("STRONG" if s >= 50 else "SOLID")
    trn = "Rising" if vel > 5 else ("Stable" if vel >= -5 else "Fading")

    print(f"\n{'─'*65}")
    print(f"[{tag}] #{i+1} -- OPPORTUNITY SCORE: {s}/100  |  Trend: {trn}")
    print(f"{'─'*65}")
    print(f"TOPIC       : {o['topic']}")
    print(f"SOURCE      : {o['source']}")
    print(f"ENGAGEMENT  : {o['engagement']:,} Reddit score")
    print(f"COMPETITION : {o['competition']} on YouTube ({o['yt_count']} existing videos)")
    print(f"AVG VIEWS   : {o['yt_avg_views']:,} on competing videos")
    print(f"\nUNIQUE ANGLE (what nobody covered):")
    print(f"  -> {o['angle']['dark_files_angle']}")
    print(f"\nOPENING HOOK:")
    print(f'  "{o["angle"]["opening_hook"]}"')
    print(f"\nTITLE OPTIONS:")
    for j, t in enumerate(o['metadata']['title_options'][:3], 1):
        print(f"  {j}. {t}")
    print(f"\nTOP TAGS    : {', '.join(o['metadata']['tags'][:7])}")
    print(f"THUMBNAIL   : [{o['metadata']['thumbnail']['main']}] [{o['metadata']['thumbnail']['sub']}]")
    print(f"UPLOAD      : {o['metadata']['upload_day']} at {o['metadata']['upload_time']}")

print("\n" + "=" * 65)
print("\nSCRIPT OUTLINE -- Top Opportunity:")
print(opportunities[0]['outline'] if opportunities else "No topics found.")
print("""
===============================================================
NEXT STEPS:
  1. Pick the topic with the highest score above
  2. Use Claude to research the UNIQUE ANGLE
     (paste the CLAUDE RESEARCH PROMPT from the outline)
  3. Write your full Dark Files script (500+ words)
  4. Scroll down to Cell 8, paste your script
  5. Runtime -> Run all -> Download your finished video
===============================================================
""")
