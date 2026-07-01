"""
Build the Dark Files Video Generator Colab notebook.
Run: python build_notebook.py
Output: dark_files_generator.ipynb
"""

import json, os

def md(src): return {"cell_type":"markdown","metadata":{},"source":src}
def code(src): return {"cell_type":"code","execution_count":None,"metadata":{},"outputs":[],"source":src}

# Load trend cell from separate file to avoid nested quote / emoji encoding issues
_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, 'trend_cell.py'), 'r', encoding='utf-8') as _f:
    _TREND_SRC = _f.read()

# ── CELLS ──────────────────────────────────────────────────────────────────────

CELL_TITLE = md("""\
# 🎬 DARK FILES — Complete YouTube Production System
### True Crime · Classified Secrets · Dark Chapters of History
---
**This notebook has TWO systems — both completely free:**

**🔍 SYSTEM 1 — Trend Intelligence (Run first)**
- Scans Google Trends, YouTube & Reddit simultaneously
- Finds what people are actively searching right now
- Scores each topic by opportunity (high demand, low competition)
- Detects the unique angle nobody has covered
- Generates complete metadata: titles, description, tags, thumbnail text

**🎬 SYSTEM 2 — Video Generator (After you have your script)**
- Generates realistic motion video per scene (LTX-Video)
- Professional deep voiceover (Microsoft Edge neural TTS)
- Dark ambient background music (Meta MusicGen)
- Cinematic fade transitions + synced captions
- Dark Files color grade (cold blue, crushed blacks, film grain)
- Exports YouTube-ready MP4

---
### ⚡ Before you start
1. Click **Runtime → Change runtime type → T4 GPU → Save**
2. **Run System 1 first** to find your episode topic
3. **Research the unique angle** using Claude
4. **Paste your script into Cell 8** and run System 2

> ⏱️ Trend scan: ~3 min | Video generation: ~30–50 min on free T4 GPU
""")

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM 1: TREND INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────

CELL_TREND_INSTALL = code("""\
# ── SYSTEM 1 · STEP 1: Install Trend Intelligence packages ───────
import subprocess
print("📦  Installing Trend Intelligence packages...")
subprocess.run(['pip', 'install', '-q',
    'pytrends',
    'youtube-search-python',
    'requests',
    'beautifulsoup4',
], check=True)
print("✅  Done!")
""")

CELL_TREND_INTELLIGENCE = code(_TREND_SRC)


CELL_GPU = code("""\
# ── STEP 0: Verify GPU ──────────────────────────────────────────
import subprocess, os, sys

result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
if result.returncode != 0:
    print("❌  No GPU found!")
    print("👉  Go to Runtime → Change runtime type → GPU → T4 → Save")
    print("    Then restart and run again.")
    sys.exit(1)

# Print GPU name and memory
for line in result.stdout.split('\\n'):
    if 'Tesla' in line or 'T4' in line or 'A100' in line or 'L4' in line or 'V100' in line:
        print(f"✅  GPU: {line.strip()}")
        break
else:
    print("✅  GPU detected")
    print(result.stdout[:300])

# Create working directories
for d in ['/content/dark_files/clips', '/content/dark_files/audio',
          '/content/dark_files/final', '/content/dark_files/cache']:
    os.makedirs(d, exist_ok=True)

print("\\n📁  Working directories ready")
print("🚀  Ready to generate Dark Files videos!")
""")

CELL_INSTALL = code("""\
# ── STEP 1: Install dependencies ────────────────────────────────
print("Installing packages (3-5 min first time)...")

import subprocess
pkgs = [
    "edge-tts",
    "diffusers>=0.31.0",
    "transformers>=4.40.0",
    "accelerate",
    "sentencepiece",
    "protobuf",
]
subprocess.run(["pip", "install", "-q", "--upgrade"] + pkgs, check=True)

# Verify FFmpeg
r = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
print(f"  {r.stdout.splitlines()[0]}" if r.returncode == 0 else "  FFmpeg missing!")
print("All packages installed!")
""")

CELL_IMPORTS = code("""\
# ── STEP 2: Imports ─────────────────────────────────────────────
import os, re, json, asyncio, subprocess, math, time, warnings
import numpy as np
from pathlib import Path

import torch
warnings.filterwarnings('ignore')

from IPython.display import Video, display, HTML
try:
    from google.colab import files as colab_files
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE  = torch.bfloat16

if DEVICE == "cuda":
    props = torch.cuda.get_device_properties(0)
    print(f"🖥️   GPU : {props.name}")
    print(f"💾  VRAM : {props.total_memory / 1e9:.1f} GB")
else:
    print("⚠️   Running on CPU — video generation will be very slow")

print(f"\\n✅  Ready  |  Device: {DEVICE.upper()}")
""")

CELL_SCRIPT = code("""\
# ── STEP 3: Episode Settings & Upload Script ─────────────────────
# 1. Edit EPISODE_TITLE and voice below.
# 2. Run this cell.
# 3. Click Choose Files and select your script as a plain .txt file.
#    Your script can contain any characters (dashes, quotes, etc.)
# ─────────────────────────────────────────────────────────────────

EPISODE_TITLE  = "The Classified Files"   # <- change this

# Voice options (uncomment one)
VOICE          = "en-US-GuyNeural"        # Deep authoritative male  <- DEFAULT
# VOICE        = "en-US-EricNeural"       # Serious male narrator
# VOICE        = "en-US-ChristopherNeural"# Calm, grave male voice
# VOICE        = "en-GB-RyanNeural"       # British male (BBC documentary feel)

SPEAKING_RATE  = "-10%"
SPEAKING_PITCH = "-3Hz"

# ── Upload script ────────────────────────────────────────────────
from google.colab import files as _gcf
print(f"Episode: {EPISODE_TITLE}")
print(f"Voice  : {VOICE}")
print("\\nClick Choose Files below and select your script as a .txt file...")
_up = _gcf.upload()
if not _up:
    raise RuntimeError("No file uploaded. Run this cell again.")
YOUR_SCRIPT = list(_up.values())[0].decode("utf-8", errors="replace").strip()
words = len(YOUR_SCRIPT.split())
print(f"\\nScript loaded: {words} words  (~{words / (110/60):.0f}s  {words / (110/60) / 60:.1f} min)")
""")

