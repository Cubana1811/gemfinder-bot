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
# ✏️ UNLEARNED — Doodle Video Generator
### Psychology · Ancient History · Behavioral Science
---
**Completely FREE whiteboard animation — NO GPU required**

**Run cells in order:**
1. **Cell 1** — Install (3-5 min, once per session)
2. **Cell 2** — Setup
3. **Cell 3** — Mount Google Drive
4. **Cell 4** — Paste your script + set episode title
5. **Cell 5** — Parse script & generate voiceover
6. **Cell 6** — Render doodle animation (Manim, ~20-30 min for 15-min video)
7. **Cell 7** — Generate background music
8. **Cell 8** — Assemble final video
9. **Cell 9** — Save to Drive & download

> ✅ No GPU needed · Runs on free Colab CPU · Auto-saves to Google Drive
""")

CELL_INSTALL = code('''\
# ══ CELL 1: Install ══════════════════════════════════════════════════════════
print("Installing — runs once per session (~3-5 min)...")
import subprocess, sys, os, urllib.request

def _sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

# System packages Cairo + Pango (required by Manim)
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
_FONT_PATH = '/usr/share/fonts/truetype/custom/Caveat-Regular.ttf'
_FONT_OK = False
for _url in [
    'https://github.com/google/fonts/raw/main/ofl/caveat/static/Caveat-Regular.ttf',
    'https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/static/Caveat-Regular.ttf',
]:
    try:
        urllib.request.urlretrieve(_url, _FONT_PATH)
        subprocess.run(['fc-cache', '-f'], capture_output=True)
        _FONT_OK = True
        break
    except Exception:
        pass
print(f"  Caveat font: {'installed' if _FONT_OK else 'using Ubuntu fallback'}")

try:
    import importlib, manim as _m
    print(f"  Manim {_m.__version__}: ready")
except Exception as _e:
    print(f"  Manim check: {_e}")

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

# Visual constants
BG_COLOR     = '#FFFEF5'
TEXT_COLOR   = '#1A1A1A'
ACCENT_COLOR = '#C41E3A'

# Voice
VOICE       = 'en-US-AndrewNeural'
VOICE_RATE  = '+2%'
VOICE_PITCH = '-3Hz'

# Music
MUSIC_VOL = 0.10

# Check Caveat font
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

# ── Parse ─────────────────────────────────────────────────────────────────────
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

def wrap_for_display(text, words_per_line=8):
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
        capture_output=True, text=True
    )
    return float(json.loads(r.stdout)[\'format\'][\'duration\'])

async def _tts(text, path):
    comm = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, pitch=VOICE_PITCH)
    await comm.save(path)

# ── Generate ──────────────────────────────────────────────────────────────────
print("Parsing script...")
_raw_scenes = parse_scenes(_raw)
print(f"  {len(_raw_scenes)} scenes")

print("\\nGenerating voiceover (per scene)...")
SCENE_DATA = []
_loop = asyncio.get_event_loop()
for _i, _text in enumerate(_raw_scenes):
    _audio = f\'{AUDIO_DIR}/scene_{_i:04d}.mp3\'
    _loop.run_until_complete(_tts(_text, _audio))
    _dur = get_duration(_audio)
    SCENE_DATA.append({
        \'idx\':     _i,
        \'text_raw\': _text,
        \'text\':     wrap_for_display(_text),
        \'duration\': _dur,
        \'audio\':    _audio,
    })
    print(f"  [{_i+1}/{len(_raw_scenes)}] {_dur:.1f}s — {_text[:55]}{'...' if len(_text)>55 else ''}")

# Concatenate audio
_list_path = f\'{WORK_DIR}/audio_list.txt\'
with open(_list_path, \'w\') as _f:
    for _s in SCENE_DATA:
        _f.write(f"file \'{_s[\'audio\']}\'\\n")

FULL_AUDIO = f\'{WORK_DIR}/voiceover_full.mp3\'
subprocess.run([\'ffmpeg\', \'-f\', \'concat\', \'-safe\', \'0\',
    \'-i\', _list_path, \'-c\', \'copy\', FULL_AUDIO, \'-y\'],
    capture_output=True, check=True)

# Save scene data
with open(f\'{WORK_DIR}/scene_data.json\', \'w\') as _f:
    json.dump(SCENE_DATA, _f, indent=2, ensure_ascii=False)

_total = sum(s[\'duration\'] for s in SCENE_DATA)
print(f"\\nTotal audio: {_total:.0f}s  ({_total/60:.1f} min)")
print("\\n✅ Voiceover done. Run Cell 6.")
''')

CELL_MANIM = code('''\
# ══ CELL 6: Render Doodle Animation (Manim) ══════════════════════════════════
import json, os, subprocess

# Reload scene data (safe to re-run this cell independently)
with open(f\'{WORK_DIR}/scene_data.json\') as _f:
    SCENE_DATA = json.load(_f)

SCENES_PY = f\'{WORK_DIR}/scenes.py\'

# ── Write the Manim script ────────────────────────────────────────────────────
_BG  = \'#FFFEF5\'
_FG  = \'#1A1A1A\'
_ACC = \'#C41E3A\'

_manim_code = """from manim import *
import json, subprocess

