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
# UNLEARNED — Flat Icon Video Generator
### Psychology · Ancient History · Behavioral Science
---
Generates a clean flat-icon image for every scene — white background, bold caption, perfectly synced voiceover.

Icons are fetched automatically from the Iconify library (150 k+ free icons). No GPU needed. No AI model download.

**Run cells in order — any runtime type works (CPU is fine):**

| Cell | What it does |
|------|-------------|
| Cell 1 | Install packages (~2 min, once per session) |
| Cell 2 | Setup directories and voice settings |
| Cell 3 | Mount Google Drive |
| Cell 4 | Type your episode title and click Set Title |
| Cell 5 | Upload your script as a .txt file — voiceover is generated automatically |
| Cell 6 | Fetch icons + render a scene image for every line (~2 sec/scene) |
| Cell 7 | Generate background music |
| Cell 8 | Assemble the final video |
| Cell 9 | Save to Google Drive and download |

> No GPU required. CPU runtime works fine — image generation takes only ~2 seconds per scene.
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

CELL_IMAGES = code('''\
# == CELL 6: Fetch Icons & Render Scene Images =================================
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

    print(f"\\nAll {_n} images done. Run Cell 7.")
''')

CELL_MUSIC = code('''\
# == CELL 7: Generate Background Music ========================================
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
print("\\nMusic done. Run Cell 8.")
''')

CELL_ASSEMBLE = code('''\
# == CELL 8: Assemble Final Video =============================================
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
print("\\nAssembly done. Run Cell 9 to download.")
''')

CELL_DOWNLOAD = code('''\
# == CELL 9: Save to Drive & Download =========================================
import shutil, os, re
from google.colab import files as _cf

if "FINAL_VIDEO" not in dir():
    import json
    with open(f\'{WORK_DIR}/episode_title.txt\') as _f:
        EPISODE_TITLE = _f.read().strip()
    _safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
    FINAL_VIDEO = f\'{WORK_DIR}/UNLEARNED_{_safe}.mp4\'

if not os.path.exists(FINAL_VIDEO):
    raise RuntimeError(f"Video not found: {FINAL_VIDEO}\\nRun Cell 8 first.")

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
    CELL_TITLE_INPUT, CELL_UPLOAD_VOICE, CELL_IMAGES,
    CELL_MUSIC, CELL_ASSEMBLE, CELL_DOWNLOAD,
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
