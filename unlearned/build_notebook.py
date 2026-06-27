"""
Build the Unlearned Video Generator Colab notebook.
Run: python build_notebook.py
Output: unlearned_generator.ipynb

UNLEARNED BRAND STYLE:
  Background  : #FFF8F0  warm parchment — scholarly, timeless
  Character   : #2563A8  royal blue head / #1A3F72 darker body — authority, trust
  Gold accent : #E8A020  amber gold — insight, discovery, callouts
  Text        : #1A1A1A  near-black, Caveat font (handwritten warmth)
  Ground      : #C4B4A4  warm gray

Character is a flat-design figure: filled circle head with dot eyes, rounded
rectangle body, thick arm/leg lines — identical every single scene.
"""
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src}

def code(src):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": src}

# ── CELLS ──────────────────────────────────────────────────────────────────────

CELL_TITLE = md("""\
# ✏️ UNLEARNED — Animated Video Generator
### Psychology · Ancient History · Behavioral Science
---
**Your own original brand style — 100% consistent, every episode.**

A flat-design character in royal blue walks on screen, reacts to your script,
and gestures as the narrator speaks. Gold accents highlight key insights.
Every scene looks identical — this IS the Unlearned brand.

**Run cells in order:**
1. **Cell 1** — Install (3-5 min, once per session)
2. **Cell 2** — Setup
3. **Cell 3** — Mount Google Drive
4. **Cell 4** — Paste your script + set episode title
5. **Cell 5** — Parse script & generate voiceover
6. **Cell 6** — Render animation (Manim, ~25-35 min for 15-min video)
7. **Cell 7** — Generate background music
8. **Cell 8** — Assemble final video
9. **Cell 9** — Save to Drive & download

> ✅ No GPU needed · Free Colab CPU · Auto-saves to Google Drive
""")

CELL_INSTALL = code('''\
# ══ CELL 1: Install ══════════════════════════════════════════════════════════
print("Installing — runs once per session (~3-5 min)...")
import subprocess, sys, os, urllib.request

def _sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

_sh(["apt-get", "install", "-y", "-q",
     "libcairo2-dev", "libpango1.0-dev", "ffmpeg", "pkg-config"])
print("  system packages: ok")

for _pkg in ["manim", "edge-tts", "nest_asyncio", "scipy"]:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", _pkg],
                   capture_output=True)
    print(f"  {_pkg}: ok")

os.makedirs("/usr/share/fonts/truetype/custom", exist_ok=True)
_FP = "/usr/share/fonts/truetype/custom/Caveat-Regular.ttf"
_FONT_OK = False
for _url in [
    "https://github.com/google/fonts/raw/main/ofl/caveat/static/Caveat-Regular.ttf",
    "https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/static/Caveat-Regular.ttf",
]:
    try:
        urllib.request.urlretrieve(_url, _FP)
        subprocess.run(["fc-cache", "-f"], capture_output=True)
        _FONT_OK = True
        break
    except Exception:
        pass
print(f"  Caveat font: {'installed' if _FONT_OK else 'using Ubuntu fallback'}")

try:
    import manim as _m; print(f"  Manim {_m.__version__}: ready")
except Exception as _e: print(f"  Manim: {_e}")

print("\\n✅ Done! Run Cell 2.")
''')

CELL_SETUP = code('''\
# ══ CELL 2: Setup ═══════════════════════════════════════════════════════════
import os, json, re, subprocess, shutil, asyncio
import nest_asyncio
nest_asyncio.apply()

WORK_DIR  = "/content/unlearned"
MEDIA_DIR = f"{WORK_DIR}/media"
AUDIO_DIR = f"{WORK_DIR}/audio"
for _d in [WORK_DIR, MEDIA_DIR, AUDIO_DIR]:
    os.makedirs(_d, exist_ok=True)

VOICE       = "en-US-AndrewNeural"
VOICE_RATE  = "+2%"
VOICE_PITCH = "-3Hz"
MUSIC_VOL   = 0.10

def _font_available(name):
    r = subprocess.run(["fc-list", name], capture_output=True, text=True)
    return bool(r.stdout.strip())

USE_FONT = "Caveat" if _font_available("Caveat") else "Ubuntu"
print(f"Font   : {USE_FONT}")
print(f"Voice  : {VOICE}")
print(f"WorkDir: {WORK_DIR}")
print("\\n✅ Setup done. Run Cell 3.")
''')