def _font_ok(name):
    r = subprocess.run(["fc-list", name], capture_output=True, text=True)
    return bool(r.stdout.strip())

BG_COLOR     = \\"#FFFEF5\\"
TEXT_COLOR   = \\"#1A1A1A\\"
ACCENT_COLOR = \\"#C41E3A\\"
FONT = \\"Caveat\\" if _font_ok(\\"Caveat\\") else \\"Ubuntu\\"

with open(\\"/content/unlearned/scene_data.json\\") as _f:
    _SCENES = json.load(_f)


class UnlearnedVideo(Scene):
    def construct(self):
        self.camera.background_color = BG_COLOR
        for sc in _SCENES:
            text  = sc[\\"text\\"]
            dur   = sc[\\"duration\\"]
            words = len(sc[\\"text_raw\\"].split())

            if words < 8:
                fs = 58
            elif words < 15:
                fs = 50
            elif words < 25:
                fs = 42
            elif words < 35:
                fs = 34
            else:
                fs = 28

            obj = Text(
                text,
                font=FONT,
                font_size=fs,
                color=TEXT_COLOR,
                line_spacing=1.5,
            )
            if obj.width > 12.2:
                obj.scale_to_fit_width(12.2)
            obj.move_to(ORIGIN)

            wt = min(dur * 0.55, 3.5)
            ft = 0.45
            ht = max(dur - wt - ft, 0.15)

            if words <= 8:
                ln = Line(
                    obj.get_bottom() + LEFT  * (obj.width / 2) + DOWN * 0.15,
                    obj.get_bottom() + RIGHT * (obj.width / 2) + DOWN * 0.15,
                    color=ACCENT_COLOR,
                    stroke_width=3,
                )
                self.play(Write(obj, run_time=wt))
                self.play(Create(ln, run_time=0.35))
                self.wait(max(ht - 0.35, 0.1))
                self.play(FadeOut(obj, ln, run_time=ft))
            else:
                self.play(Write(obj, run_time=wt))
                self.wait(ht)
                self.play(FadeOut(obj, run_time=ft))
"""

with open(SCENES_PY, \'w\', encoding=\'utf-8\') as _f:
    _f.write(_manim_code)
print(f"Manim script written: {SCENES_PY}")

# ── Run Manim ─────────────────────────────────────────────────────────────────
print("\\nRendering doodle animation (CPU — progress shown below)...")
print("Do not interrupt. A 15-min video takes ~20-30 min to render.\\n")

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
    print("Files found in media dir:")
    for _root, _, _files in os.walk(MEDIA_DIR):
        for _fn in _files:
            print(\' \', os.path.join(_root, _fn))
    raise FileNotFoundError("UnlearnedVideo.mp4 not found — see files above")

_size = os.path.getsize(MANIM_VIDEO) / 1_048_576
print(f"\\nManim video: {MANIM_VIDEO}  ({_size:.1f} MB)")
print("\\n✅ Animation rendered. Run Cell 7.")
''')

CELL_MUSIC = code('''\
# ══ CELL 7: Generate Background Music ════════════════════════════════════════
import numpy as np
from scipy.io import wavfile

# Reload scene data if needed
if \'SCENE_DATA\' not in dir():
    import json
    with open(f\'{WORK_DIR}/scene_data.json\') as _f:
        SCENE_DATA = json.load(_f)

_total_dur = sum(s[\'duration\'] for s in SCENE_DATA)
_music_dur = _total_dur + 8.0   # small tail for fade-out

SR = 44100
t  = np.linspace(0, _music_dur, int(SR * _music_dur), endpoint=False)

# C major pentatonic: C3, Eb3, F3, G3, Bb3 — two octaves
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
import os as _os
_os.remove(_wav)

print(f"Music: {_music_dur:.0f}s ambient pentatonic drone")
print("\\n✅ Music done. Run Cell 8.")
''')

CELL_ASSEMBLE = code('''\
# ══ CELL 8: Assemble Final Video ═════════════════════════════════════════════
import re, os, subprocess

# Reload if needed
if \'MANIM_VIDEO\' not in dir():
    raise RuntimeError("Run Cell 6 first to generate MANIM_VIDEO")
if \'FULL_AUDIO\' not in dir():
    FULL_AUDIO = f\'{WORK_DIR}/voiceover_full.mp3\'
if \'MUSIC_MP3\' not in dir():
    MUSIC_MP3 = f\'{WORK_DIR}/ambient_music.mp3\'

_safe  = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
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

# Save to Google Drive
try:
    _safe = re.sub(r\'[^\\w\\s-]+\', \'\', EPISODE_TITLE).strip().replace(\' \', \'_\')
    _dp   = f\'{DRIVE_FOLDER}/UNLEARNED_{_safe}.mp4\'
    shutil.copy2(FINAL_VIDEO, _dp)
    print(f"Saved to Drive: {_dp}")
except Exception as _e:
    print(f"Drive save: {_e}")

# Download to browser
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