CELL_PARSER = code("""\
# ── STEP 4: Scene parser + Dark Files prompt engine ─────────────

# ── Dark Files visual prompt database ───────────────────────────
DARK_AESTHETIC = (
    "award winning cinematic photography, professional Hollywood cinematography, "
    "dramatic three-point lighting, rich deep colors, sharp crisp focus, "
    "photorealistic ultra detailed 8k, beautiful atmospheric depth, "
    "teal and orange color grade, visible shadow detail, "
    "National Geographic documentary style, stunning visual composition"
)

DARK_NEGATIVE = (
    "cartoon, animated, illustration, painting, drawing, sketch, "
    "blurry, out of focus, low quality, distorted, watermark, text overlay, logo, nsfw, "
    "overexposed, washed out, flat lighting, stock photo, generic, boring, "
    "duplicate, deformed, ugly, bad anatomy, grainy, noisy, pixelated, "
    "pitch black, too dark, underexposed, muddy, unclear"
)

VISUAL_MAP = [
    (r'pilot|cockpit|cessna|aviator|flying|took off|takeoff|altitude|feet',
     'stunning cinematic cockpit interior at dusk, young pilot in uniform with focused expression, beautifully lit instrument panel with amber and blue glowing dials, vast sky visible through windscreen, cinematic depth of field, dramatic side lighting'),
    (r'radio|transmission|signal|contact|broadcast|frequency|transmit|microphone',
     'cinematic close-up of vintage 1970s radio equipment, glowing frequency dials in amber and green, audio waveform display, dramatic warm side lighting, rich textures, professional photography'),
    (r'air.?traffic|controller|tower|radar|robey|melbourne',
     'cinematic air traffic control room at night, multiple glowing radar screens in teal and green, professional controller at workstation, dramatic blue-amber lighting, rich atmospheric depth'),
    (r'metallic|scraping|sound|noise|interference|silence|static',
     'cinematic close-up of reel-to-reel tape recorder with audio waveform display, warm amber instrument lighting, dramatic side shadows, rich detailed textures, 1970s professional equipment'),
    (r'search|rescue|vessel|coastguard|aircraft.*search|search.*aircraft',
     'dramatic cinematic wide shot of coastguard search vessel on vast open ocean at sunset, powerful searchlights, golden and teal water reflections, breathtaking atmospheric photography'),
    (r'photograph|photo|camera|image|picture|manifold',
     'cinematic close-up of old classified photographs spread on a wooden desk, dramatic warm side lighting, magnifying glass, visible film grain texture on photos, rich vintage atmosphere'),
    (r'ocean|sea|bass strait|water|coast|strait|overwater',
     'breathtaking cinematic wide shot of vast ocean at dusk, dramatic golden-teal sky reflected on water surface, storm clouds building on horizon, stunning atmospheric photography'),
    (r'forest|woods|trees|woodland',
     'stunning cinematic forest scene, shafts of golden light through ancient tall trees, beautiful atmospheric mist between trunks, rich green and amber tones, breathtaking nature photography'),
    (r'facility|complex|plant|factory|warehouse',
     'cinematic wide shot of industrial facility at dramatic dusk, warm orange sunset behind steel structures, security lighting, rich orange-teal color contrast, architectural photography'),
    (r'laborator|lab|research|scientist',
     'cinematic government laboratory interior, clean white sterile environment, dramatic blue fluorescent lighting, scientist silhouette at equipment, rich color contrast, professional photography'),
    (r'city|town|street|urban|neighborhood|melbourne',
     'stunning cinematic city street at blue hour, rain-wet pavement reflecting neon signs in amber and teal, beautiful bokeh lights in background, dramatic atmospheric photography'),
    (r'desert|nevada|arizona|wasteland|remote|plains',
     'breathtaking cinematic desert landscape at golden hour, dramatic clouds casting long shadows, desolate road to horizon, rich warm orange and purple tones, stunning wide shot'),
    (r'prison|jail|detention|cell|incarcerat',
     'cinematic prison corridor with dramatic lighting, iron bars casting long geometric shadows, warm overhead light contrasting with cool blue shadows, rich architectural photography'),
    (r'courtroom|trial|judge|lawyer|testimony|verdict',
     'dramatic cinematic courtroom interior, oak paneling, warm overhead spotlights on witness stand, beautiful architectural details, rich amber and shadow contrast, atmospheric photography'),
    (r'cemetery|grave|tombstone|burial',
     'cinematic cemetery at dramatic blue hour, beautiful old stone monuments, mist rolling between headstones, rich teal and amber light, atmospheric documentary photography'),
    (r'hospital|medical|morgue|autopsy|clinic',
     'cinematic hospital corridor, dramatic perspective with vanishing point, fluorescent blue-white lighting, reflective floors, atmospheric depth, professional architectural photography'),
    (r'police|detective|investig|crime scene|sheriff',
     'cinematic crime scene photograph, dramatic yellow tape against dark background, red-blue police lights reflecting on wet pavement, atmospheric depth, professional documentary photography'),
    (r'document|file|report|classif|declassif|evidence|record|freedom.?of.?information|foia|sealed',
     'stunning cinematic close-up of declassified documents with redacted black lines, dramatic warm side lighting, rich paper texture, wooden desk surface, atmospheric documentary style'),
    (r'disappear|vanish|missing|abduct|gone|never.*found|never.*seen',
     'cinematic empty room with dramatic single window light, overturned chair casting long shadow, beautiful atmospheric dust particles in light beam, rich contrast, haunting composition'),
    (r'government|military|pentagon|CIA|FBI|NSA|agency|federal|intelligence|department',
     'dramatic cinematic wide shot of imposing government building at dawn, beautiful warm light on stone facade, symmetrical architectural composition, rich teal sky, stunning photography'),
    (r'witness|survivor|victim|family|father|mother|guido',
     'cinematic portrait silhouette of person at large window, beautiful blue-hour light from outside, rich rim lighting, thoughtful composition, atmospheric documentary photography'),
    (r'secret|hidden|cover|buried|suppress|conceal',
     'cinematic close-up of heavy vault or safe door, dramatic warm side lighting, rich metal textures, combination lock detail, beautiful chiaroscuro shadows, professional photography'),
    (r'helicopter|military.*aircraft|search.*plane',
     'dramatic cinematic shot of helicopter silhouetted against stunning sunset sky, rotor blur, rich orange and purple clouds, breathtaking wide angle, professional aviation photography'),
    (r'phone|call|wiretap|surveillance|listen|intercept',
     'cinematic close-up of vintage rotary telephone on dark wooden desk, warm amber desk lamp, beautiful shallow depth of field, rich textures, 1970s atmospheric photography'),
    (r'newspaper|media|press|headline|journalist|editor',
     'cinematic newspaper archive, stacked yellowed papers with visible headlines, warm single lamp overhead, beautiful vintage atmosphere, rich amber tones, documentary photography'),
    (r'night|midnight|dark|evening|dusk|1978|october',
     'breathtaking cinematic night sky full of stars over calm water, milky way reflection, rich blue and silver tones, stunning astrophotography style, dramatic atmospheric wide shot'),
    (r'road|highway|bridge|airport|runway|moorabbin',
     'stunning cinematic airport runway at blue hour, perspective lines of runway lights stretching to horizon, dramatic teal sky, aircraft silhouette, beautiful aviation photography'),
    (r'body|remains|skeleton|bones|buried',
     'cinematic forensic scene at dusk, professional lighting equipment casting warm glow, evidence markers, dramatic atmospheric photography, rich color contrast'),
    (r'national.?security|classified|sealed|denied|withheld',
     'dramatic cinematic close-up of TOP SECRET stamp on document, rich red ink on aged paper, warm dramatic side lighting, beautiful depth of field, atmospheric documentary photography'),
    (r'search.*four|four.*day|called.*off|terminated|abandoned',
     'cinematic wide shot of empty ocean horizon at dawn, search vessel turning back, dramatic golden light, vast scale of ocean, heartbreaking beautiful composition'),
    (r'transcript|words|said|spoke|voice|last.*word',
     'cinematic close-up of typed transcript paper, individual words in sharp focus, warm side lighting, dramatic shadow from page edge, rich texture detail, documentary photography'),
]

def parse_scenes(script, max_words=55):
    paras = [p.strip() for p in script.strip().split('\\n') if p.strip()]
    scenes = []
    for para in paras:
        if len(para.split()) <= max_words:
            scenes.append(para)
        else:
            sents = re.split(r'(?<=[.!?])\\s+', para)
            bucket, bw = [], 0
            for s in sents:
                sw = len(s.split())
                if bw + sw > max_words and bucket:
                    scenes.append(' '.join(bucket))
                    bucket, bw = [s], sw
                else:
                    bucket.append(s); bw += sw
            if bucket:
                scenes.append(' '.join(bucket))
    return [s for s in scenes if s.strip()]

_KW_STOPS = {
    "that","this","with","from","they","them","their","have","been","were",
    "would","could","should","about","after","before","while","these","those",
    "some","when","then","what","which","will","also","just","like","more",
    "than","into","only","over","such","each","most","made","make","take",
    "time","very","even","back","still","well","said","told","went","came",
    "know","seen","year","years","never","every","there","here","where","only",
    "because","since","until","first","last","found","called","became","began",
}

def _scene_keywords(text, n=5):
    words = re.findall(r'\\b[a-zA-Z]{4,}\\b', text.lower())
    kw = [w for w in words if w not in _KW_STOPS]
    return ", ".join(list(dict.fromkeys(kw))[:n]) or "mystery"

def make_prompt(scene_text):
    low = scene_text.lower()
    matched = []
    for pattern, visual in VISUAL_MAP:
        if re.search(pattern, low, re.IGNORECASE):
            matched.append(visual)
    if matched:
        base = ", ".join(matched[:2])
    else:
        # Extract keywords from the scene so every prompt is contextually specific
        kw = _scene_keywords(scene_text)
        base = (
            f"cinematic documentary scene depicting {kw}, "
            "dramatic atmospheric lighting, dark mysterious environment, "
            "shadows and depth, professional cinematography"
        )
    return f"{base}, {DARK_AESTHETIC}", DARK_NEGATIVE

def estimate_secs(text, wpm=110):
    return (len(text.split()) / wpm) * 60

# ── Preview ──────────────────────────────────────────────────────
scenes = parse_scenes(YOUR_SCRIPT)
print(f"📊  Parsed into {len(scenes)} scenes\\n{'='*65}")
for i, s in enumerate(scenes):
    dur = estimate_secs(s)
    prompt, _ = make_prompt(s)
    print(f"\\n🎬  Scene {i+1}  ({dur:.1f}s | {len(s.split())} words)")
    print(f"    Text   : {s[:75]}...")
    print(f"    Prompt : {prompt[:80]}...")
total = sum(estimate_secs(s) for s in scenes)
print(f"\\n{'='*65}")
print(f"⏱️   Total estimated duration: {total:.0f}s  ({total/60:.1f} min)")
print(f"⏳  Estimated generation time on T4: {len(scenes)*3:.0f}–{len(scenes)*5:.0f} min")
""")