CELL_DRIVE = code('''\
# ══ CELL 3: Mount Google Drive ═══════════════════════════════════════════════
from google.colab import drive
drive.mount("/content/drive", force_remount=False)

DRIVE_FOLDER = "/content/drive/MyDrive/Unlearned"
os.makedirs(DRIVE_FOLDER, exist_ok=True)
print(f"Drive ready: {DRIVE_FOLDER}")
print("\\n✅ Drive mounted. Run Cell 4.")
''')

CELL_INPUT = code('''\
# ══ CELL 4: Set Title & Load Script ══════════════════════════════════════════
# 1. Change EPISODE_TITLE below (no special characters or apostrophes)
# 2. Save your script as a .txt file and upload it to:
#      Google Drive → Unlearned → script.txt
# 3. Run this cell

EPISODE_TITLE = """Episode 1 Your Title Here"""

# ── Load script from Google Drive ─────────────────────────────────────────────
_script_path = f"{DRIVE_FOLDER}/script.txt"
assert os.path.exists(_script_path), (
    f"script.txt not found!\\n"
    f"Upload your script as a .txt file to:\\n"
    f"  Google Drive → Unlearned → script.txt"
)

with open(_script_path, encoding="utf-8") as _f:
    YOUR_SCRIPT = _f.read()

_raw = YOUR_SCRIPT.strip()
assert _raw, "script.txt is empty!"
_wc  = len(_raw.split())
_est = round(_wc / 2.8 / 60, 1)
print(f"Script : {_wc} words  ->  ~{_est} min video")
print(f"Episode: {EPISODE_TITLE}")
print("\\n Script loaded. Run Cell 5.")
''')

CELL_PARSE_VOICE = code('''\
# ══ CELL 5: Parse Script & Generate Voiceover ════════════════════════════════
import edge_tts, asyncio, re, json
import nest_asyncio; nest_asyncio.apply()

def parse_scenes(text, max_words=28):
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

def wrap_display(text, words_per_line=8):
    words = text.split()
    lines, line = [], []
    for w in words:
        line.append(w)
        if len(line) >= words_per_line:
            lines.append(\' \'.join(line))
            line = []
    if line:
        lines.append(\' \'.join(line))
    return \'\\n\'.join(lines)

def get_duration(path):
    r = subprocess.run(
        [\'ffprobe\', \'-v\', \'quiet\', \'-print_format\', \'json\', \'-show_format\', path],
        capture_output=True, text=True)
    return float(json.loads(r.stdout)[\'format\'][\'duration\'])

async def _tts(text, path):
    comm = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, pitch=VOICE_PITCH)
    await comm.save(path)

print("Parsing script...")
_raw_scenes = parse_scenes(_raw)
print(f"  {len(_raw_scenes)} scenes")

print("\\nGenerating voiceover...")
SCENE_DATA = []
_loop = asyncio.get_event_loop()
for _i, _text in enumerate(_raw_scenes):
    _audio = f\'{AUDIO_DIR}/scene_{_i:04d}.mp3\'
    _loop.run_until_complete(_tts(_text, _audio))
    _dur = get_duration(_audio)
    SCENE_DATA.append({
        \'idx\':      _i,
        \'text_raw\':  _text,
        \'text\':      wrap_display(_text),
        \'duration\':  _dur,
        \'audio\':     _audio,
    })
    print(f"  [{_i+1}/{len(_raw_scenes)}] {_dur:.1f}s  {_text[:55]}{'...' if len(_text)>55 else ''}")

_list = f\'{WORK_DIR}/audio_list.txt\'
with open(_list, \'w\') as _f:
    for _s in SCENE_DATA:
        _f.write(f"file \'{_s[\'audio\']}\'\\n")

FULL_AUDIO = f\'{WORK_DIR}/voiceover_full.mp3\'
subprocess.run([\'ffmpeg\', \'-f\', \'concat\', \'-safe\', \'0\',
    \'-i\', _list, \'-c\', \'copy\', FULL_AUDIO, \'-y\'],
    capture_output=True, check=True)

with open(f\'{WORK_DIR}/scene_data.json\', \'w\') as _f:
    json.dump(SCENE_DATA, _f, indent=2, ensure_ascii=False)

with open(f\'{WORK_DIR}/episode_title.txt\', \'w\') as _f:
    _f.write(EPISODE_TITLE)

_total = sum(s[\'duration\'] for s in SCENE_DATA)
print(f"\\nTotal audio: {_total:.0f}s  ({_total/60:.1f} min)")
print("\\n✅ Voiceover done. Run Cell 6.")
''')

