"""
Build the Unlearned Video Generator Colab notebook.
Run: python build_notebook.py
Output: unlearned_generator.ipynb

UNLEARNED CHANNEL STYLE:
  Visual  : AI-generated stick figure drawings (SDXL) per scene
  Sync    : Each clip = exact TTS audio duration (frame-perfect)
  Voice   : en-US-AndrewNeural via edge-tts
  Music   : Ambient pentatonic drone (numpy + wave)
  Motion  : Ken Burns zoom per scene (alternating directions)
  Assembly: FFmpeg concat + amix
"""
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src}

def code(src):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": src}

# ── CELLS ──────────────────────────────────────────────────────────────────────

CELL_TITLE = md("""\
# UNLEARNED — Video Generator
### Psychology · Ancient History · Behavioral Science
---

## Choose your path after Cell 5:

### 🎨 PATH A — Canva (matches reference videos exactly)
Use Canva's Zidan Sasc stick figures — the exact same ones your reference channel uses.

| Cell | What it does |
|------|-------------|
| Cell 1 | Install packages |
| Cell 2 | Setup |
| Cell 3 | Mount Google Drive |
| Cell 4 | Set episode title |
| Cell 5 | Upload script → generates voiceover automatically |
| **Cell 6** | **Downloads a ZIP: one audio file per scene + scene_list.txt** |
| **Cell 7** | **Generates one image prompt per scene (for Midjourney / DALL-E / Ideogram)** |

Then open Canva (free at canva.com):
- Create a YouTube video design
- For each scene: add new page → upload `scene_XXXX.mp3` → timing is set automatically
- Elements → search `zidan sasc` → pick the right stick figure
- Export MP4 — done!

---

### 🤖 PATH B — Fully automated (no Canva needed)
Generates everything automatically using flat icons from the Iconify library. No GPU required.

| Cell | What it does |
|------|-------------|
| Cell 1–5 | Same as above |
| Cell 7 | Fetch icons + render scene images (~2 sec/scene) |
| Cell 8 | Generate background music |
| Cell 9 | Assemble the final video |
| Cell 10 | Save to Drive + download |

---
> **Recommendation:** Use Path A (Canva) for videos that look exactly like your reference. Use Path B for fully automated production with no manual steps.
""")

CELL_INSTALL = code('''\
# == CELL 1: Install ==========================================================
print("Installing packages — runs once per session (~2 min)...")
import subprocess, sys

def _sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

# libcairo2 is needed by cairosvg to convert SVG icons to PNG
_sh(["apt-get", "install", "-y", "-q", "ffmpeg", "libcairo2"])
print("  ffmpeg + libcairo2: ok")

_pkgs = ["cairosvg", "requests", "Pillow", "edge-tts", "nest_asyncio"]
for _pkg in _pkgs:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", _pkg], capture_output=True)
    print(f"  {_pkg}: ok")

print("\\nDone! Run Cell 2.")
''')

CELL_SETUP = code('''\
# == CELL 2: Setup ============================================================
# No GPU required — icons are fetched from the Iconify API (free, no key needed).
import os, json, re, subprocess, asyncio
import nest_asyncio
nest_asyncio.apply()

WORK_DIR  = "/content/unlearned"
IMG_DIR   = f"{WORK_DIR}/images"
AUDIO_DIR = f"{WORK_DIR}/audio"
CLIP_DIR  = f"{WORK_DIR}/clips"
for _d in [WORK_DIR, IMG_DIR, AUDIO_DIR, CLIP_DIR]:
    os.makedirs(_d, exist_ok=True)

VOICE       = "en-US-AndrewNeural"
VOICE_RATE  = "+2%"
VOICE_PITCH = "-3Hz"
MUSIC_VOL   = 0.08

print(f"Working directory : {WORK_DIR}")
print(f"Voice             : {VOICE}")
print("\\nSetup complete — no GPU needed, no model download!")
print("Run Cell 3.")
''')

CELL_DRIVE = code('''\
# == CELL 3: Mount Google Drive ================================================
from google.colab import drive
drive.mount("/content/drive", force_remount=False)

DRIVE_FOLDER = "/content/drive/MyDrive/Unlearned"
os.makedirs(DRIVE_FOLDER, exist_ok=True)
print(f"Drive ready: {DRIVE_FOLDER}")
print("\\nDrive mounted. Run Cell 4.")
''')

CELL_TITLE_INPUT = code('''\
# == CELL 4: Set Episode Title =================================================
# Type your episode title in the box below, then click Set Title.
# Do NOT paste your script here — that happens in Cell 5 via file upload.

import ipywidgets as widgets
from IPython.display import display, clear_output

_title_box = widgets.Text(
    value="Episode 1 Your Title Here",
    description="Title:",
    layout=widgets.Layout(width="90%"),
    style={"description_width": "60px"},
)
_btn = widgets.Button(description="Set Title", button_style="success",
                      layout=widgets.Layout(width="200px"))
_out = widgets.Output()

def _set(_):
    global EPISODE_TITLE
    EPISODE_TITLE = _title_box.value.strip()
    with _out:
        clear_output()
        if not EPISODE_TITLE:
            print("Type your episode title first!")
        else:
            with open(f\'{WORK_DIR}/episode_title.txt\', \'w\') as _f:
                _f.write(EPISODE_TITLE)
            print(f"Title saved: {EPISODE_TITLE}")
            print("Now run Cell 5 to upload your script as a .txt file.")

_btn.on_click(_set)
display(_title_box, _btn, _out)
''')