CELL_VOICEOVER = code("""\
# ── STEP 5: Generate voiceover + caption timing ──────────────────
import nest_asyncio
nest_asyncio.apply()
import edge_tts, asyncio, json, subprocess

async def gen_voice_simple(text, voice, rate, pitch, audio_out):
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(audio_out)

def audio_dur(path):
    r = subprocess.run(
        ['ffprobe','-v','quiet','-print_format','json','-show_format', path],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"ffprobe failed on {path}: {r.stderr[:200]}")
    return float(json.loads(r.stdout)['format']['duration'])

print(f"🎙️   Generating voiceover  ({VOICE})...\\n")
audio_paths, vtt_paths, durations = [], [], []

for i, scene in enumerate(scenes):
    ap = f'/content/dark_files/audio/scene_{i:03d}.mp3'
    vp = f'/content/dark_files/audio/scene_{i:03d}.vtt'
    for _try in range(3):
        try:
            asyncio.run(gen_voice_simple(scene, VOICE, SPEAKING_RATE, SPEAKING_PITCH, ap))
            break
        except Exception as _e:
            if _try == 2:
                raise RuntimeError(f"TTS failed for scene {i+1} after 3 tries: {_e}")
            time.sleep(2)
    d = audio_dur(ap)
    with open(vp, 'w') as f:
        f.write(f"WEBVTT\\n\\n00:00.000 --> {int(d//60):02d}:{d%60:06.3f}\\n{scene}\\n\\n")
    audio_paths.append(ap); vtt_paths.append(vp); durations.append(d)
    print(f"  ✅  Scene {i+1}/{len(scenes)}: {d:.2f}s  |  {scene[:55]}...")

total_duration = sum(durations)

# Save to disk so later cells can recover on session restart
_jpath = '/content/dark_files/scene_data.json'
with open(_jpath, 'w') as _jf:
    json.dump([{'text': s, 'audio': a, 'vtt': v, 'duration': d}
               for s, a, v, d in zip(scenes, audio_paths, vtt_paths, durations)], _jf, indent=2)

print(f"\\n✅  Voiceover complete!")
print(f"⏱️   Total duration: {total_duration:.1f}s  ({total_duration/60:.1f} min)")
""")