# ── CELL 6: Manim ─────────────────────────────────────────────────────────────
# The _MANIM string is scenes.py — embedded inside code('''...''') so """ works freely.
# Character VGroup always has exactly 11 elements → Transform is stable across all poses.

CELL_MANIM = code('''\
# ══ CELL 6: Render Animation (Manim) ═════════════════════════════════════════
import json, os, subprocess

with open(f\'{WORK_DIR}/scene_data.json\') as _f:
    SCENE_DATA = json.load(_f)

SCENES_PY = f\'{WORK_DIR}/scenes.py\'

_MANIM = """from manim import *
import json, subprocess

def _fok(n):
    return bool(subprocess.run(["fc-list", n], capture_output=True, text=True).stdout.strip())
FONT = "Caveat" if _fok("Caveat") else "Ubuntu"

# ── Unlearned Brand Palette ───────────────────────────────────────────────────
BG   = "#FFF8F0"   # warm parchment
CH   = "#2563A8"   # character head — royal blue
CB   = "#1A3F72"   # character body — deeper blue
GOLD = "#E8A020"   # amber gold — accents, underlines, symbols
INK  = "#1A1A1A"   # text and outlines
GND  = "#C4B4A4"   # ground line — warm gray

# ── Data ─────────────────────────────────────────────────────────────────────
with open("/content/unlearned/scene_data.json") as _f:
    _SC = json.load(_f)

try:
    with open("/content/unlearned/episode_title.txt") as _f:
        _TITLE = _f.read().strip()
except Exception:
    _TITLE = ""

# ── Layout ────────────────────────────────────────────────────────────────────
FX   = -3.8    # figure centre x
FY   = -1.45   # figure torso centre y  (head top lands at y≈0)
GY   = -2.58   # ground line y           (feet at -2.50, just above)
TX   =  2.0    # text centre x
TY   =  1.8    # text centre y

# ── Character builder — always 11 elements, always same types ─────────────────
# Order: head, body, l_eye, r_eye, l_pup, r_pup, collar, l_arm, r_arm, l_leg, r_leg
# Identical structure across every pose → Transform is smooth and reliable.
def _char(cx, la, ra, ll, rl):
    SY = FY + 0.50    # shoulder y
    HY = FY - 0.30    # hips y

    head   = Circle(0.30, color=INK, stroke_width=2.5,
                    fill_opacity=1, fill_color=CH).move_to([cx, FY+1.15, 0])
    body   = RoundedRectangle(corner_radius=0.10, width=0.60, height=0.75,
                              color=INK, stroke_width=2,
                              fill_opacity=1, fill_color=CB).move_to([cx, FY+0.20, 0])
    l_eye  = Circle(0.068, color=INK, stroke_width=1,
                    fill_opacity=1, fill_color=WHITE).move_to([cx-0.11, FY+1.21, 0])
    r_eye  = Circle(0.068, color=INK, stroke_width=1,
                    fill_opacity=1, fill_color=WHITE).move_to([cx+0.11, FY+1.21, 0])
    l_pup  = Dot(radius=0.030, color=INK).move_to([cx-0.11, FY+1.20, 0])
    r_pup  = Dot(radius=0.030, color=INK).move_to([cx+0.11, FY+1.20, 0])
    collar = Line([cx-0.12, FY+0.55, 0], [cx+0.12, FY+0.55, 0],
                  color=GOLD, stroke_width=3.5)
    l_arm  = Line([cx-0.30, SY, 0], la, color=INK, stroke_width=4)
    r_arm  = Line([cx+0.30, SY, 0], ra, color=INK, stroke_width=4)
    l_leg  = Line([cx-0.18, HY, 0], ll, color=INK, stroke_width=4)
    r_leg  = Line([cx+0.18, HY, 0], rl, color=INK, stroke_width=4)

    return VGroup(head, body, l_eye, r_eye, l_pup, r_pup,
                  collar, l_arm, r_arm, l_leg, r_leg)

# ── Poses ─────────────────────────────────────────────────────────────────────
def stand(cx):
    return _char(cx,
        la=[cx-0.55, -1.90, 0], ra=[cx+0.55, -1.90, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0])

def explain(cx):
    return _char(cx,
        la=[cx-0.45, -1.90, 0], ra=[cx+0.68, -0.65, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0])

def think(cx):
    return _char(cx,
        la=[cx-0.45, -1.90, 0], ra=[cx+0.22, -0.50, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0])

def excited(cx):
    return _char(cx,
        la=[cx-0.65, -0.60, 0], ra=[cx+0.65, -0.60, 0],
        ll=[cx-0.32, -2.50, 0], rl=[cx+0.32, -2.50, 0])

def serious(cx):
    return _char(cx,
        la=[cx-0.45, -1.68, 0], ra=[cx+0.45, -1.68, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0])

def walk_a(cx):
    return _char(cx,
        la=[cx-0.55, -0.60, 0], ra=[cx+0.35, -1.42, 0],
        ll=[cx-0.15, -2.50, 0], rl=[cx+0.50, -2.22, 0])

def walk_b(cx):
    return _char(cx,
        la=[cx-0.35, -1.42, 0], ra=[cx+0.55, -0.60, 0],
        ll=[cx-0.50, -2.22, 0], rl=[cx+0.15, -2.50, 0])

# ── Pose selection from keywords ─────────────────────────────────────────────
def _pose_type(text):
    t = text.lower()
    if any(k in t for k in ["?","why","how","wonder","think","consider",
                             "what if","imagine","question","mean"]):
        return "think"
    if any(k in t for k in ["discover","reveal","found","surprise","shock",
                             "amazing","secret","hidden","truth","never knew",
                             "actually","in fact","turns out"]):
        return "excited"
    if any(k in t for k in ["death","died","kill","murder","war","tragic",
                             "terrible","suffer","dark","evil","pain","loss"]):
        return "serious"
    return "explain"

def _get_pose(text, cx):
    pt = _pose_type(text)
    if pt == "think":   return think(cx)
    if pt == "excited": return excited(cx)
    if pt == "serious": return serious(cx)
    return explain(cx)


class UnlearnedVideo(Scene):
    def construct(self):
        self.camera.background_color = BG

        # ── Episode title card ─────────────────────────────────────────────────
        if _TITLE:
            ep = Text(_TITLE, font=FONT, font_size=46, color=INK)
            ep.move_to([0, 0.5, 0])
            ln = Line([-4.5, 0.05, 0], [4.5, 0.05, 0], color=GOLD, stroke_width=2.5)
            sub = Text("Unlearned", font=FONT, font_size=30, color=GOLD)
            sub.move_to([0, -0.45, 0])
            self.play(FadeIn(ep), FadeIn(ln), FadeIn(sub), run_time=0.80)
            self.wait(2.2)
            self.play(FadeOut(ep), FadeOut(ln), FadeOut(sub), run_time=0.65)
            self.wait(0.30)

        # ── Ground line ────────────────────────────────────────────────────────
        ground = Line([-7.6, GY, 0], [7.6, GY, 0], color=GND, stroke_width=1.8)
        self.add(ground)

        # ── Walk in from left ──────────────────────────────────────────────────
        fig = walk_a(-7.6)
        self.add(fig)
        for i in range(10):
            nx = -7.6 + (i + 1) * 0.38
            nf = walk_a(nx) if i % 2 == 0 else walk_b(nx)
            self.play(Transform(fig, nf), run_time=0.13, rate_func=linear)
        self.play(Transform(fig, stand(FX)), run_time=0.28)
        self.wait(0.18)

        # ── Scene loop ────────────────────────────────────────────────────────
        for i, sc in enumerate(_SC):
            raw  = sc["text_raw"]
            disp = sc["text"]
            dur  = sc["duration"]
            wc   = len(raw.split())

            # Pose transition
            pt = _pose_type(raw)
            self.play(Transform(fig, _get_pose(raw, FX)), run_time=0.28)

            # Gold symbol for think / excited
            sym     = None
            sym_dur = 0.0
            if pt == "think":
                sym = Text("?", font=FONT, font_size=42, color=GOLD)
                sym.move_to([FX + 0.75, FY + 1.72, 0])
                self.play(FadeIn(sym), run_time=0.18)
                sym_dur = 0.18
            elif pt == "excited":
                sym = Text("!", font=FONT, font_size=46, color=GOLD)
                sym.move_to([FX, FY + 1.85, 0])
                self.play(FadeIn(sym), run_time=0.18)
                sym_dur = 0.18

            # Adaptive font size
            if wc < 8:    fs = 52
            elif wc < 16: fs = 44
            elif wc < 26: fs = 36
            elif wc < 36: fs = 30
            else:         fs = 25

            obj = Text(disp, font=FONT, font_size=fs, color=INK, line_spacing=1.4)
            if obj.width > 8.0:
                obj.scale_to_fit_width(8.0)
            obj.move_to([TX, TY, 0])

            wt = min(dur * 0.50, 3.0)
            ft = 0.38
            ht = max(dur - wt - ft - 0.28 - sym_dur, 0.12)

            if wc <= 8:
                # Gold underline for short punchy sentences
                uline = Line(
                    obj.get_bottom() + LEFT  * (obj.width / 2) + DOWN * 0.12,
                    obj.get_bottom() + RIGHT * (obj.width / 2) + DOWN * 0.12,
                    color=GOLD, stroke_width=3.5)
                self.play(Write(obj, run_time=wt))
                self.play(Create(uline, run_time=0.28))
                self.wait(max(ht - 0.28, 0.10))
                fade_out = [FadeOut(obj), FadeOut(uline)]
                if sym: fade_out.append(FadeOut(sym))
                self.play(*fade_out, run_time=ft)
            else:
                self.play(Write(obj, run_time=wt))
                self.wait(ht)
                fade_out = [FadeOut(obj)]
                if sym: fade_out.append(FadeOut(sym))
                self.play(*fade_out, run_time=ft)

            if i < len(_SC) - 1:
                self.play(Transform(fig, stand(FX)), run_time=0.20)

        # ── Walk out right ────────────────────────────────────────────────────
        for i in range(8):
            nx = FX + (i + 1) * 0.52
            nf = walk_a(nx) if i % 2 == 0 else walk_b(nx)
            self.play(Transform(fig, nf), run_time=0.13, rate_func=linear)
        self.play(FadeOut(fig), FadeOut(ground), run_time=0.65)
"""

with open(SCENES_PY, "w", encoding="utf-8") as _f:
    _f.write(_MANIM)
print(f"Manim script: {SCENES_PY}")

print("\\nRendering animation (CPU — progress shown below)...")
print("A 15-min episode takes ~25-35 min. Do not interrupt.\\n")

_result = subprocess.run([
    "python", "-m", "manim", "-qm",
    "--media_dir", MEDIA_DIR,
    "--disable_caching",
    SCENES_PY, "UnlearnedVideo"
], timeout=9000)

if _result.returncode != 0:
    raise RuntimeError(f"Manim render failed (exit {_result.returncode})")

MANIM_VIDEO = None
for _root, _, _files in os.walk(MEDIA_DIR):
    for _fn in _files:
        if _fn == "UnlearnedVideo.mp4":
            MANIM_VIDEO = os.path.join(_root, _fn)
            break
    if MANIM_VIDEO:
        break

if not MANIM_VIDEO:
    print("Files found in media dir:")
    for _root, _, _files in os.walk(MEDIA_DIR):
        for _fn in _files: print(" ", os.path.join(_root, _fn))
    raise FileNotFoundError("UnlearnedVideo.mp4 not found")

print(f"\\nManim video: {MANIM_VIDEO}  ({os.path.getsize(MANIM_VIDEO)/1_048_576:.1f} MB)")
print("\\n✅ Animation rendered. Run Cell 7.")
''')