CELL_UPLOAD_VOICE = code('''\
# == CELL 5: Upload Script & Generate Voiceover ================================
# 1. Run this cell.
# 2. A "Choose Files" button will appear — click it.
# 3. Select your script saved as a plain .txt file from your computer.
# 4. The voiceover will generate automatically. Do NOT paste script text here.

from google.colab import files as _gcf
import edge_tts, asyncio, re, json
import nest_asyncio; nest_asyncio.apply()

if "EPISODE_TITLE" not in dir() or not EPISODE_TITLE:
    raise RuntimeError("Run Cell 4 first and click Set Title!")

def parse_scenes(text, max_words=22):
    text = re.sub(r\'[ \\t]+\', \' \', text.strip())
    sentences = re.split(r\'(?<=[.!?])\\s+\', text)
    scenes, chunk, wc = [], [], 0
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        w = len(sent.split())
        if wc + w > max_words and chunk:
            scenes.append(\' \'.join(chunk))
            chunk, wc = [sent], w
        else:
            chunk.append(sent)
            wc += w
    if chunk:
        scenes.append(\' \'.join(chunk))
    return [s for s in scenes if s.strip()]

def get_duration(path):
    r = subprocess.run(
        [\'ffprobe\', \'-v\', \'quiet\', \'-print_format\', \'json\', \'-show_format\', path],
        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"ffprobe failed on {path}: {r.stderr[:200]}")
    return float(json.loads(r.stdout)[\'format\'][\'duration\'])

async def _tts(text, path):
    comm = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, pitch=VOICE_PITCH)
    await comm.save(path)

# -- Upload script file --------------------------------------------------------
print("Click Choose Files below and select your script as a .txt file.")
print("Your script can contain any characters (dashes, apostrophes, etc.)\\n")
_up = _gcf.upload()
if not _up:
    raise RuntimeError("No file uploaded. Run this cell again.")

_fname = list(_up.keys())[0]
_raw = _up[_fname].decode("utf-8", errors="replace").strip()
_wc = len(_raw.split())
_est = round(_wc / 2.8 / 60, 1)
print(f"\\nLoaded : {_fname}")
print(f"Words  : {_wc}  (~{_est} min video)")

# -- Parse & generate voiceover ------------------------------------------------
print("\\nParsing script...")
_raw_scenes = parse_scenes(_raw)
print(f"  {len(_raw_scenes)} scenes")

print("\\nGenerating voiceover (edge-tts)...")
SCENE_DATA = []
import time as _time
_loop = asyncio.get_event_loop()
for _i, _text in enumerate(_raw_scenes):
    _audio = f\'{AUDIO_DIR}/scene_{_i:04d}.mp3\'
    for _try in range(3):
        try:
            _loop.run_until_complete(_tts(_text, _audio))
            break
        except Exception as _e:
            if _try == 2:
                raise RuntimeError(f"TTS failed for scene {_i+1} after 3 tries: {_e}")
            _time.sleep(2)
    _dur = get_duration(_audio)
    SCENE_DATA.append({
        \'idx\':     _i,
        \'text\':    _text,
        \'duration\': _dur,
        \'audio\':   _audio,
        \'image\':   f\'{IMG_DIR}/scene_{_i:04d}.png\',
    })
    _suf = "..." if len(_text) > 55 else ""
    print(f"  [{_i+1}/{len(_raw_scenes)}] {_dur:.1f}s  {_text[:55]}{_suf}")

with open(f\'{WORK_DIR}/scene_data.json\', \'w\') as _f:
    json.dump(SCENE_DATA, _f, indent=2, ensure_ascii=False)

_total = sum(s[\'duration\'] for s in SCENE_DATA)
print(f"\\nTotal : {_total:.0f}s  ({_total/60:.1f} min)  |  Scenes: {len(SCENE_DATA)}")
print("\\nVoiceover done. Run Cell 6.")
''')