CELL_DARK_PROMPT_GEN = code("""\
# ── STEP 5B (PATH A): Generate Dark Files Image Prompts ─────────────────────
# For every scene, generates one image prompt that mirrors the EXACT numbers,
# names and facts spoken in the voiceover — nothing paraphrased.
# Paste each prompt into Midjourney, DALL-E, Ideogram, or Adobe Firefly.
# ─────────────────────────────────────────────────────────────────────────────
import re, json, os
from google.colab import files as _cf

if 'EPISODE_TITLE' not in dir(): EPISODE_TITLE = 'The Classified Files'

if 'scenes' not in dir() or 'durations' not in dir():
    _jp = '/content/dark_files/scene_data.json'
    if not os.path.exists(_jp):
        raise RuntimeError('Run Step 5 (Voiceover) first.')
    with open(_jp) as _jf:
        _sd = json.load(_jf)
    scenes    = [x['text']     for x in _sd]
    durations = [x['duration'] for x in _sd]

_ANCHOR = (
    'Cold case documentary illustration, flat editorial style, '
    'muted desaturated palette, bold typewriter-style text overlays, '
    'composed like evidence laid out on a desk,'
)
_LOCK = (
    'no photorealism, no horror aesthetics, no dramatic lighting, '
    'no stock footage look, no sensationalism, 16:9 aspect ratio, '
    'investigative documentary visual style.'
)

def _bg(text):
    w = text.lower()
    if any(x in w for x in ['document','file','foia','classif','redact','page','report','sealed','archive','record']):
        return 'white (#FFFFFF) background, aged paper texture suggestion'
    if any(x in w for x in ['court','judge','trial','testimony','verdict','lawyer','hearing']):
        return 'pale institutional gray (#D9D9D9) background'
    if any(x in w for x in ['cover','suppress','hidden','buried','withheld','denied','conceal']):
        return 'deep charcoal (#1C1C1C) background'
    if any(x in w for x in ['found','body','remains','location','miles','address']):
        return 'dark navy (#0D1B2A) background'
    if any(x in w for x in ['1800','1900','1910','1920','1930','1940','archive','century','historical']):
        return 'sepia (#C4965A) aged paper background'
    return 'aged cream manila paper (#F5F0E8) background'

def _frame(text):
    w = text.lower()
    if any(x in w for x in ['document','file','foia','classif','redact','page','report','sealed','filed','record']):
        return 'document'
    if any(x in w for x in ['said','testified','stated','claimed','told','according to','witness']):
        return 'witness_quote'
    if any(x in w for x in ['official','but the','however','contradict','actually','real version','instead']):
        return 'contradiction'
    if any(x in w for x in ['miles','location','address','city','state','county','near','found at']):
        return 'location'
    if any(x in w for x in ['timeline','sequence','then','after','before','followed','later','earlier']):
        return 'timeline'
    return 'document'

def _extract_overlay(text):
    # Pull exact number-noun pairs straight from the narration
    pairs = re.findall(r'\\b(\\d[\\d,]*)\\s+([a-zA-Z]+(?:\\s+[a-zA-Z]+)?)', text)
    results = [num + ' ' + noun.upper() for num, noun in pairs[:2]]
    yrs = re.findall(r'\\b(19|20)\\d{2}\\b', text)
    if yrs and not any(yrs[0] in r for r in results):
        results.append(yrs[0])
    return ' — '.join(results[:2])

def _stamp(text):
    w = text.lower()
    if any(x in w for x in ['no reason','not filed','no explanation']):        return 'NO REASON FILED'
    if any(x in w for x in ['top secret','classified','secret']):               return 'CLASSIFIED'
    if any(x in w for x in ['denied','withheld','refused']):                    return 'DENIED'
    if any(x in w for x in ['redacted','blacked out','removed']):               return 'REDACTED'
    return None

def _build(text, dur):
    bg      = _bg(text)
    ft      = _frame(text)
    overlay = _extract_overlay(text)
    stmp    = _stamp(text)

    overlay_line = (', bold ALL CAPS typewriter text at top of frame reading ' + '"' + overlay + '"') if overlay else ''
    stamp_line   = (', red rubber stamp reading ' + '"' + stmp + '" slightly crooked in lower corner') if stmp else ''

    if ft == 'document':
        has_redact   = any(x in text.lower() for x in ['redact','classif','page','foia','sealed'])
        redact_note  = ', thick black REDACTED bars crossing three lines on the top document page' if has_redact else ''
        mid = 'open manila file folder with document pages fanning out on aged desk surface' + redact_note + overlay_line + stamp_line + ', ' + bg + ','

    elif ft == 'witness_quote':
        raw_quote = text[:55].rstrip(',')
        name_m = re.search(r'\\b([A-Z][a-z]+(?:\\s+[A-Z][a-z]+)?)\\s+(?:said|stated|testified|claimed|told)', text)
        name   = name_m.group(1).upper() if name_m else 'WITNESS'
        mid = ('plain white page, large open quotation marks top-left, bold typewriter text '
               + '"' + raw_quote.upper() + '" centered, '
               + 'ALL CAPS attribution ' + '"' + name + '" below in smaller typewriter, ' + bg + ',')

    elif ft == 'contradiction':
        mid = ('split composition — left column bold typewriter header OFFICIAL VERSION, '
               'right column header DOCUMENT SAYS, thin vertical dividing line, '
               'contrasting facts in smaller typewriter text below each header' + overlay_line + ', ' + bg + ',')

    elif ft == 'location':
        loc_m  = re.search(r'\\b([A-Z][a-z]+(?:[,\\s]+[A-Z][a-z]+)?)\\b', text)
        dist_m = re.search(r'\\b(\\d+)\\s*(mile|kilometer|km|feet|yard)', text)
        loc_label  = loc_m.group(0).upper() if loc_m else 'LOCATION'
        dist_label = (dist_m.group(1) + ' ' + dist_m.group(2).upper() + 'S') if dist_m else ''
        dist_note  = (', distance marker ' + '"' + dist_label + '" in bold red') if dist_label else ''
        mid = ('minimal flat map outline, simple location pin marker, '
               'bold ALL CAPS typewriter label ' + '"' + loc_label + '" beside pin'
               + dist_note + ', ' + bg + ',')

    elif ft == 'timeline':
        tm = re.findall(r'\\b(?:January|February|March|April|May|June|July|August|September|October|November|December|19\\d{2}|20\\d{2})\\b', text)
        dates_note = (' key dates: ' + ', '.join(tm[:3]).upper()) if tm else ''
        mid = ('horizontal timeline bar spanning full frame width,' + dates_note
               + ' bold typewriter date labels above the line, '
               'brief ALL CAPS event labels below, ' + bg + ',')
    else:
        mid = 'aged manila file folder open on plain desk, ' + bg + ','

    return _ANCHOR + ' ' + mid + ' ' + _LOCK

# ── Generate ──────────────────────────────────────────────────────────────────
print(f'Generating {len(scenes)} Dark Files image prompts...\\n')
_lines = ['DARK FILES — IMAGE PROMPTS', 'Episode: ' + EPISODE_TITLE, '=' * 65, '']

for _i, (_txt, _dur) in enumerate(zip(scenes, durations)):
    _p = _build(_txt, _dur)
    print(f'  [{_i+1}] {_txt[:65]}')
    _lines.append(f'── SCENE {_i+1:03d}  ({_dur:.1f}s) ──────────────────────────────────')
    _lines.append('NARRATION : ' + _txt)
    _lines.append('PROMPT    : ' + _p)
    _lines.append('')

_safe = re.sub(r'[^\\w\\s-]+', '', EPISODE_TITLE).strip().replace(' ', '_')
_out  = '/content/dark_files/dark_files_prompts_' + _safe + '.txt'
with open(_out, 'w', encoding='utf-8') as _f:
    _f.write('\\n'.join(_lines))

print(f'\\n✅  {len(scenes)} prompts saved.')
print('Downloading now...')
_cf.download(_out)
print('\\nEach PROMPT mirrors the exact words from the voiceover.')
print('Paste into Midjourney / DALL-E / Ideogram to generate the image.')
""")

CELL_LOAD_MODEL = code("""\
# ── STEP 6: Load Stable Diffusion XL image model ────────────────
#
#  SDXL: ~7 GB download — high quality cinematic images on T4 GPU.
#  Generates one detailed scene image per paragraph; FFmpeg adds
#  Ken Burns pan/zoom motion to create smooth video clips.
# ─────────────────────────────────────────────────────────────────
import torch
from diffusers import StableDiffusionXLPipeline

torch.cuda.empty_cache()
print("Loading Stable Diffusion XL (~7 GB — first run only, please wait)...\\n")

pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
    variant="fp16",
    use_safetensors=True,
    cache_dir='/content/dark_files/cache',
)
pipe.enable_model_cpu_offload()

print(f"\\n✅  Stable Diffusion XL loaded!")
print(f"    VRAM used: {torch.cuda.memory_allocated()/1e9:.2f} GB / 16 GB")
""")

