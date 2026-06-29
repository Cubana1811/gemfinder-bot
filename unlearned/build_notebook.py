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
# UNLEARNED — AI Stick Figure Video Generator
### Psychology · Ancient History · Behavioral Science
---
**SDXL generates a unique stick figure drawing for every scene — perfectly synced to the voiceover.**

Each image is AI-drawn to match what the narrator says.
Hospital scene → stick figure hospital. Animals → stick figure animals. No stock images. No text on screen.

**Run cells in order using a T4 GPU runtime:**
1. **Cell 1** — Install packages (~3 min, once per session)
2. **Cell 2** — Setup and load SDXL model (~2 min, requires T4 GPU)
3. **Cell 3** — Mount Google Drive
4. **Cell 4** — Enter title and paste script, then click Load Script
5. **Cell 5** — Parse script and generate voiceover
6. **Cell 6** — Generate SDXL stick figure images (~25 sec/scene)
7. **Cell 7** — Generate background music
8. **Cell 8** — Assemble final video
9. **Cell 9** — Save to Google Drive and download

> Requires T4 GPU runtime · Auto-saves to Google Drive
""")

CELL_INSTALL = code('''\
# == CELL 1: Install ==========================================================
print("Installing packages — runs once per session (~3-5 min)...")
import subprocess, sys

def _sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

_sh(["apt-get", "install", "-y", "-q", "ffmpeg"])
print("  ffmpeg: ok")

_pkgs = ["diffusers", "transformers", "accelerate", "xformers", "edge-tts", "nest_asyncio"]
for _pkg in _pkgs:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", _pkg], capture_output=True)
    print(f"  {_pkg}: ok")

print("\\n Done! Run Cell 2.")
''')

CELL_SETUP = code('''\
# == CELL 2: Setup & Load SDXL ================================================
import os, json, re, subprocess, asyncio, torch
import nest_asyncio
nest_asyncio.apply()

if not torch.cuda.is_available():
    raise RuntimeError(
        "No GPU detected!\\n"
        "Switch to T4 GPU: Runtime -> Change runtime type -> T4 GPU"
    )

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

# -- Keyword extractor ---------------------------------------------------------
_STOPS = set((
    "a an the in on at is was are were it its of to and or but for with by "
    "from this that they them their we our you your he she his her not no as "
    "so be been has have had do does did will would could should may might also "
    "just than then when where who which what how why if all one two three "
    "first last into out up about more most some any each every can there here "
    "now after before during while because since though although like even get "
    "got very much many such way make made use used using take took time "
    "know knew think thought say said see saw come came go went back new old "
    "other another both own long well still only over own day year life same "
    "become became through between again those these its our"
).split())

def extract_keywords(text, n=7):
    words = re.findall(r\'\\b[a-zA-Z]{3,}\\b\', text.lower())
    kw = [w for w in words if w not in _STOPS]
    kw.sort(key=len, reverse=True)
    return ", ".join(list(dict.fromkeys(kw))[:n])

NEG_PROMPT = (
    "realistic, photographic, 3d render, complex, colorful, painting, "
    "detailed, text, watermark, blurry, photograph, logo, signature, "
    "color fill, gradient, shadow, realistic people, anime, cartoon, "
    "photo, human face, portrait, background detail, decoration"
)

def build_prompt(text):
    kw = extract_keywords(text)
    return (
        f"stick figure drawing of {kw}, "
        "simple black ink lines on white paper, "
        "minimalist hand-drawn sketch, clean line art, "
        "educational illustration, no fill, no color, "
        "stick man figures, crude simple drawing"
    )

# -- Load SDXL -----------------------------------------------------------------
print("Loading SDXL (stabilityai/stable-diffusion-xl-base-1.0)...")
print("First load: downloads ~6.9 GB. Cached loads: ~2 min.")
from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler

pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
    variant="fp16",
    use_safetensors=True,
).to("cuda")
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
pipe.enable_model_cpu_offload()

try:
    pipe.enable_xformers_memory_efficient_attention()
    print("  xformers: enabled")
except Exception:
    print("  xformers: not available (OK)")

print(f"\\nVoice  : {VOICE}")
print(f"WorkDir: {WORK_DIR}")
print("\\n SDXL ready. Run Cell 3.")
''')

CELL_DRIVE = code('''\
# == CELL 3: Mount Google Drive ================================================
from google.colab import drive
drive.mount("/content/drive", force_remount=False)

DRIVE_FOLDER = "/content/drive/MyDrive/Unlearned"
os.makedirs(DRIVE_FOLDER, exist_ok=True)
print(f"Drive ready: {DRIVE_FOLDER}")
print("\\n Drive mounted. Run Cell 4.")
''')

CELL_INPUT = code('''\
# == CELL 4: Enter Title & Paste Script =======================================
# Run this cell. Two text boxes appear.
# Type your episode title in the top box.
# Paste your full script in the large box.
# Click Load Script, then run Cell 5.

import ipywidgets as widgets
from IPython.display import display, clear_output

_title_box = widgets.Text(
    value="Episode 1 Your Title Here",
    description="Title:",
    layout=widgets.Layout(width="90%"),
    style={"description_width": "60px"},
)
_script_box = widgets.Textarea(
    value="",
    placeholder="Paste your full script here...",
    description="Script:",
    layout=widgets.Layout(width="90%", height="320px"),
    style={"description_width": "60px"},
)
_btn = widgets.Button(description="Load Script", button_style="success")
_out = widgets.Output()

def _load(_):
    global EPISODE_TITLE, _raw
    EPISODE_TITLE = _title_box.value.strip()
    _raw = _script_box.value.strip()
    with _out:
        clear_output()
        if not _raw:
            print("Paste your script first!")
        elif not EPISODE_TITLE:
            print("Enter a title first!")
        else:
            _wc  = len(_raw.split())
            _est = round(_wc / 2.8 / 60, 1)
            print(f"Script : {_wc} words  ->  ~{_est} min video")
            print(f"Episode: {EPISODE_TITLE}")
            print("\\n Script loaded. Run Cell 5.")

_btn.on_click(_load)
display(_title_box, _script_box, _btn, _out)
''')

CELL_PARSE_VOICE = code('''\
# == CELL 5: Parse Script & Generate Voiceover ================================
import edge_tts, asyncio, re, json
import nest_asyncio; nest_asyncio.apply()

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
    return float(json.loads(r.stdout)[\'format\'][\'duration\'])

async def _tts(text, path):
    comm = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, pitch=VOICE_PITCH)
    await comm.save(path)

if "_raw" not in dir() or not _raw:
    raise RuntimeError("Run Cell 4 first and click Load Script!")

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
with open(f\'{WORK_DIR}/episode_title.txt\', \'w\') as _f:
    _f.write(EPISODE_TITLE)

_total = sum(s[\'duration\'] for s in SCENE_DATA)
print(f"\\nTotal : {_total:.0f}s  ({_total/60:.1f} min)  |  Scenes: {len(SCENE_DATA)}")
print("\\n Voiceover done. Run Cell 6.")
''')

CELL_IMAGES = code('''\
# == CELL 6: Generate SDXL Stick Figure Images ================================
import json, os, torch

if "pipe" not in dir():
    raise RuntimeError("Run Cell 2 first to load the SDXL pipeline!")
if "SCENE_DATA" not in dir():
    with open(f\'{WORK_DIR}/scene_data.json\') as _f:
        SCENE_DATA = json.load(_f)

_n = len(SCENE_DATA)
_est = max(1, round(_n * 25 / 60))
print(f"Generating {_n} stick figure images with SDXL...")
print(f"Estimated time: ~{_est} min on T4 GPU\\n")

for _i, _sc in enumerate(SCENE_DATA):
    _img_path = _sc[\'image\']

    if os.path.exists(_img_path):
        print(f"  [{_i+1}/{_n}] cached  {os.path.basename(_img_path)}")
        continue

    _prompt = build_prompt(_sc[\'text\'])
    print(f"  [{_i+1}/{_n}] {_sc[\'duration\']:.1f}s  {_sc[\'text\'][:50]}...")
    print(f"    prompt: {_prompt[:80]}...")

    with torch.inference_mode():
        _image = pipe(
            prompt=_prompt,
            negative_prompt=NEG_PROMPT,
            width=1280,
            height=720,
            num_inference_steps=20,
            guidance_scale=7.5,
        ).images[0]

    _image.save(_img_path)
    print(f"    saved: {os.path.basename(_img_path)}")

print(f"\\n All {_n} images done. Run Cell 7.")
''')

CELL_MUSIC = code('''\
# == CELL 7: Generate Background Music ========================================
import numpy as np, wave, os, subprocess

if "SCENE_DATA" not in dir():
    import json
    with open(f\'{WORK_DIR}/scene_data.json\') as _f:
        SCENE_DATA = json.load(_f)

_total_dur = sum(s["duration"] for s in SCENE_DATA)
_music_dur = _total_dur + 10.0

SR = 44100
t  = np.linspace(0, _music_dur, int(SR * _music_dur), endpoint=False)

# C major pentatonic ambient drone
_NOTES = [130.81, 155.56, 174.61, 196.00, 233.08,
          261.63, 311.13, 349.23, 392.00, 466.16]
_AMPS  = [0.30,   0.18,   0.22,   0.26,   0.16,
          0.18,   0.11,   0.13,   0.16,   0.09]

mix = np.zeros_like(t)
for _freq, _amp in zip(_NOTES, _AMPS):
    _w  = _amp       * np.sin(2 * np.pi * _freq * t)
    _w += _amp * 0.3 * np.sin(2 * np.pi * _freq * 2 * t)
    _w += _amp * 0.1 * np.sin(2 * np.pi * _freq * 3 * t)
    mix += _w * (0.90 + 0.10 * np.sin(2 * np.pi * 0.07 * t + _freq))

mix /= (np.max(np.abs(mix)) + 1e-9)
mix *= 0.55

_fi = min(int(SR * 4.0), len(mix) // 4)
_fo = min(int(SR * 7.0), len(mix) // 4)
mix[:_fi]  *= np.linspace(0, 1, _fi)
mix[-_fo:] *= np.linspace(1, 0, _fo)

_wav     = f\'{WORK_DIR}/ambient_music.wav\'
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

print(f"Music: {_music_dur:.0f}s ambient pentatonic drone -> {MUSIC_MP3}")
print("\\n Music done. Run Cell 8.")
''')

CELL_ASSEMBLE = code('''\
# == CELL 8: Assemble Final Video =============================================
import json, os, re, subprocess

if "SCENE_DATA" not in dir():
    with open(f\'{WORK_DIR}/scene_data.json\') as _f:
        SCENE_DATA = json.load(_f)
if "EPISODE_TITLE" not in dir():
    with open(f\'{WORK_DIR}/episode_title.txt\') as _f:
        EPISODE_TITLE = _f.read().strip()
if "MUSIC_MP3" not in dir():
    MUSIC_MP3 = f\'{WORK_DIR}/ambient_music.mp3\'

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
        _zp = f"z=\'if(lte(zoom\\,1.0)\\,1.12\\,zoom-0.0003)\':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':d={_nf}"

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
print("\\n Assembly done. Run Cell 9 to download.")
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
    print(f"\\n Complete!")
    print(f"Episode : {EPISODE_TITLE}")
    print(f"Duration: ~{_total:.1f} min")
''')

# ── NOTEBOOK ───────────────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE, CELL_INSTALL, CELL_SETUP, CELL_DRIVE,
    CELL_INPUT, CELL_PARSE_VOICE, CELL_IMAGES,
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