CELL_CANVA_EXPORT = code('''\
# == CELL 6 (PATH A): Canva Export ============================================
# Run this cell to download everything you need to finish the video in Canva.
#
# What you get:
#   scene_list.txt  — tells you the text + suggested stick figure for every scene
#   scene_XXXX.mp3  — one audio file per scene (timing is already perfect)
#
# In Canva (free at canva.com):
#   1. Create design → YouTube video (16:9)
#   2. For Scene 1: add a new page → upload scene_0000.mp3
#      Canva sets the page duration automatically — timing matches perfectly!
#   3. Click Elements → search "zidan sasc" → pick a stick figure that fits
#   4. Repeat for every scene (scene_0001.mp3, scene_0002.mp3, ...)
#   5. Export as MP4
# =============================================================================
import json, os, zipfile, re as _re
from google.colab import files as _cf

if "WORK_DIR"   not in dir(): WORK_DIR   = "/content/unlearned"
if "AUDIO_DIR"  not in dir(): AUDIO_DIR  = f"{WORK_DIR}/audio"
if "EPISODE_TITLE" not in dir():
    _tp = f"{WORK_DIR}/episode_title.txt"
    EPISODE_TITLE = open(_tp).read().strip() if os.path.exists(_tp) else "Episode"

if "SCENE_DATA" not in dir():
    _jpath = f"{WORK_DIR}/scene_data.json"
    if not os.path.exists(_jpath):
        raise RuntimeError("scene_data.json not found. Run Cell 5 first.")
    with open(_jpath) as _f:
        SCENE_DATA = json.load(_f)

_n     = len(SCENE_DATA)
_total = sum(s["duration"] for s in SCENE_DATA)

# ── Build scene_list.txt ──────────────────────────────────────────────────────
_lines = []
_lines.append(f"EPISODE : {EPISODE_TITLE}")
_lines.append(f"SCENES  : {_n}   TOTAL: {_total:.0f}s ({_total/60:.1f} min)")
_lines.append("=" * 65)
_lines.append("")
_lines.append("HOW TO USE IN CANVA")
_lines.append("-" * 30)
_lines.append("1. canva.com → Create design → YouTube video (16:9)")
_lines.append("2. For each scene below:")
_lines.append("     • Add a new page in Canva")
_lines.append("     • Upload the scene audio file listed (e.g. scene_0001.mp3)")
_lines.append("     • Canva auto-sets the page duration → timing is perfect!")
_lines.append("3. Click Elements → search the suggestion below → pick stick figure")
_lines.append("4. Export MP4 when done")
_lines.append("")
_lines.append("=" * 65)
_lines.append("")

for _sc in SCENE_DATA:
    _i   = _sc["idx"]
    _dur = _sc["duration"]
    _txt = _sc["text"]
    _aud = os.path.basename(_sc["audio"])
    _low = _txt.lower()

    # Suggest the most relevant Canva search term per scene content
    if any(w in _low for w in ["sad","cry","depress","grief","upset","hurt"]):
        _hint = "zidan sasc sad"
    elif any(w in _low for w in ["happy","joy","excit","celebrat","laugh","smile"]):
        _hint = "zidan sasc happy"
    elif any(w in _low for w in ["angry","anger","rage","frustrat","mad"]):
        _hint = "zidan sasc angry"
    elif any(w in _low for w in ["fear","scared","anxious","worry","stress","panic"]):
        _hint = "zidan sasc fear"
    elif any(w in _low for w in ["think","thought","brain","mind","idea","memory","imagine"]):
        _hint = "zidan sasc thinking"
    elif any(w in _low for w in ["talk","speak","say","tell","listen","voice","conversation"]):
        _hint = "zidan sasc talking"
    elif any(w in _low for w in ["friend","together","group","team","social","meet","people"]):
        _hint = "zidan sasc friends"
    elif any(w in _low for w in ["alone","lonely","isolat","introvert","quiet","silence"]):
        _hint = "zidan sasc alone"
    elif any(w in _low for w in ["work","job","career","boss","office","business","money","success"]):
        _hint = "zidan sasc work"
    elif any(w in _low for w in ["learn","study","school","book","read","knowledge","teach"]):
        _hint = "zidan sasc reading"
    elif any(w in _low for w in ["walk","run","move","action","step","exercise"]):
        _hint = "zidan sasc walking"
    elif any(w in _low for w in ["phone","social media","internet","post","online","screen"]):
        _hint = "zidan sasc phone"
    elif any(w in _low for w in ["sleep","rest","tired","exhaust","relax"]):
        _hint = "zidan sasc sleeping"
    elif any(w in _low for w in ["confus","lost","question","wonder","unsure","doubt"]):
        _hint = "zidan sasc confused"
    elif any(w in _low for w in ["power","strong","control","leader","authority","dominan"]):
        _hint = "zidan sasc strong"
    else:
        # Extract the 2 most meaningful words as a search hint
        _kws = [w for w in _re.findall(r"[a-zA-Z]{5,}", _txt) if w.lower() not in
                {"that","this","with","from","they","them","their","have","been","were",
                 "would","could","should","about","after","before","while","these","those"}]
        _hint = f"zidan sasc   OR   search: {' '.join(_kws[:2]).lower()}" if _kws else "zidan sasc"

    _lines.append(f"┌─ SCENE {_i+1:03d}  ({_dur:.1f}s)  →  {_aud}")
    _lines.append(f"│  {_txt}")
    _lines.append(f"└─ Canva search: {_hint}")
    _lines.append("")

_txt_path = f"{WORK_DIR}/scene_list.txt"
with open(_txt_path, "w", encoding="utf-8") as _f:
    _f.write("\\n".join(_lines))

# ── Build ZIP ─────────────────────────────────────────────────────────────────
_safe     = _re.sub(r"[^\\w\\s-]+", "", EPISODE_TITLE).strip().replace(" ", "_")
_zip_path = f"{WORK_DIR}/CANVA_{_safe}.zip"

with zipfile.ZipFile(_zip_path, "w", zipfile.ZIP_DEFLATED) as _zf:
    _zf.write(_txt_path, "scene_list.txt")
    for _sc in SCENE_DATA:
        _ap = _sc["audio"]
        if os.path.exists(_ap):
            _zf.write(_ap, os.path.basename(_ap))

_mb = os.path.getsize(_zip_path) / 1_048_576
print(f"✅  ZIP ready  ({_mb:.1f} MB)")
print(f"    scene_list.txt  — {_n} scenes with Canva search suggestions")
print(f"    {_n} x scene_XXXX.mp3 — one audio per scene, timing is perfect")
print("\\nDownloading now...")
_cf.download(_zip_path)
print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 NEXT STEPS IN CANVA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 1. canva.com → Create design → YouTube video
 2. Scene 1: new page → upload scene_0000.mp3
    → page duration sets automatically!
 3. Elements → search "zidan sasc" → pick figure
 4. Repeat for every scene in scene_list.txt
 5. Export MP4
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
''')