CELL_GEN_CLIPS = code("""\
# ── STEP 7: Generate images → animated video clips (Drive-checkpointed) ──────
#
#  WORKS WITH ANY NUMBER OF SCENES — no scene limit.
#
#  Phase 1 — SDXL generates one cinematic image per scene.
#  Phase 2 — SVD animates each image into real motion video using 4-step
#             fast mode (~6x faster than default): 14 frames at 8 fps, looped
#             to match the exact voiceover length (-shortest sync).
#
#  Drive checkpointing: each finished clip is saved to Google Drive the moment
#  it is done. If Colab disconnects, just re-run this cell — it detects
#  which clips already exist on Drive and skips them automatically.
#
#  Fallback: if SVD errors on a clip, Ken Burns zoom is used for that clip only.
# ─────────────────────────────────────────────────────────────────────────────
import time, shutil, glob as _glob_mod
from PIL import Image

# ── Session restart recovery — reload scene data if cells above weren't run ───
if 'scenes' not in dir() or 'durations' not in dir() or 'audio_paths' not in dir():
    _jpath = '/content/dark_files/scene_data.json'
    if not os.path.exists(_jpath):
        raise RuntimeError("scene_data.json not found. Run Cell 9 (Voiceover) first.")
    with open(_jpath) as _jf:
        _sd = json.load(_jf)
    scenes      = [x['text']     for x in _sd]
    audio_paths = [x['audio']    for x in _sd]
    vtt_paths   = [x['vtt']      for x in _sd]
    durations   = [x['duration'] for x in _sd]
    total_duration = sum(durations)
    print(f"Recovered {len(scenes)} scenes from disk.")

if 'EPISODE_TITLE' not in dir(): EPISODE_TITLE = 'The Classified Files'

# ── Mount Drive for checkpointing ─────────────────────────────────────────────
try:
    from google.colab import drive as _gd
    _gd.mount('/content/drive', force_remount=False)
    _safe_ep = re.sub(r'[^\\w-]', '_', EPISODE_TITLE)[:40]
    CKPT_DIR = f'/content/drive/MyDrive/DarkFiles/_ckpt_{_safe_ep}'
    os.makedirs(CKPT_DIR, exist_ok=True)
    _ckpt = True
    print(f"Drive checkpointing ON — {CKPT_DIR}")
    print("Re-run this cell anytime to resume after a disconnect.\\n")
except Exception as _e:
    _ckpt = False
    CKPT_DIR = '/content/dark_files/clips'
    print(f"Drive not mounted — checkpointing disabled ({_e})\\n")

def _ci(i): return f'{CKPT_DIR}/scene_{i:03d}.png'
def _cc(i): return f'{CKPT_DIR}/clip_{i:03d}.mp4'

# ── Phase 1: SDXL — generate all scene images ─────────────────────────────────
print(f"Phase 1  SDXL images  ({len(scenes)} scenes)")
img_paths = []
t0 = time.time()

for i, scene in enumerate(scenes):
    local_img = f'/content/dark_files/clips/scene_{i:03d}.png'
    img_paths.append(local_img)

    if os.path.exists(local_img):
        print(f"  {i+1}/{len(scenes)}  local cache"); continue
    if _ckpt and os.path.exists(_ci(i)):
        shutil.copy2(_ci(i), local_img)
        print(f"  {i+1}/{len(scenes)}  Drive cache"); continue

    prompt, neg = make_prompt(scene)
    gen = torch.Generator(device='cuda').manual_seed(i * 17 + 42)
    img = pipe(
        prompt=prompt, negative_prompt=neg,
        width=1024, height=576,
        num_inference_steps=25, guidance_scale=7.5,
        generator=gen,
    ).images[0]
    img.save(local_img)
    if _ckpt:
        shutil.copy2(local_img, _ci(i))
    print(f"  {i+1}/{len(scenes)}  generated  ({time.time()-t0:.0f}s)")

print(f"\\nPhase 1 done ({(time.time()-t0)/60:.1f} min). Swapping to SVD model...")
del pipe
torch.cuda.empty_cache()

# ── Phase 2: load SVD in 4-step fast mode ────────────────────────────────────
from diffusers import StableVideoDiffusionPipeline

print("Loading stable-video-diffusion-img2vid (4-step fast mode) ...")
svd_pipe = StableVideoDiffusionPipeline.from_pretrained(
    "stabilityai/stable-video-diffusion-img2vid",
    torch_dtype=torch.float16,
    variant="fp16",
    cache_dir='/content/dark_files/cache',
)
svd_pipe.enable_model_cpu_offload()
print(f"SVD ready  |  VRAM: {torch.cuda.memory_allocated()/1e9:.2f} GB\\n")

# Ken Burns fallback — instant, no model, used only when SVD errors on a clip
_KB = [
    "zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "zoompan=z='min(zoom+0.0012,1.4)':x='min(iw-iw/zoom,iw/2-(iw/zoom/2)+in*0.4)':y='ih/2-(ih/zoom/2)'",
    "zoompan=z='min(zoom+0.0012,1.4)':x='iw/2-(iw/zoom/2)':y='max(0,ih/2-(ih/zoom/2)-in*0.3)'",
    "zoompan=z='max(1.0,1.5-in*0.0018)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
]

def _ken_burns(img_path, audio_path, out_path, duration, idx=0):
    fps = 25
    frames = max(int(duration * fps) + 1, 2)
    effect = _KB[idx % len(_KB)]
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', img_path, '-i', audio_path,
        '-filter_complex', f'[0:v]{effect}:d={frames}:s=1024x576,fps={fps}[v]',
        '-map', '[v]', '-map', '1:a',
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
        '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', '-shortest',
        out_path,
    ], capture_output=True, check=True)

def _svd_clip(img_path, audio_path, out_path, scene_idx=0):
    SVD_FPS, SVD_FRAMES = 8, 14
    pil = Image.open(img_path).convert("RGB").resize((1024, 576))
    gen = torch.Generator(device='cuda').manual_seed(scene_idx * 31 + 7)
    frames = svd_pipe(
        pil,
        num_frames=SVD_FRAMES,
        num_inference_steps=4,   # 4-step fast mode: ~6x faster than default 25
        decode_chunk_size=4,
        motion_bucket_id=100,
        noise_aug_strength=0.02,
        generator=gen,
    ).frames[0]

    fdir = f'/content/dark_files/clips/_svdf_{scene_idx:03d}'
    os.makedirs(fdir, exist_ok=True)
    for fi, fr in enumerate(frames):
        fr.save(f'{fdir}/f{fi:04d}.png')

    raw = f'/content/dark_files/clips/_svdr_{scene_idx:03d}.mp4'
    subprocess.run([
        'ffmpeg', '-y', '-framerate', str(SVD_FPS),
        '-i', f'{fdir}/f%04d.png',
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-pix_fmt', 'yuv420p',
        raw,
    ], capture_output=True, check=True)
    subprocess.run([
        'ffmpeg', '-y', '-stream_loop', '-1', '-i', raw, '-i', audio_path,
        '-map', '0:v', '-map', '1:a',
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-shortest',
        out_path,
    ], capture_output=True, check=True)
    shutil.rmtree(fdir, ignore_errors=True)
    if os.path.exists(raw): os.remove(raw)

# ── Phase 2 loop ─────────────────────────────────────────────────────────────
print(f"Phase 2  SVD clips  (4-step fast mode)\\n{'='*65}")
clip_paths = []
_svd_ok = _kb_n = _resumed = 0
t0 = time.time()

for i, (scene, dur, ap) in enumerate(zip(scenes, durations, audio_paths)):
    local_clip = f'/content/dark_files/clips/clip_{i:03d}.mp4'
    clip_paths.append(local_clip)

    # Resume: already saved to Drive on a previous run
    if _ckpt and os.path.exists(_cc(i)):
        shutil.copy2(_cc(i), local_clip)
        _resumed += 1
        print(f"  {i+1}/{len(scenes)}  resumed from Drive"); continue

    print(f"  {i+1}/{len(scenes)}  ({dur:.1f}s)  {scene[:52]}...")
    t1 = time.time()
    try:
        _svd_clip(img_paths[i], ap, local_clip, scene_idx=i)
        _svd_ok += 1; mode = "SVD"
    except Exception as _e:
        print(f"    SVD error ({str(_e)[:55]}) -> Ken Burns fallback")
        _ken_burns(img_paths[i], ap, local_clip, dur, idx=i)
        _kb_n += 1; mode = "KB"

    # Save to Drive immediately — work is never lost on disconnect
    if _ckpt:
        shutil.copy2(local_clip, _cc(i))

    done = _svd_ok + _kb_n
    eta  = (time.time() - t0) / done * (len(scenes) - i - 1) if done else 0
    print(f"    [{mode}]  {time.time()-t1:.0f}s  |  ETA: ~{eta/60:.1f} min")

del svd_pipe
torch.cuda.empty_cache()
print(f"\\nAll clips done  |  total: {(time.time()-t0)/60:.1f} min")
print(f"  SVD: {_svd_ok}   Ken Burns: {_kb_n}   Resumed: {_resumed}/{len(scenes)}")
""")