CELL_MUSIC = code('''\
# ══ CELL 7: Generate Background Music ════════════════════════════════════════
import numpy as np, wave, struct, os, subprocess

if "SCENE_DATA" not in dir():
    import json
    with open(f\'{WORK_DIR}/scene_data.json\') as _f:
        SCENE_DATA = json.load(_f)

_total_dur = sum(s["duration"] for s in SCENE_DATA)
_music_dur = _total_dur + 10.0

SR = 44100
t  = np.linspace(0, _music_dur, int(SR * _music_dur), endpoint=False)

# C major pentatonic ambient drone — warm and intellectual
_NOTES = [130.81, 155.56, 174.61, 196.00, 233.08,
          261.63, 311.13, 349.23, 392.00, 466.16]
_AMPS  = [0.30,   0.18,   0.22,   0.26,   0.16,
          0.18,   0.11,   0.13,   0.16,   0.09]

mix = np.zeros_like(t)
for _freq, _amp in zip(_NOTES, _AMPS):
    _wave  = _amp       * np.sin(2 * np.pi * _freq * t)
    _wave += _amp * 0.3 * np.sin(2 * np.pi * _freq * 2 * t)
    _wave += _amp * 0.1 * np.sin(2 * np.pi * _freq * 3 * t)
    mix   += _wave * (0.90 + 0.10 * np.sin(2 * np.pi * 0.07 * t + _freq))

mix /= (np.max(np.abs(mix)) + 1e-9)
mix *= 0.55

_fi = min(int(SR * 4.0), len(mix) // 4)
_fo = min(int(SR * 7.0), len(mix) // 4)
mix[:_fi]  *= np.linspace(0, 1, _fi)
mix[-_fo:] *= np.linspace(1, 0, _fo)

# Write WAV with built-in wave module — no scipy needed
_wav  = f\'{WORK_DIR}/ambient_music.wav\'
MUSIC_MP3 = f\'{WORK_DIR}/ambient_music.mp3\'
_pcm = (mix * 32767).astype(np.int16)
with wave.open(_wav, \'w\') as _wf:
    _wf.setnchannels(1)
    _wf.setsampwidth(2)
    _wf.setframerate(SR)
    _wf.writeframes(_pcm.tobytes())
subprocess.run(["ffmpeg", "-i", _wav, "-q:a", "4", MUSIC_MP3, "-y"],
               capture_output=True, check=True)
os.remove(_wav)

print(f"Music: {_music_dur:.0f}s ambient pentatonic drone")
print("\\n✅ Music done. Run Cell 8.")
''')