CELL_PROMPT_GEN = code('''\
# == CELL 7: Generate Image Prompts ============================================
# Reads your scene voiceover text and outputs a ready-to-use image prompt for
# every scene — formatted for Midjourney, DALL-E, or any AI image generator.
# Downloads prompts_XXXX.txt automatically when done.
# =============================================================================
import json, os, re
from google.colab import files as _cf

if "WORK_DIR" not in dir(): WORK_DIR = "/content/unlearned"
if "SCENE_DATA" not in dir():
    _jp = f"{WORK_DIR}/scene_data.json"
    if not os.path.exists(_jp):
        raise RuntimeError("Run Cell 5 first.")
    with open(_jp) as _f:
        SCENE_DATA = json.load(_f)
if "EPISODE_TITLE" not in dir():
    _tp = f"{WORK_DIR}/episode_title.txt"
    EPISODE_TITLE = open(_tp).read().strip() if os.path.exists(_tp) else "Episode"

_ANCHOR = (
    "Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, "
    "slightly imperfect sketchy marker lines,"
)
_LOCK = (
    "no gradients, no shadows, no textures, no photorealism, no 3D, "
    "16:9 aspect ratio, educational YouTube explainer doodle style."
)

_STOPS = set((
    "a an the in on at is was are were it its of to and or but for with by "
    "from this that they them their we our you your he she his her not no as "
    "so be been has have had do does did will would could should may might also "
    "just than then when where who what how why if all one two three first last "
    "into out up about more most some any each every can there here now after "
    "before during while because since though although like even get very much "
    "many such way make made use used using take took time know think say see "
    "come went back new old other both own long well still only over day year "
    "life same become through again those these that"
).split())

def _bg(text):
    w = text.lower()
    if any(x in w for x in ["ancient","prehistoric","cave","fossil","million year","egypt","rome","babylon","mesopotamia","empire"]):
        return "tan (#C4965A) background"
    if any(x in w for x in ["danger","threat","predator","attack","kill","dead","blood","murder","deadly","poison","virus"]):
        return "stark white background, bold red ALL CAPS danger text at top of frame"
    if any(x in w for x in ["happy","joy","triumph","discover","excit","win","success","celebrat","achieve"]):
        return "bright white (#FFFFFF) background"
    if any(x in w for x in ["underwater","ocean","sea","deep","marine","fish","shark","whale","swim"]):
        return "solid cobalt blue (#2D5FBF) background"
    if any(x in w for x in ["nature","forest","tree","plant","evolv","jungle","grass","wild","environment","outdoor"]):
        return "flat green ground strip (#3A9E3A) at bottom, solid sky blue (#6EB5E8) upper half"
    if any(x in w for x in ["fire","night","ritual","torch","dark","primitive","tribe","sunset","cave","ancient flame"]):
        return "solid orange (#F5820D) background"
    if any(x in w for x in ["science","lab","research","experiment","chemical","atom","cell","dna","microscope"]):
        return "solid cobalt blue (#2D5FBF) background"
    return "white (#FFFFFF) background"

def _frame(text):
    w = text.lower()
    if re.match(r"^\\d+[.):] ", text.strip()) and len(text.split()) <= 12:
        return "concept_text"
    if any(x in w for x in ["evolv","progress","develop","transform","became","stages","steps","million year","sequence","from","to"]):
        return "evolution"
    if any(x in w for x in ["brain","stress","anxiety","fear","dopamine","cortisol","ego","addiction","trauma","cortex"]):
        return "villain"
    if any(x in w for x in ["why","wonder","confus","unsure","but wait","what if","hmm","question"]):
        return "reaction"
    if any(x in w for x in ["world","globe","earth","planet","global","everywhere","species","million"]):
        return "globe"
    if any(x in w for x in ["called","known as","named","labeled","type of","kind of","part of"]):
        return "diagram"
    return "scene"

def _action(text):
    w = text.lower()
    if any(x in w for x in ["run","chase","escape","flee"]): return "a stick figure sprinting with motion lines behind it"
    if any(x in w for x in ["talk","speak","shout","yell","tell"]): return "a stick figure with an open mouth and a speech bubble floating beside it"
    if any(x in w for x in ["think","wonder","imagine","consider","thought"]): return "a stick figure with a large cloud-shaped thought bubble above its head reading HMMMM in bold caps"
    if any(x in w for x in ["sad","cry","grief","depress","hurt"]): return "a stick figure with a downturned mouth, shoulders slumped, small blue teardrops falling"
    if any(x in w for x in ["angry","rage","frustrat","mad"]): return "a stick figure with thick angry brow lines, fists raised, red steam lines from head"
    if any(x in w for x in ["happy","joy","excit","smile","laugh","celebrat"]): return "a stick figure with a wide smile and arms raised in a V above its head"
    if any(x in w for x in ["fear","scared","panic","anxious","stress"]): return "a stick figure frozen with wide circle eyes and jagged shock lines radiating outward"
    if any(x in w for x in ["read","study","learn","book"]): return "a stick figure sitting cross-legged holding an open book, a small lightbulb above its head"
    if any(x in w for x in ["sleep","rest","tired","exhaust"]): return "a stick figure lying flat with ZZZ letters floating above"
    if any(x in w for x in ["confus","lost","unsure","doubt"]): return "a stick figure with a large ? above its head and arms shrugged outward"
    if any(x in w for x in ["work","job","boss","office","business"]): return "a stick figure sitting at a flat desk with a simple laptop shape in front of it"
    if any(x in w for x in ["walk","step","move","march"]): return "a stick figure mid-stride with one foot raised"
    return "a stick figure standing upright facing forward with neutral expression"

def _concept(text):
    words = [w for w in re.findall(r"\\b[A-Za-z]{5,}\\b", text) if w.lower() not in _STOPS]
    return words[0].upper() if words else "CONCEPT"

def _build(scene):
    text = scene["text"]
    bg   = _bg(text)
    ft   = _frame(text)
    act  = _action(text)
    con  = _concept(text)

    if ft == "concept_text":
        mid = (f"large bold ALL CAPS white marker text \\"{text[:45].upper()}...\\" centered on a dark red (#7B0000) "
               f"background, white horizontal decorative lines above and below the text,")
    elif ft == "evolution":
        mid = (f"left-to-right progression of three chunky cartoon figures connected by thick black right-pointing "
               f"arrows, each figure slightly more advanced, bold ALL CAPS labels EARLY / MIDDLE / NOW below each stage, {bg},")
    elif ft == "villain":
        mid = (f"chunky cartoon {con.lower()} blob with an angry cartoon face — thick brow lines, clenched cartoon "
               f"fists, bold ALL CAPS label \\"{con}\\" in red at top of frame, {bg},")
    elif ft == "reaction":
        mid = (f"{act}, with bold ALL CAPS text \\"WAIT...\\" inside a classic cloud thought bubble above the "
               f"figure\\'s head, {bg},")
    elif ft == "globe":
        mid = (f"chunky cartoon Earth globe centered, surrounded by small floating cartoon creatures and simple "
               f"flat icons, bold ALL CAPS label \\"{con}\\" at top of frame, {bg},")
    elif ft == "diagram":
        mid = (f"{act}, a yellow diagonal arrow pointing at the figure with bold ALL CAPS label \\"{con}\\" "
               f"beside the arrowhead, {bg},")
    else:
        mid = f"{act}, {bg},"

    return f"{_ANCHOR} {mid} {_LOCK}"

# ── Generate prompts ──────────────────────────────────────────────────────────
print(f"Generating {len(SCENE_DATA)} image prompts...\\n")
_lines = [f"IMAGE PROMPTS — {EPISODE_TITLE}", "=" * 65, ""]

for _sc in SCENE_DATA:
    _i   = _sc["idx"]
    _dur = _sc["duration"]
    _txt = _sc["text"]
    _p   = _build(_sc)
    print(f"  [{_i+1}] {_txt[:60]}...")
    _lines.append(f"── SCENE {_i+1:03d}  ({_dur:.1f}s) ──────────────────────────────────")
    _lines.append(f"NARRATION : {_txt}")
    _lines.append(f"PROMPT    : {_p}")
    _lines.append("")

_safe = re.sub(r"[^\\w\\s-]+", "", EPISODE_TITLE).strip().replace(" ", "_")
_out  = f"{WORK_DIR}/prompts_{_safe}.txt"
with open(_out, "w", encoding="utf-8") as _f:
    _f.write("\\n".join(_lines))

print(f"\\n✅  {len(SCENE_DATA)} prompts saved.")
print("Downloading prompts file now...")
_cf.download(_out)
print("\\nOpen prompts_XXXX.txt — copy each prompt into Midjourney / DALL-E / Ideogram.")
''')