CELL_MUSIC = code("""\
# ── STEP 8: Generate dark ambient background music ───────────────
import glob as _glob_mod, json as _json_mod, subprocess as _sp_mod
from transformers import pipeline as hf_pipeline
import wave, numpy as np, torch

# Free GPU memory from prior models (already done if Cell 7 ran in this session)
if 'pipe'     in dir(): del pipe
if 'svd_pipe' in dir(): del svd_pipe
torch.cuda.empty_cache()

# Session restart recovery
if 'DEVICE' not in dir():
    DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

if 'total_duration' not in dir():
    _afiles = sorted(_glob_mod.glob('/content/dark_files/audio/scene_???.mp3'))
    if not _afiles:
        raise RuntimeError("No audio files found. Run Cell 9 (Voiceover) first.")
    def _ap_dur(_a):
        _r = _sp_mod.run(['ffprobe','-v','quiet','-print_format','json','-show_format', _a],
                         capture_output=True, text=True)
        if _r.returncode != 0 or not _r.stdout.strip():
            raise RuntimeError(f"ffprobe failed on {_a}: {_r.stderr[:200]}")
        return float(_json_mod.loads(_r.stdout)['format']['duration'])
    total_duration = sum(_ap_dur(_a) for _a in _afiles)
    print(f"Recovered total_duration = {total_duration:.1f}s from {len(_afiles)} audio files")

print("Loading MusicGen-small ...")
music_pipe = hf_pipeline(
    'text-to-audio',
    'facebook/musicgen-small',
    device=0 if DEVICE == 'cuda' else -1,
)

MUSIC_PROMPT = (
    "dark ambient music, mysterious thriller documentary, tense suspenseful atmosphere, "
    "slow deep bass drones, ominous low-frequency hum, haunting cinematic orchestral score, "
    "psychological thriller, minimal slow tempo, no vocals, instrumental only, eerie"
)

print("Generating dark ambient loop ...")
music = music_pipe(MUSIC_PROMPT, forward_params={"do_sample": True, "max_new_tokens": 1500})

# Handle both list and dict output formats across transformers versions
audio_data = music[0] if isinstance(music, list) else music
sr         = audio_data['sampling_rate']
_arr       = audio_data['audio']
if _arr.ndim == 2:
    _arr = _arr.mean(axis=0)   # stereo -> mono
_pcm = (_arr * 32767).clip(-32768, 32767).astype(np.int16)

# Write WAV using built-in wave module — no scipy dependency
raw_wav = '/content/dark_files/audio/music_raw.wav'
with wave.open(raw_wav, 'w') as _wf:
    _wf.setnchannels(1)
    _wf.setsampwidth(2)
    _wf.setframerate(sr)
    _wf.writeframes(_pcm.tobytes())

# Loop to match full video duration + fade out
music_wav = '/content/dark_files/audio/music_final.wav'
fade_start = max(0, total_duration - 4)
subprocess.run([
    'ffmpeg', '-stream_loop', '-1', '-i', raw_wav,
    '-t', str(total_duration + 2),
    '-af', f'afade=t=out:st={fade_start:.1f}:d=4',
    '-c:a', 'pcm_s16le', music_wav, '-y'
], capture_output=True, check=True)

del music_pipe
torch.cuda.empty_cache()
print(f"Music ready ({total_duration:.0f}s, fades out at end)")
""")

CELL_ASSEMBLE = code("""\
# ── STEP 9: Assemble clips with fade transitions ─────────────────
#  Each clip already carries its own voiceover audio (embedded in Step 7).
#  We apply fades, concatenate, then feed into color grade.
import glob as _glob_mod, json as _json_mod, subprocess, os

# Session restart recovery
if 'clip_paths' not in dir():
    clip_paths = sorted(_glob_mod.glob('/content/dark_files/clips/clip_???.mp4'))
    if not clip_paths:
        raise RuntimeError("No clip files found. Run Cell 7 (Generate clips) first.")
    print(f"Recovered {len(clip_paths)} clip paths from disk.")

if 'durations' not in dir():
    _afiles = sorted(_glob_mod.glob('/content/dark_files/audio/scene_???.mp3'))
    if not _afiles:
        raise RuntimeError("No audio files found. Run Cell 9 (Voiceover) first.")
    def _ap_dur9(_a):
        _r = subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_format', _a],
                            capture_output=True, text=True)
        if _r.returncode != 0 or not _r.stdout.strip():
            raise RuntimeError(f"ffprobe failed on {_a}: {_r.stderr[:200]}")
        return float(_json_mod.loads(_r.stdout)['format']['duration'])
    durations = [_ap_dur9(_a) for _a in _afiles]
    print(f"Recovered {len(durations)} durations from audio files.")

_n_clips = len(clip_paths)

def add_fades(src, dst, dur, fade_dur=0.4):
    fade_out_start = max(0, dur - fade_dur)
    subprocess.run([
        'ffmpeg', '-y', '-i', src,
        '-vf', (f'fade=t=in:st=0:d={fade_dur},'
                f'fade=t=out:st={fade_out_start:.2f}:d={fade_dur}'),
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-pix_fmt', 'yuv420p',
        '-c:a', 'copy',   # preserve audio stream — already synced
        dst
    ], capture_output=True, check=True)

print("Adding fade transitions to each clip ...")
faded_paths = []
for i, (cp, dur) in enumerate(zip(clip_paths, durations)):
    fp = f'/content/dark_files/clips/clip_{i:03d}_faded.mp4'
    add_fades(cp, fp, dur)
    faded_paths.append(fp)
    print(f"  Clip {i+1}/{_n_clips} faded")

# Concatenate all faded clips — audio (voiceover) is already embedded per clip
concat_list = '/content/dark_files/concat.txt'
with open(concat_list, 'w') as f:
    for p in faded_paths:
        f.write(f"file '{p}'\\n")

video_with_voice = '/content/dark_files/final/video_raw.mp4'
subprocess.run([
    'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
    '-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '192k',
    video_with_voice
], capture_output=True, check=True)
print("\\nAll clips assembled — voiceover perfectly synced to each scene.")
""")