CELL_ASSEMBLE = code('''\
# ══ CELL 8: Assemble Final Video ═════════════════════════════════════════════
import re, os, subprocess

if "MANIM_VIDEO" not in dir():
    raise RuntimeError("Run Cell 6 first to generate MANIM_VIDEO")
if "FULL_AUDIO" not in dir():
    FULL_AUDIO = f\'{WORK_DIR}/voiceover_full.mp3\'
if "MUSIC_MP3" not in dir():
    MUSIC_MP3 = f\'{WORK_DIR}/ambient_music.mp3\'

_safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
FINAL_VIDEO = f\'{WORK_DIR}/UNLEARNED_{_safe}.mp4\'

print("Assembling final video...")
_r = subprocess.run([
    "ffmpeg", "-y",
    "-i", MANIM_VIDEO,
    "-i", FULL_AUDIO,
    "-i", MUSIC_MP3,
    "-filter_complex",
        "[1:a]volume=1.0[voice];"
        f"[2:a]volume={MUSIC_VOL}[music];"
        "[voice][music]amix=inputs=2:duration=first[aout]",
    "-map", "0:v",
    "-map", "[aout]",
    "-c:v", "libx264", "-crf", "20", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    "-pix_fmt", "yuv420p",
    "-shortest",
    FINAL_VIDEO
], capture_output=True, text=True)

if _r.returncode != 0:
    print("FFmpeg error:", _r.stderr[-2000:])
    raise RuntimeError("Assembly failed — see error above")

_mb = os.path.getsize(FINAL_VIDEO) / 1_048_576
print(f"Final video : {FINAL_VIDEO}")
print(f"Size        : {_mb:.1f} MB")
print("\\n✅ Assembly done. Run Cell 9 to download.")
''')