CELL_IMAGES = code('''\
# == CELL 7 (PATH B): Fetch Icons & Render Scene Images =======================
# Session-restart safe. Checks cached images first — reruns skip instantly.
# Uses Iconify API (free, 150 k+ icons, no key) + cairosvg + Pillow.
# No GPU needed. ~2 seconds per scene.
import json as _json, os, re, io, requests
import cairosvg
from PIL import Image, ImageDraw, ImageFont

_WDIR  = "/content/unlearned"
_IDIR  = f"{_WDIR}/images"
_JPATH = f"{_WDIR}/scene_data.json"
os.makedirs(_IDIR, exist_ok=True)

if "SCENE_DATA" not in dir():
    if not os.path.exists(_JPATH):
        raise RuntimeError("scene_data.json not found. Run Cell 5 first.")
    with open(_JPATH) as _f:
        SCENE_DATA = _json.load(_f)

_n       = len(SCENE_DATA)
_missing = [_sc for _sc in SCENE_DATA if not os.path.exists(_sc["image"])]

if not _missing:
    print(f"All {_n} images already on disk. Run Cell 7.")
else:
    # ── Stop-word list for keyword extraction ──────────────────────────────────
    _STOPS = set((
        "a an the in on at is was are were it its of to and or but for with by "
        "from this that they them their we our you your he she his her not no as "
        "so be been has have had do does did will would could should may might also "
        "just than then when where who which what how why if all one two three "
        "first last into out up about more most some any each every can there here "
        "now after before during while because since though although like even get "
        "got very much many such way make made use used using take took time "
        "know knew think thought say said see saw come came go went back new old "
        "other another both own long well still only over day year life same "
        "become became through between again those these"
    ).split())

    def _kw(text, n=4):
        words = re.findall(r"\\b[a-zA-Z]{4,}\\b", text.lower())
        seen, out = set(), []
        for w in words:
            if w not in _STOPS and w not in seen:
                seen.add(w); out.append(w)
        return out[:n]

    # ── Keyword → Iconify search term map (psychology/history/science topics) ──
    _MAP = {
        "brain":"brain","mind":"brain","think":"brain","thought":"brain","memory":"memory",
        "learn":"graduation-cap","study":"book-open","school":"school","book":"book-open",
        "knowledge":"brain","smart":"lightbulb","intelligence":"lightbulb","idea":"lightbulb",
        "happy":"smile","happiness":"smile","joy":"smile","laugh":"laugh",
        "sad":"frown","sadness":"frown","depress":"cloud-rain","grief":"frown",
        "angry":"angry","anger":"angry","rage":"angry","frustrat":"angry",
        "fear":"alert-triangle","anxiety":"alert-triangle","stress":"alert-circle","worry":"alert-circle",
        "calm":"leaf","peace":"dove","relax":"spa",
        "love":"heart","heart":"heart","emotion":"heart","feel":"heart",
        "friend":"users","social":"users","people":"users","group":"users","team":"users",
        "alone":"user","lonely":"user","person":"user","human":"user","individual":"user",
        "money":"dollar-sign","wealth":"dollar-sign","rich":"dollar-sign","poor":"coins",
        "work":"briefcase","job":"briefcase","career":"briefcase","boss":"briefcase",
        "success":"trophy","goal":"target","winner":"trophy","achieve":"star",
        "fail":"x-circle","mistake":"x-circle","error":"x-circle","wrong":"x-circle",
        "trust":"handshake","honest":"shield-check","lie":"eye-off","cheat":"eye-off",
        "power":"zap","strong":"shield","weak":"meh","control":"sliders",
        "leader":"crown","leader":"crown","authority":"crown","king":"crown",
        "change":"refresh-cw","grow":"trending-up","improve":"trending-up","progress":"trending-up",
        "time":"clock","clock":"clock","hour":"clock","minute":"clock","slow":"clock",
        "sleep":"moon","rest":"moon","tired":"moon","energy":"sun","wake":"sun",
        "food":"coffee","eat":"utensils","diet":"salad","health":"heart-pulse",
        "body":"activity","exercise":"dumbbell","fitness":"dumbbell","sport":"activity",
        "talk":"message-circle","speak":"message-circle","voice":"mic","listen":"headphones",
        "phone":"smartphone","media":"share-2","internet":"wifi","tech":"cpu",
        "family":"home","parent":"users","child":"baby","mother":"user","father":"user",
        "death":"skull","dead":"skull","grave":"skull","kill":"skull","murder":"skull",
        "war":"sword","fight":"sword","battle":"sword","weapon":"shield",
        "history":"landmark","ancient":"landmark","empire":"landmark","king":"crown",
        "science":"flask","research":"microscope","discover":"search","experiment":"flask",
        "nature":"tree","earth":"globe","environment":"leaf","plant":"leaf","animal":"paw",
        "secret":"lock","hidden":"eye-off","mystery":"question-mark","unknown":"question-mark",
        "question":"help-circle","answer":"check-circle","truth":"check-circle","fact":"info",
    }

    # ── Iconify helpers ─────────────────────────────────────────────────────────
    _ICON_COLOR = "%23374151"   # dark slate gray, URL-encoded
    _ICON_SIZE  = 480
    _SVG_CACHE  = {}            # icon_id -> png bytes, avoids re-fetching

    def _find_icon(keywords):
        for kw in keywords:
            term = _MAP.get(kw, kw)
            try:
                r = requests.get(
                    f"https://api.iconify.design/search?query={term}&limit=1",
                    timeout=8)
                if r.ok:
                    icons = r.json().get("icons", [])
                    if icons:
                        return icons[0]
            except Exception:
                pass
        return None

    def _icon_png(icon_id):
        if icon_id in _SVG_CACHE:
            return _SVG_CACHE[icon_id]
        prefix, name = icon_id.split(":", 1)
        url = (f"https://api.iconify.design/{prefix}/{name}.svg"
               f"?color={_ICON_COLOR}&width={_ICON_SIZE}&height={_ICON_SIZE}")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        png = cairosvg.svg2png(bytestring=r.content,
                               output_width=_ICON_SIZE, output_height=_ICON_SIZE)
        _SVG_CACHE[icon_id] = png
        return png

    # ── PIL rendering helpers ───────────────────────────────────────────────────
    W, H = 1280, 720

    def _load_font(size):
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _wrap(text, font, max_w, draw):
        words = text.split()
        lines, line = [], []
        for w in words:
            test = " ".join(line + [w])
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_w:
                line.append(w)
            else:
                if line: lines.append(" ".join(line))
                line = [w]
        if line: lines.append(" ".join(line))
        return lines or [""]

    def _title_card(text):
        """Dark red card with white horizontal rules and white bold text — like the section headers in the reference."""
        img = Image.new("RGB", (W, H), "#7B0000")
        draw = ImageDraw.Draw(img)
        # Horizontal white lines (decorative)
        for y in [int(H * 0.18), int(H * 0.82)]:
            draw.rectangle([60, y, W - 60, y + 3], fill="white")
        font = _load_font(68)
        lines = _wrap(text, font, W - 140, draw)
        line_h = 84
        total_h = len(lines) * line_h
        y = (H - total_h) // 2
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            draw.text(((W - tw) // 2, y), line, fill="white", font=font)
            y += line_h
        return img

    def _icon_card(text, png_bytes):
        """White background — icon centered in top 58% — bold caption at bottom."""
        img  = Image.new("RGB", (W, H), "white")
        icon = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

        # Scale icon to fit upper area
        max_icon = int(H * 0.54)
        icon.thumbnail((max_icon, max_icon), Image.LANCZOS)

        # Paste icon centered horizontally, vertically in top 60%
        ix = (W - icon.width) // 2
        iy = max(28, (int(H * 0.58) - icon.height) // 2)
        img.paste(icon, (ix, iy), icon)

        # Caption
        draw = ImageDraw.Draw(img)
        font = _load_font(46)
        lines = _wrap(text, font, W - 120, draw)
        line_h = 60
        total_h = len(lines) * line_h
        y = H - total_h - 38
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2
            # Subtle outline for readability
            for dx, dy in [(-1,-1),(1,-1),(-1,1),(1,1)]:
                draw.text((x+dx, y+dy), line, fill="#d0d0d0", font=font)
            draw.text((x, y), line, fill="#1a1a1a", font=font)
            y += line_h
        return img

    def _text_card(text):
        """Fallback: white background, large bold centered text only."""
        img  = Image.new("RGB", (W, H), "white")
        draw = ImageDraw.Draw(img)
        font = _load_font(52)
        lines = _wrap(text, font, W - 120, draw)
        line_h = 66
        total_h = len(lines) * line_h
        y = (H - total_h) // 2
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            draw.text(((W - tw) // 2, y), line, fill="#1a1a1a", font=font)
            y += line_h
        return img

    # ── Generate each scene ────────────────────────────────────────────────────
    print(f"Generating {len(_missing)}/{_n} images (icon fetch + PIL — no GPU)...\\n")

    for _i, _sc in enumerate(SCENE_DATA):
        _img_path = _sc["image"]
        if os.path.exists(_img_path):
            print(f"  [{_i+1}/{_n}] cached")
            continue

        _text = _sc["text"]
        _kws  = _kw(_text)

        # Short numbered lines → title card (e.g. "1. Faces Carry More Information Than Names")
        _is_title = bool(re.match(r"^\\d+[.):]", _text.strip())) and len(_text.split()) <= 10

        if _is_title:
            _pil = _title_card(_text)
            _pil.save(_img_path)
            print(f"  [{_i+1}/{_n}] title card  |  {_text[:60]}")
        else:
            _icon_id = _find_icon(_kws)
            if _icon_id:
                try:
                    _png = _icon_png(_icon_id)
                    _pil = _icon_card(_text, _png)
                    print(f"  [{_i+1}/{_n}] {_icon_id:<30}  |  {_text[:45]}")
                except Exception as _e:
                    print(f"  [{_i+1}/{_n}] icon render error ({_e}) — text fallback")
                    _pil = _text_card(_text)
            else:
                _pil = _text_card(_text)
                print(f"  [{_i+1}/{_n}] text-only  |  {_text[:50]}")
            _pil.save(_img_path)

    print(f"\\nAll {_n} images done. Run Cell 8.")
''')