CELL_GRADE = code("""\
# ── STEP 10: Apply Dark Files cinematic color grade ──────────────
import os, subprocess

if 'video_with_voice' not in dir():
    video_with_voice = '/content/dark_files/final/video_raw.mp4'
if not os.path.exists(video_with_voice):
    raise RuntimeError(f"Assembly output not found: {video_with_voice}  Run Cell 9 (Assemble) first.")

print("🎨  Applying Dark Files color grade ...")
print("    → Cold blue channel shift")
print("    → Crushed blacks + compressed highlights")
print("    → Desaturated tones (0.65 saturation)")
print("    → High contrast (1.3)")
print("    → Subtle film grain")

DARK_FILES_GRADE = ",".join([
    # Hollywood teal-orange look: teal in shadows, warm in highlights
    "colorchannelmixer=rr=1.02:rg=0.0:rb=-0.02:gr=-0.01:gg=0.98:gb=0.03:br=-0.02:bg=0.05:bb=1.0",
    # Lift blacks slightly (cinematic) + gentle S-curve
    "curves=r='0/0.02 0.5/0.52 1/0.98':g='0/0.01 0.5/0.50 1/0.99':b='0/0.03 0.5/0.51 1/0.97'",
    # Slight saturation boost, gentle contrast — keep it vivid and beautiful
    "eq=saturation=1.05:contrast=1.08:brightness=0.0:gamma=1.0",
    # Barely-there film grain — just enough for texture
    "noise=alls=1:allf=t",
    # Gentle sharpening for crisp detail
    "unsharp=5:5:0.4:3:3:0.0"
])

video_graded = '/content/dark_files/final/video_graded.mp4'
subprocess.run([
    'ffmpeg', '-i', video_with_voice,
    '-vf', DARK_FILES_GRADE,
    '-c:v', 'libx264', '-crf', '17', '-preset', 'slow',
    '-c:a', 'copy',
    video_graded, '-y'
], check=True, capture_output=True)

print("\\n✅  Dark Files color grade applied!")
""")

CELL_CAPTIONS = code("""\
# ── STEP 11: Build + burn synced captions ───────────────────────
import glob as _glob_mod, json as _json_mod, subprocess, os, re

if 'video_graded' not in dir():
    video_graded = '/content/dark_files/final/video_graded.mp4'
if not os.path.exists(video_graded):
    raise RuntimeError(f"Graded video not found: {video_graded}  Run Cell 10 (Color grade) first.")

if 'vtt_paths' not in dir():
    vtt_paths = sorted(_glob_mod.glob('/content/dark_files/audio/scene_???.vtt'))
    if not vtt_paths:
        raise RuntimeError("No VTT files found. Run Cell 9 (Voiceover) first.")
    print(f"Recovered {len(vtt_paths)} VTT paths from disk.")

if 'durations' not in dir():
    _afiles = sorted(_glob_mod.glob('/content/dark_files/audio/scene_???.mp3'))
    def _ap_dur11(_a):
        _r = subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_format', _a],
                            capture_output=True, text=True)
        if _r.returncode != 0 or not _r.stdout.strip():
            raise RuntimeError(f"ffprobe failed on {_a}: {_r.stderr[:200]}")
        return float(_json_mod.loads(_r.stdout)['format']['duration'])
    durations = [_ap_dur11(_a) for _a in _afiles]
    print(f"Recovered {len(durations)} durations from disk.")

def vtt_time_to_ms(t):
    t = t.strip().replace(',','.')
    parts = t.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return (int(h)*3600 + int(m)*60 + float(s)) * 1000
    m, s = parts
    return (int(m)*60 + float(s)) * 1000

def ms_to_srt(ms):
    ms = int(ms)
    h  = ms // 3_600_000; ms %= 3_600_000
    m  = ms // 60_000;    ms %= 60_000
    s  = ms // 1_000;     ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

print("📝  Building synced SRT caption file ...")
entries, idx, offset_ms = [], 1, 0

for vp, dur in zip(vtt_paths, durations):
    try:
        with open(vp, encoding='utf-8') as f:
            content = f.read()
        for block in re.split(r'\\n{2,}', content.strip()):
            if '-->' not in block:
                continue
            lines = block.strip().splitlines()
            t_line = next((l for l in lines if '-->' in l), None)
            if not t_line:
                continue
            text = ' '.join(
                l for l in lines
                if '-->' not in l and not l.strip().isdigit() and l.strip()
            )
            if not text:
                continue
            s_str, e_str = t_line.split('-->')
            s_ms = vtt_time_to_ms(s_str) + offset_ms
            e_ms = vtt_time_to_ms(e_str) + offset_ms
            entries.append((idx, ms_to_srt(s_ms), ms_to_srt(e_ms), text))
            idx += 1
    except Exception as ex:
        print(f"  ⚠️   VTT parse warning for {vp}: {ex}")
    offset_ms += dur * 1000

srt_path = '/content/dark_files/audio/captions.srt'
with open(srt_path, 'w', encoding='utf-8') as f:
    for n, s, e, t in entries:
        f.write(f"{n}\\n{s} --> {e}\\n{t}\\n\\n")
print(f"  ✅  {len(entries)} caption entries generated")

# Burn captions with Dark Files styling
CAPTION_STYLE = (
    "FontName=Arial,Bold=1,FontSize=17,"
    "PrimaryColour=&H00FFFFFF,"     # white text
    "OutlineColour=&H00000000,"     # black outline
    "BackColour=&H55000000,"        # semi-transparent black box
    "BorderStyle=3,Outline=1.5,Shadow=0,"
    "Alignment=2,MarginV=28"        # bottom centre, 28px margin
)

video_captioned = '/content/dark_files/final/video_captioned.mp4'
subprocess.run([
    'ffmpeg', '-i', video_graded,
    '-vf', f"subtitles={srt_path}:force_style='{CAPTION_STYLE}'",
    '-c:v', 'libx264', '-crf', '17',
    '-c:a', 'copy',
    video_captioned, '-y'
], check=True, capture_output=True)

print("✅  Captions burned in!")
""")