CELL_DOWNLOAD = code('''\
# ══ CELL 9: Save to Drive & Download ════════════════════════════════════════
import shutil, os, re
from google.colab import files as _cf

try:
    _safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
    _dp   = f\'{DRIVE_FOLDER}/UNLEARNED_{_safe}.mp4\'
    shutil.copy2(FINAL_VIDEO, _dp)
    print(f"Saved to Drive: {_dp}")
except Exception as _e:
    print(f"Drive save: {_e}")

print("Starting download...")
_cf.download(FINAL_VIDEO)

_total = sum(s["duration"] for s in SCENE_DATA) / 60
print(f"\\n✅ Complete!")
print(f"Episode : {EPISODE_TITLE}")
print(f"Duration: ~{_total:.1f} minutes")
''')

# ── NOTEBOOK ───────────────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE, CELL_INSTALL, CELL_SETUP, CELL_DRIVE,
    CELL_INPUT, CELL_PARSE_VOICE, CELL_MANIM,
    CELL_MUSIC, CELL_ASSEMBLE, CELL_DOWNLOAD,
]

NOTEBOOK = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {
        "colab": {"provenance": [], "gpuType": "None"},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "cells": CELLS,
}

OUT = os.path.join(_HERE, "unlearned_generator.ipynb")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(NOTEBOOK, f, indent=1, ensure_ascii=False)
print(f"Written {len(CELLS)} cells → {OUT}")