CELL_MUSIC = code('''\
# == CELL 8 (PATH B): Generate Background Music ================================
# Generates a 90-second ambient loop then uses FFmpeg to extend it to the full
# video length — avoids OOM crashes on long videos with hundreds of scenes.
import numpy as np, wave, os, subprocess

if "WORK_DIR" not in dir():
    WORK_DIR = "/content/unlearned"

if "SCENE_DATA" not in dir():
    import json
    _jpath = f"{WORK_DIR}/scene_data.json"
    if not os.path.exists(_jpath):
        raise RuntimeError("scene_data.json not found. Run Cell 5 first.")
    with open(_jpath) as _f:
        SCENE_DATA = json.load(_f)

_total_dur = sum(s["duration"] for s in SCENE_DATA)
_music_dur = _total_dur + 8.0

# Generate a 90-second base loop only — tiny RAM footprint regardless of
# video length. FFmpeg will loop it to the full duration below.
_LOOP_DUR = 90.0
SR = 44100
t  = np.linspace(0, _LOOP_DUR, int(SR * _LOOP_DUR), endpoint=False)

_NOTES = [130.81, 155.56, 174.61, 196.00, 233.08,
          261.63, 311.13, 349.23, 392.00, 466.16]
_AMPS  = [0.30,   0.18,   0.22,   0.26,   0.16,
          0.18,   0.11,   0.13,   0.16,   0.09]

mix = np.zeros(len(t), dtype=np.float32)
for _freq, _amp in zip(_NOTES, _AMPS):
    _w  = _amp       * np.sin(2 * np.pi * _freq * t).astype(np.float32)
    _w += _amp * 0.3 * np.sin(2 * np.pi * _freq * 2 * t).astype(np.float32)
    _w += _amp * 0.1 * np.sin(2 * np.pi * _freq * 3 * t).astype(np.float32)
    mix += _w

mix /= (np.max(np.abs(mix)) + 1e-9)
mix *= 0.55

_fi = int(SR * 3.0)
_fo = int(SR * 4.0)
mix[:_fi]  *= np.linspace(0, 1, _fi, dtype=np.float32)
mix[-_fo:] *= np.linspace(1, 0, _fo, dtype=np.float32)

_loop_wav = f\'{WORK_DIR}/ambient_loop.wav\'
MUSIC_MP3  = f\'{WORK_DIR}/ambient_music.mp3\'
_pcm = (mix * 32767).clip(-32768, 32767).astype(np.int16)
with wave.open(_loop_wav, \'w\') as _wf:
    _wf.setnchannels(1)
    _wf.setsampwidth(2)
    _wf.setframerate(SR)
    _wf.writeframes(_pcm.tobytes())

# FFmpeg loops the 90-second clip to cover the full video + fade out at end
_fade_start = max(0, _music_dur - 5.0)
subprocess.run([
    "ffmpeg", "-y",
    "-stream_loop", "-1", "-i", _loop_wav,
    "-t", str(_music_dur),
    "-af", f"afade=t=out:st={_fade_start:.1f}:d=5",
    "-q:a", "4", MUSIC_MP3,
], capture_output=True, check=True)
os.remove(_loop_wav)

print(f"Music: {_music_dur:.0f}s ambient pentatonic drone -> {MUSIC_MP3}")
print("\\nMusic done. Run Cell 9.")
''')