CELL_MIX = code("""\
# ── STEP 12: Final audio mix (voice 100% + music 15%) ───────────
import glob as _glob_mod, os, re, json, subprocess

if 'EPISODE_TITLE' not in dir(): EPISODE_TITLE = 'The Classified Files'
if 'VOICE'         not in dir(): VOICE         = 'en-US-GuyNeural'
if 'entries'       not in dir(): entries       = []

if 'video_captioned' not in dir():
    video_captioned = '/content/dark_files/final/video_captioned.mp4'
if not os.path.exists(video_captioned):
    raise RuntimeError(f"Captioned video not found: {video_captioned}  Run Cell 11 first.")

if 'music_wav' not in dir():
    music_wav = '/content/dark_files/audio/music_final.wav'
if not os.path.exists(music_wav):
    raise RuntimeError(f"Music not found: {music_wav}  Run Cell 8 (Music) first.")

print("🎵  Mixing voiceover + background music ...")

safe_title  = re.sub(r'[^\\w\\s-]', '', EPISODE_TITLE).strip().replace(' ', '_')
final_video = f'/content/dark_files/final/DARK_FILES_{safe_title}.mp4'

subprocess.run([
    'ffmpeg',
    '-i', video_captioned,
    '-i', music_wav,
    '-filter_complex',
    '[0:a]volume=1.0[v];[1:a]volume=0.14[m];[v][m]amix=inputs=2:duration=first:dropout_transition=2[mix]',
    '-map', '0:v', '-map', '[mix]',
    '-c:v', 'copy',
    '-c:a', 'aac', '-b:a', '192k',
    '-shortest',
    final_video, '-y'
], check=True, capture_output=True)

# ── Final stats ──────────────────────────────────────────────────
r = subprocess.run(
    ['ffprobe','-v','quiet','-print_format','json','-show_format','-show_streams', final_video],
    capture_output=True, text=True
)
if r.returncode != 0 or not r.stdout.strip():
    raise RuntimeError(f"ffprobe failed on final video: {r.stderr[:200]}")
info = json.loads(r.stdout)
size_mb  = int(info['format']['size']) / (1024*1024)
vid_dur  = float(info['format']['duration'])
v_stream = next((s for s in info['streams'] if s['codec_type']=='video'), {})
width    = v_stream.get('width', 704)
height   = v_stream.get('height', 480)

print(f"\\n{'='*55}")
print(f"🎉  DARK FILES VIDEO COMPLETE!")
print(f"{'='*55}")
print(f"📁  File     : {os.path.basename(final_video)}")
print(f"⏱️   Duration : {vid_dur:.1f}s  ({vid_dur/60:.1f} min)")
print(f"📊  Size     : {size_mb:.1f} MB")
print(f"🎬  Res.     : {width}x{height} @ 25fps")
print(f"🎨  Grade    : Dark Files cinematic (cold blue, high contrast)")
print(f"🎙️   Voice    : {VOICE}")
print(f"📝  Captions : {len(entries)} synced entries")
print(f"🎵  Music    : Dark ambient (AI-generated, royalty-free)")
print(f"{'='*55}")
""")

CELL_DOWNLOAD = code("""\
# ── STEP 13: Save to Google Drive + download ─────────────────────

import glob as _glob_mod, os, re, shutil
from IPython.display import Video, display
from google.colab import files as colab_files

if 'EPISODE_TITLE' not in dir(): EPISODE_TITLE = 'The Classified Files'

if 'final_video' not in dir():
    _candidates = sorted(_glob_mod.glob('/content/dark_files/final/DARK_FILES_*.mp4'))
    if not _candidates:
        raise RuntimeError("Final video not found. Run Cell 12 (Audio mix) first.")
    final_video = _candidates[-1]
    print(f"Recovered final video: {final_video}")

# ── Mount Google Drive and save a permanent copy ─────────────────
try:
    from google.colab import drive
    drive.mount('/content/drive', force_remount=False)
    drive_folder = '/content/drive/MyDrive/DarkFiles'
    os.makedirs(drive_folder, exist_ok=True)
    safe_title = re.sub(r'[^\\w\\s-]', '', EPISODE_TITLE).strip().replace(' ', '_')
    drive_path  = f'{drive_folder}/DARK_FILES_{safe_title}.mp4'
    shutil.copy2(final_video, drive_path)
    print(f"Saved to Google Drive: DarkFiles/DARK_FILES_{safe_title}.mp4")
    print("Your video is safe — even if Colab disconnects.")
except Exception as e:
    print(f"Drive save skipped: {e}")

# ── Preview ──────────────────────────────────────────────────────
print("\\nLoading preview ...\\n")
try:
    display(Video(final_video, width=1024, height=576, embed=True))
except Exception:
    pass

# ── Download to your computer ────────────────────────────────────
print("\\nDownloading your Dark Files video to your computer ...")
colab_files.download(final_video)

print(\"\"\"
YOUR VIDEO IS READY FOR YOUTUBE

  MP4 container (H.264 + AAC)
  16:9 aspect ratio  |  25 fps  |  192 kbps audio
  Professional neural voiceover
  Cinematic color grade
  Dark ambient background music (royalty-free)

Your video is also saved permanently in Google Drive
under My Drive > DarkFiles

Pro tips after upload:
  - Add the thumbnail you generated in YouTube Studio
  - Paste the SEO description and tags
  - Add chapter markers for longer episodes
\"\"\")
""")

# ── ASSEMBLE NOTEBOOK ──────────────────────────────────────────────────────────

notebook = {
    "nbformat": 4,
    "nbformat_minor": 0,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python", "version": "3.10.12"},
        "accelerator": "GPU",
        "gpuClass": "standard",
        "colab": {
            "provenance": [],
            "gpuType": "T4",
            "name": "Dark Files — Complete YouTube Production System"
        }
    },
    "cells": [
        # ── System 1: Trend Intelligence ──────────────────────────
        CELL_TITLE,
        CELL_TREND_INSTALL,
        CELL_TREND_INTELLIGENCE,
        # ── System 2: Video Generator ─────────────────────────────
        CELL_GPU,
        CELL_INSTALL,
        CELL_IMPORTS,
        CELL_SCRIPT,
        CELL_PARSER,
        CELL_VOICEOVER,
        CELL_DARK_PROMPT_GEN,   # PATH A — image prompts (mirrors exact voiceover words)
        CELL_LOAD_MODEL,
        CELL_GEN_CLIPS,
        CELL_MUSIC,
        CELL_ASSEMBLE,
        CELL_GRADE,
        CELL_CAPTIONS,
        CELL_MIX,
        CELL_DOWNLOAD,
    ]
}

out = os.path.join(os.path.dirname(__file__), 'dark_files_generator.ipynb')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(notebook, f, indent=1, ensure_ascii=False)

print(f"✅  Notebook written → {out}")
print(f"    Cells: {len(notebook['cells'])}")
