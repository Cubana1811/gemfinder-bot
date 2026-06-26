"""
Build the Unlearned Doodle Video Generator Colab notebook.
Run: python build_notebook.py
Output: unlearned_generator.ipynb
"""
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src}

def code(src):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": src}

# ── CELLS ──────────────────────────────────────────────────────────────────────

CELL_TITLE = md("""\
# ✏️ UNLEARNED — Animated Stick Figure Video Generator
### Psychology · Ancient History · Behavioral Science
---
**Completely FREE whiteboard animation — NO GPU required**

A stick figure walks on screen, reacts to the script, and gestures as the narrator speaks.
Short impactful sentences get a red underline. The figure changes pose based on what's being said.

**Run cells in order:**
1. **Cell 1** — Install (3-5 min, once per session)
2. **Cell 2** — Setup
3. **Cell 3** — Mount Google Drive
4. **Cell 4** — Paste your script + set episode title
5. **Cell 5** — Parse script & generate voiceover
6. **Cell 6** — Render stick figure animation (Manim, ~25-35 min for 15-min video)
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

# System packages (Cairo + Pango required by Manim)
_sh(['apt-get', 'install', '-y', '-q',
     'libcairo2-dev', 'libpango1.0-dev', 'ffmpeg', 'pkg-config'])
print("  system packages: ok")

# Python packages
for _pkg in ['manim', 'edge-tts', 'nest_asyncio', 'scipy']:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', _pkg],
                   capture_output=True)
    print(f"  {_pkg}: ok")

# Caveat handwritten font
os.makedirs('/usr/share/fonts/truetype/custom', exist_ok=True)
_FP = '/usr/share/fonts/truetype/custom/Caveat-Regular.ttf'
_FONT_OK = False
for _url in [
    'https://github.com/google/fonts/raw/main/ofl/caveat/static/Caveat-Regular.ttf',
    'https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/static/Caveat-Regular.ttf',
]:
    try:
        urllib.request.urlretrieve(_url, _FP)
        subprocess.run(['fc-cache', '-f'], capture_output=True)
        _FONT_OK = True
        break
    except Exception:
        pass
print(f"  Caveat font: {'installed' if _FONT_OK else 'using Ubuntu fallback'}")

try:
    import manim as _m
    print(f"  Manim {_m.__version__}: ready")
except Exception as _e:
    print(f"  Manim: {_e}")

print("\\n✅ Done! Run Cell 2.")
''')

CELL_SETUP = code('''\
# ══ CELL 2: Setup ═══════════════════════════════════════════════════════════
import os, json, re, subprocess, shutil, asyncio
import nest_asyncio
nest_asyncio.apply()

WORK_DIR  = '/content/unlearned'
MEDIA_DIR = f'{WORK_DIR}/media'
AUDIO_DIR = f'{WORK_DIR}/audio'
for _d in [WORK_DIR, MEDIA_DIR, AUDIO_DIR]:
    os.makedirs(_d, exist_ok=True)

VOICE       = 'en-US-AndrewNeural'
VOICE_RATE  = '+2%'
VOICE_PITCH = '-3Hz'
MUSIC_VOL   = 0.10

def _font_available(name):
    r = subprocess.run(['fc-list', name], capture_output=True, text=True)
    return bool(r.stdout.strip())

USE_FONT = 'Caveat' if _font_available('Caveat') else 'Ubuntu'
print(f"Font   : {USE_FONT}")
print(f"Voice  : {VOICE}")
print(f"WorkDir: {WORK_DIR}")
print("\\n✅ Setup done. Run Cell 3.")
''')

CELL_DRIVE = code('''\
# ══ CELL 3: Mount Google Drive ═══════════════════════════════════════════════
from google.colab import drive
drive.mount('/content/drive', force_remount=False)

DRIVE_FOLDER = '/content/drive/MyDrive/Unlearned'
os.makedirs(DRIVE_FOLDER, exist_ok=True)
print(f"Drive ready: {DRIVE_FOLDER}")
print("\\n✅ Drive mounted. Run Cell 4.")
''')

CELL_INPUT = code('''\
# ══ CELL 4: Paste Your Script ════════════════════════════════════════════════
# 1. Change EPISODE_TITLE below
# 2. Replace EVERYTHING between the triple quotes with your script
# 3. Run this cell

EPISODE_TITLE = "Episode 1: Your Title Here"

YOUR_SCRIPT = """
PASTE YOUR UNLEARNED SCRIPT HERE

Replace this entire block with your episode script.
Write in clear, concise sentences — each paragraph becomes a scene.
Aim for 2200-2800 words for a 15-minute episode.
"""

# ── Validate ─────────────────────────────────────────────────────────────────
_raw = YOUR_SCRIPT.strip()
assert _raw, "Script is empty!"
assert 'PASTE YOUR' not in _raw, "Replace the placeholder text with your actual script."
_wc = len(_raw.split())
_est = round(_wc / 2.8 / 60, 1)
print(f"Script : {_wc} words  →  ~{_est} min video")
print(f"Episode: {EPISODE_TITLE}")
print("\\n✅ Script loaded. Run Cell 5.")
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

print("\\nGenerating voiceover (scene by scene)...")
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

# Concatenate all scene audio into one track
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

_total = sum(s[\'duration\'] for s in SCENE_DATA)
print(f"\\nTotal audio: {_total:.0f}s  ({_total/60:.1f} min)")
print("\\n✅ Voiceover done. Run Cell 6.")
''')

# ── The Manim scenes.py template (embedded as a Python string) ─────────────────
# Layout: figure on left (FX=-3.8), text on right-centre (TXT_X=2.2)
# Ground line at GY=-2.55, figure torso at FY=-1.45 (feet land at -2.50)

CELL_MANIM = code('''\
# ══ CELL 6: Render Stick Figure Animation (Manim) ════════════════════════════
import json, os, subprocess

with open(f\'{WORK_DIR}/scene_data.json\') as _f:
    SCENE_DATA = json.load(_f)

SCENES_PY = f\'{WORK_DIR}/scenes.py\'

_MANIM = """from manim import *
import json, subprocess

# ── Detect font ───────────────────────────────────────────────────────────────
def _fok(n):
    return bool(subprocess.run(["fc-list", n], capture_output=True, text=True).stdout.strip())
FONT = "Caveat" if _fok("Caveat") else "Ubuntu"

BG  = "#FFFEF5"
INK = "#1A1A1A"
ACC = "#C41E3A"
GRY = "#AAAAAA"

with open("/content/unlearned/scene_data.json") as _f:
    _SC = json.load(_f)

# ── Layout constants ──────────────────────────────────────────────────────────
FX  = -3.8    # stick figure centre x
FY  = -1.45   # stick figure torso-centre y  (feet reach GY)
GY  = -2.55   # ground line y
TXT_X = 2.2   # text block centre x
TXT_Y = 1.5   # text block centre y

# ── Stick figure builder ──────────────────────────────────────────────────────
# EVERY pose produces exactly 7 VGroup elements so Transform never hits a
# count mismatch. Element 7 is a symbol (? / !) or an invisible dot placeholder.
def _fig(cx, la, ra, ll, rl, symbol=""):
    SY = FY + 0.50   # shoulder y = -0.95
    HY = FY - 0.30   # hips y    = -1.75
    sym = Text(symbol if symbol else ".", font=FONT, font_size=34, color=ACC)
    sym.move_to([cx + 0.60, FY + 1.62, 0])
    if not symbol:
        sym.set_opacity(0)
    return VGroup(
        Circle(0.22, color=INK, stroke_width=3, fill_opacity=0).move_to([cx, FY+1.22, 0]),
        Line([cx, FY+0.99, 0], [cx, HY, 0], color=INK, stroke_width=3),
        Line([cx, SY, 0], la, color=INK, stroke_width=3),
        Line([cx, SY, 0], ra, color=INK, stroke_width=3),
        Line([cx, HY, 0], ll, color=INK, stroke_width=3),
        Line([cx, HY, 0], rl, color=INK, stroke_width=3),
        sym,
    )

# ── Poses (all exactly 7 elements — safe to Transform between any two) ────────
def stand(cx):
    return _fig(cx,
        la=[cx-0.55, -1.95, 0], ra=[cx+0.55, -1.95, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0])

def explain(cx):
    # Right arm raised, pointing toward text
    return _fig(cx,
        la=[cx-0.45, -1.95, 0], ra=[cx+0.65, -0.75, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0])

def think(cx):
    # Right hand near chin, question mark above head
    return _fig(cx,
        la=[cx-0.45, -1.95, 0], ra=[cx+0.22, -0.52, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0],
        symbol="?")

def excited(cx):
    # Both arms raised, exclamation mark above head
    return _fig(cx,
        la=[cx-0.65, -0.62, 0], ra=[cx+0.65, -0.62, 0],
        ll=[cx-0.32, -2.50, 0], rl=[cx+0.32, -2.50, 0],
        symbol="!")

def serious(cx):
    # Arms hanging low, drooped posture
    return _fig(cx,
        la=[cx-0.45, -1.72, 0], ra=[cx+0.45, -1.72, 0],
        ll=[cx-0.28, -2.50, 0], rl=[cx+0.28, -2.50, 0])

def walk_a(cx):
    # Left arm + right leg forward (stride A)
    return _fig(cx,
        la=[cx-0.55, -0.58, 0], ra=[cx+0.35, -1.38, 0],
        ll=[cx-0.15, -2.50, 0], rl=[cx+0.50, -2.22, 0])

def walk_b(cx):
    # Right arm + left leg forward (stride B)
    return _fig(cx,
        la=[cx-0.35, -1.38, 0], ra=[cx+0.55, -0.58, 0],
        ll=[cx-0.50, -2.22, 0], rl=[cx+0.15, -2.50, 0])

# ── Keyword → pose ────────────────────────────────────────────────────────────
def get_pose(text, cx):
    t = text.lower()
    if any(k in t for k in ["?", "why", "how", "wonder", "question",
                             "think", "consider", "what if", "imagine"]):
        return think(cx)
    if any(k in t for k in ["discover", "reveal", "found", "surprise",
                             "shock", "amazing", "secret", "never knew",
                             "hidden", "truth"]):
        return excited(cx)
    if any(k in t for k in ["death", "died", "killed", "murder", "war",
                             "tragic", "terrible", "dark", "evil", "suffer"]):
        return serious(cx)
    return explain(cx)


class UnlearnedVideo(Scene):
    def construct(self):
        self.camera.background_color = BG

        # Ground line
        ground = Line([-7.5, GY, 0], [7.5, GY, 0], color=GRY, stroke_width=1.5)
        self.add(ground)

        # Walk figure in from left edge
        fig = walk_a(-7.2)
        self.add(fig)
        for i in range(10):
            nx = -7.2 + (i + 1) * 0.34
            nf = walk_a(nx) if i % 2 == 0 else walk_b(nx)
            self.play(Transform(fig, nf), run_time=0.13, rate_func=linear)
        self.play(Transform(fig, stand(FX)), run_time=0.25)
        self.wait(0.15)

        for i, sc in enumerate(_SC):
            raw  = sc["text_raw"]
            disp = sc["text"]
            dur  = sc["duration"]
            wc   = len(raw.split())

            # Transition to contextual pose
            self.play(Transform(fig, get_pose(raw, FX)), run_time=0.28)

            # Adaptive font size
            if wc < 8:    fs = 52
            elif wc < 16: fs = 44
            elif wc < 26: fs = 36
            elif wc < 36: fs = 30
            else:         fs = 25

            obj = Text(disp, font=FONT, font_size=fs, color=INK, line_spacing=1.4)
            if obj.width > 8.2:
                obj.scale_to_fit_width(8.2)
            obj.move_to([TXT_X, TXT_Y, 0])

            wt = min(dur * 0.50, 3.0)
            ft = 0.38
            ht = max(dur - wt - ft - 0.28, 0.12)

            if wc <= 8:
                # Short punchy line — add red underline
                ln = Line(
                    obj.get_bottom() + LEFT  * (obj.width / 2) + DOWN * 0.10,
                    obj.get_bottom() + RIGHT * (obj.width / 2) + DOWN * 0.10,
                    color=ACC, stroke_width=3)
                self.play(Write(obj, run_time=wt))
                self.play(Create(ln, run_time=0.28))
                self.wait(max(ht - 0.28, 0.10))
                self.play(FadeOut(obj, ln, run_time=ft))
            else:
                self.play(Write(obj, run_time=wt))
                self.wait(ht)
                self.play(FadeOut(obj, run_time=ft))

            # Return to stand between scenes
            if i < len(_SC) - 1:
                self.play(Transform(fig, stand(FX)), run_time=0.20)

        # Walk figure out to the right
        for i in range(8):
            nx = FX + (i + 1) * 0.50
            nf = walk_a(nx) if i % 2 == 0 else walk_b(nx)
            self.play(Transform(fig, nf), run_time=0.13, rate_func=linear)
        self.play(FadeOut(fig, ground), run_time=0.60)
"""

with open(SCENES_PY, \'w\', encoding=\'utf-8\') as _f:
    _f.write(_MANIM)
print(f"Manim script: {SCENES_PY}")

print("\\nRendering stick figure animation (CPU — progress shown below)...")
print("A 15-min episode takes ~25-35 min. Do not interrupt.\\n")

_result = subprocess.run([
    \'python\', \'-m\', \'manim\', \'-qm\',
    \'--media_dir\', MEDIA_DIR,
    \'--disable_caching\',
    SCENES_PY, \'UnlearnedVideo\'
], timeout=9000)

if _result.returncode != 0:
    raise RuntimeError(f"Manim render failed (exit {_result.returncode})")

# Find output file
MANIM_VIDEO = None
for _root, _, _files in os.walk(MEDIA_DIR):
    for _fn in _files:
        if _fn == \'UnlearnedVideo.mp4\':
            MANIM_VIDEO = os.path.join(_root, _fn)
            break
    if MANIM_VIDEO:
        break

if not MANIM_VIDEO:
    print("Files in media dir:")
    for _root, _, _files in os.walk(MEDIA_DIR):
        for _fn in _files:
            print(\' \', os.path.join(_root, _fn))
    raise FileNotFoundError("UnlearnedVideo.mp4 not found")

print(f"\\nManim video: {MANIM_VIDEO}  ({os.path.getsize(MANIM_VIDEO)/1_048_576:.1f} MB)")
print("\\n✅ Animation rendered. Run Cell 7.")
''')

CELL_MUSIC = code('''\
# ══ CELL 7: Generate Background Music ════════════════════════════════════════
import numpy as np
from scipy.io import wavfile

if \'SCENE_DATA\' not in dir():
    import json
    with open(f\'{WORK_DIR}/scene_data.json\') as _f:
        SCENE_DATA = json.load(_f)

_total_dur = sum(s[\'duration\'] for s in SCENE_DATA)
_music_dur = _total_dur + 10.0

SR = 44100
t  = np.linspace(0, _music_dur, int(SR * _music_dur), endpoint=False)

# C major pentatonic ambient drone — two octaves
_NOTES = [130.81, 155.56, 174.61, 196.00, 233.08,
          261.63, 311.13, 349.23, 392.00, 466.16]
_AMPS  = [0.30,   0.18,   0.22,   0.26,   0.16,
          0.18,   0.11,   0.13,   0.16,   0.09]

mix = np.zeros_like(t)
for _freq, _amp in zip(_NOTES, _AMPS):
    _wave  = _amp       * np.sin(2 * np.pi * _freq * t)
    _wave += _amp * 0.3 * np.sin(2 * np.pi * _freq * 2 * t)
    _wave += _amp * 0.1 * np.sin(2 * np.pi * _freq * 3 * t)
    _lfo   = 0.90 + 0.10 * np.sin(2 * np.pi * 0.07 * t + _freq)
    mix   += _wave * _lfo

mix /= (np.max(np.abs(mix)) + 1e-9)
mix *= 0.55

_fi = min(int(SR * 4.0), len(mix) // 4)
_fo = min(int(SR * 7.0), len(mix) // 4)
mix[:_fi]  *= np.linspace(0, 1, _fi)
mix[-_fo:] *= np.linspace(1, 0, _fo)

_wav = f\'{WORK_DIR}/ambient_music.wav\'
MUSIC_MP3 = f\'{WORK_DIR}/ambient_music.mp3\'
wavfile.write(_wav, SR, mix.astype(np.float32))
subprocess.run([\'ffmpeg\', \'-i\', _wav, \'-q:a\', \'4\', MUSIC_MP3, \'-y\'],
               capture_output=True, check=True)
import os as _os; _os.remove(_wav)

print(f"Music: {_music_dur:.0f}s ambient pentatonic drone")
print("\\n✅ Music done. Run Cell 8.")
''')

CELL_ASSEMBLE = code('''\
# ══ CELL 8: Assemble Final Video ═════════════════════════════════════════════
import re, os, subprocess

if \'MANIM_VIDEO\' not in dir():
    raise RuntimeError("Run Cell 6 first to generate MANIM_VIDEO")
if \'FULL_AUDIO\' not in dir():
    FULL_AUDIO = f\'{WORK_DIR}/voiceover_full.mp3\'
if \'MUSIC_MP3\' not in dir():
    MUSIC_MP3 = f\'{WORK_DIR}/ambient_music.mp3\'

_safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
FINAL_VIDEO = f\'{WORK_DIR}/UNLEARNED_{_safe}.mp4\'

print("Assembling final video...")
_r = subprocess.run([
    \'ffmpeg\', \'-y\',
    \'-i\', MANIM_VIDEO,
    \'-i\', FULL_AUDIO,
    \'-i\', MUSIC_MP3,
    \'-filter_complex\',
        \'[1:a]volume=1.0[voice];\'
        f\'[2:a]volume={MUSIC_VOL}[music];\'
        \'[voice][music]amix=inputs=2:duration=first[aout]\',
    \'-map\', \'0:v\',
    \'-map\', \'[aout]\',
    \'-c:v\', \'libx264\', \'-crf\', \'20\', \'-preset\', \'fast\',
    \'-c:a\', \'aac\', \'-b:a\', \'192k\',
    \'-pix_fmt\', \'yuv420p\',
    \'-shortest\',
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

print("Starting download to your computer...")
_cf.download(FINAL_VIDEO)

_total = sum(s[\'duration\'] for s in SCENE_DATA) / 60
print(f"\\n✅ Complete!")
print(f"Episode : {EPISODE_TITLE}")
print(f"Duration: ~{_total:.1f} minutes")
''')

# ── NOTEBOOK ───────────────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE,
    CELL_INSTALL,
    CELL_SETUP,
    CELL_DRIVE,
    CELL_INPUT,
    CELL_PARSE_VOICE,
    CELL_MANIM,
    CELL_MUSIC,
    CELL_ASSEMBLE,
    CELL_DOWNLOAD,
]

NOTEBOOK = {
    "nbformat": 4,
    "nbformat_minor": 0,
    "metadata": {
        "colab": {"provenance": [], "gpuType": "None"},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"}
    },
    "cells": CELLS,
}

OUT = os.path.join(_HERE, 'unlearned_generator.ipynb')
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(NOTEBOOK, f, indent=1, ensure_ascii=False)
print(f"Written {len(CELLS)} cells → {OUT}")