CELL_ASSEMBLE = code('''\
# == CELL 9 (PATH B): Assemble Final Video ====================================
import json, os, re, subprocess

# Restore all constants that Cell 2 would have set — safe after session restart
if "WORK_DIR"  not in dir(): WORK_DIR  = "/content/unlearned"
if "CLIP_DIR"  not in dir(): CLIP_DIR  = f"{WORK_DIR}/clips"
if "AUDIO_DIR" not in dir(): AUDIO_DIR = f"{WORK_DIR}/audio"
if "MUSIC_VOL" not in dir(): MUSIC_VOL = 0.08
if "VOICE"     not in dir(): VOICE     = "en-US-AndrewNeural"

if "SCENE_DATA" not in dir():
    _jpath = f"{WORK_DIR}/scene_data.json"
    if not os.path.exists(_jpath):
        raise RuntimeError("scene_data.json not found. Run Cell 5 first.")
    with open(_jpath) as _f:
        SCENE_DATA = json.load(_f)
if "EPISODE_TITLE" not in dir():
    _tp = f"{WORK_DIR}/episode_title.txt"
    EPISODE_TITLE = open(_tp).read().strip() if os.path.exists(_tp) else "Episode"
if "MUSIC_MP3" not in dir():
    MUSIC_MP3 = f"{WORK_DIR}/ambient_music.mp3"

_n = len(SCENE_DATA)
print(f"Building {_n} Ken Burns clips (each clip = exact audio duration)...")
_clips = []

for _i, _sc in enumerate(SCENE_DATA):
    _img   = _sc[\'image\']
    _audio = _sc[\'audio\']
    _dur   = _sc[\'duration\']
    _clip  = f\'{CLIP_DIR}/clip_{_i:04d}.mp4\'
    _clips.append(_clip)
    _nf    = max(int(_dur * 30), 2)

    # Alternate Ken Burns directions for visual variety
    _p = _i % 4
    if _p == 0:
        _zp = f"z=\'min(zoom+0.0003,1.12)\':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':d={_nf}"
    elif _p == 1:
        _zp = f"z=\'min(zoom+0.0003,1.12)\':x=\'0\':y=\'0\':d={_nf}"
    elif _p == 2:
        _zp = f"z=\'min(zoom+0.0003,1.12)\':x=\'iw-iw/zoom\':y=\'ih-ih/zoom\':d={_nf}"
    else:
        _zp = f"z=\'if(lte(zoom,1.0),1.12,zoom-0.0003)\':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':d={_nf}"

    _r = subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", _img,
        "-i", _audio,
        "-filter_complex",
            f"[0:v]scale=1280:720,zoompan={_zp}:s=1280x720:fps=30[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-pix_fmt", "yuv420p",
        _clip
    ], capture_output=True, text=True)

    if _r.returncode != 0:
        print(f"  Clip {_i} error:\\n{_r.stderr[-600:]}")
        raise RuntimeError(f"Clip {_i} failed")

    print(f"  [{_i+1}/{_n}] {_dur:.1f}s  clip_{_i:04d}.mp4")

# Concatenate all clips
_list_path = f\'{WORK_DIR}/clip_list.txt\'
with open(_list_path, \'w\') as _f:
    for _c in _clips:
        _f.write(f"file \'{_c}\'\\n")

_raw_video = f\'{WORK_DIR}/video_raw.mp4\'
print("\\nConcatenating clips...")
subprocess.run([
    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
    "-i", _list_path, "-c", "copy", _raw_video
], capture_output=True, check=True)

# Mix voiceover with background music
_safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
FINAL_VIDEO = f\'{WORK_DIR}/UNLEARNED_{_safe}.mp4\'
print("Mixing music...")

_r = subprocess.run([
    "ffmpeg", "-y",
    "-i", _raw_video,
    "-i", MUSIC_MP3,
    "-filter_complex",
        f"[0:a]volume=1.0[voice];[1:a]volume={MUSIC_VOL}[music];"
        "[voice][music]amix=inputs=2:duration=first[aout]",
    "-map", "0:v",
    "-map", "[aout]",
    "-c:v", "copy",
    "-c:a", "aac", "-b:a", "192k",
    "-shortest",
    FINAL_VIDEO
], capture_output=True, text=True)

if _r.returncode != 0:
    print("FFmpeg error:", _r.stderr[-2000:])
    raise RuntimeError("Assembly failed")

_mb = os.path.getsize(FINAL_VIDEO) / 1_048_576
print(f"\\nFinal video : {FINAL_VIDEO}")
print(f"Size        : {_mb:.1f} MB")
print("\\nAssembly done. Run Cell 10 to download.")
''')

CELL_DOWNLOAD = code('''\
# == CELL 10 (PATH B): Save to Drive & Download ================================
import shutil, os, re
from google.colab import files as _cf

if "WORK_DIR" not in dir(): WORK_DIR = "/content/unlearned"

if "FINAL_VIDEO" not in dir():
    import json
    with open(f\'{WORK_DIR}/episode_title.txt\') as _f:
        EPISODE_TITLE = _f.read().strip()
    _safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
    FINAL_VIDEO = f\'{WORK_DIR}/UNLEARNED_{_safe}.mp4\'

if not os.path.exists(FINAL_VIDEO):
    raise RuntimeError(f"Video not found: {FINAL_VIDEO}\\nRun Cell 9 first.")

try:
    _safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
    _dp   = f\'{DRIVE_FOLDER}/UNLEARNED_{_safe}.mp4\'
    shutil.copy2(FINAL_VIDEO, _dp)
    print(f"Saved to Drive: {_dp}")
except Exception as _e:
    print(f"Drive save skipped: {_e}")

_mb = os.path.getsize(FINAL_VIDEO) / 1_048_576
print(f"Downloading: {os.path.basename(FINAL_VIDEO)}  ({_mb:.1f} MB)")
_cf.download(FINAL_VIDEO)

if "SCENE_DATA" in dir():
    _total = sum(s[\'duration\'] for s in SCENE_DATA) / 60
    print(f"\\nComplete!")
    print(f"Episode : {EPISODE_TITLE}")
    print(f"Duration: ~{_total:.1f} min")
''')

# ── NOTEBOOK ───────────────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE, CELL_INSTALL, CELL_SETUP, CELL_DRIVE,
    CELL_TITLE_INPUT, CELL_UPLOAD_VOICE,
    # ── PATH A: Canva export (recommended — matches reference videos exactly)
    CELL_CANVA_EXPORT,
    # ── PATH A+: Generate image prompts for AI image tools (Midjourney / DALL-E)
    CELL_PROMPT_GEN,
    # ── PATH B: Fully automated (no Canva needed)
    CELL_IMAGES, CELL_MUSIC, CELL_ASSEMBLE, CELL_DOWNLOAD,
]

NOTEBOOK = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {
        "colab": {"provenance": [], "gpuType": "T4"},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
        "accelerator": "GPU",
    },
    "cells": CELLS,
}

OUT = os.path.join(_HERE, "unlearned_generator.ipynb")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(NOTEBOOK, f, indent=1, ensure_ascii=False)
print(f"Written {len(CELLS)} cells -> {OUT}")
