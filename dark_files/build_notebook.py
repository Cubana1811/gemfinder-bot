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
print("📦  Installing packages (3–5 min first time)...")

import subprocess
pkgs = [
    "edge-tts",
    "diffusers>=0.31.0",
    "transformers>=4.40.0",
    "accelerate",
    "imageio[ffmpeg]",
    "moviepy",
    "scipy",
    "sentencepiece",
    "protobuf",
]
subprocess.run(
    ["pip", "install", "-q", "--upgrade"] + pkgs,
    check=True
)

# Verify FFmpeg
r = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
print(f"✅  {r.stdout.splitlines()[0]}" if r.returncode == 0 else "❌  FFmpeg missing")
print("✅  All packages installed!")
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
# ── STEP 3: PASTE YOUR DARK FILES SCRIPT HERE ───────────────────
#
#  ✏️  Replace the example below with your full episode script.
#  Each paragraph becomes one scene.  Longer paragraph = longer clip.
# ─────────────────────────────────────────────────────────────────

EPISODE_TITLE = "The Classified Files"

YOUR_SCRIPT = \"\"\"
In the summer of 1984, a small town in rural Ohio reported something that would be buried
for decades. Three witnesses saw lights hovering above the forest. By morning, six square
miles of trees were dead. The government arrived within hours.

The official explanation was a chemical spill from a nearby plant. But the plant had been
closed for two years. Not a single employee was interviewed. Not a single sample was tested.
The report was sealed before the week was out.

The local newspaper editor who first broke the story disappeared three weeks later. His files
were gone. His sources went silent. The case was never opened.

What really happened in Millbrook that night has never been explained. The documents we have
obtained tell a very different story — one the government has spent forty years trying to erase.
\"\"\"

# ── Voice options ────────────────────────────────────────────────
# Uncomment one voice (GuyNeural is the default Dark Files voice)
VOICE         = "en-US-GuyNeural"        # Deep authoritative male  ← DEFAULT
# VOICE       = "en-US-EricNeural"       # Serious male narrator
# VOICE       = "en-US-ChristopherNeural"# Calm, grave male voice
# VOICE       = "en-GB-RyanNeural"       # British male (BBC documentary feel)

SPEAKING_RATE  = "-10%"    # Slower = more dramatic
SPEAKING_PITCH = "-3Hz"    # Slightly deeper tone

# ─────────────────────────────────────────────────────────────────
words = len(YOUR_SCRIPT.split())
print(f"📺  Episode    : {EPISODE_TITLE}")
print(f"🎙️   Voice      : {VOICE}")
print(f"📝  Words      : {words}")
print(f"⏱️   Est. length: ~{words / (110/60):.0f} seconds  ({words / (110/60) / 60:.1f} min)")
""")

CELL_PARSER = code("""\
# ── STEP 4: Scene parser + Dark Files prompt engine ─────────────

# ── Dark Files visual prompt database ───────────────────────────
DARK_AESTHETIC = (
    "dark atmospheric cinematography, cold desaturated blue color palette, "
    "dramatic noir low-key lighting, deep crushed shadows, film grain texture, "
    "documentary thriller style, cinematic 16:9 widescreen, "
    "mysterious haunting atmosphere, ultra realistic, photorealistic, "
    "high contrast, professional cinematography"
)

DARK_NEGATIVE = (
    "bright sunny day, colorful cheerful, cartoon, animated, illustration, "
    "blurry, low quality, distorted, watermark, text overlay, logo, nsfw, "
    "happy atmosphere, over-exposed, white background, daytime"
)

VISUAL_MAP = [
    (r'forest|woods|trees|woodland',
     'dark misty forest at night, fog between ancient trees, faint moonlight'),
    (r'facility|complex|plant|factory|warehouse',
     'abandoned industrial facility at dusk, chain-link fence, security floodlights, concrete'),
    (r'laborator|lab|research|scientist',
     'dark sterile government laboratory corridor, sealed blast doors, cold fluorescent light'),
    (r'city|town|street|urban|neighborhood',
     'dark rain-slicked city street at night, distant neon reflections, empty pavement'),
    (r'ocean|sea|river|lake|water|coast',
     'dark turbulent water surface at night, storm clouds, cold dramatic moonlight'),
    (r'desert|nevada|arizona|wasteland|remote|plains',
     'remote desert landscape at dusk, dramatic storm clouds building, desolate empty road'),
    (r'prison|jail|detention|cell|incarcerat',
     'dark prison corridor at night, harsh single overhead light, iron bars casting long shadows'),
    (r'courtroom|trial|judge|lawyer|testimony|verdict',
     'dark courtroom interior, single overhead spotlight on witness stand, wooden benches, tension'),
    (r'church|chapel|cathedral|cemetery|grave|tombstone',
     'gothic fog-covered cemetery at midnight, crumbling headstones, cold moonlight through clouds'),
    (r'hospital|medical|morgue|autopsy|clinic',
     'abandoned hospital corridor, flickering fluorescent lights, peeling walls, cold sterile blue'),
    (r'police|detective|investig|crime scene|sheriff',
     'crime scene at night, yellow police tape in the wind, distant red-blue police lights in fog'),
    (r'document|file|report|classif|declassif|evidence|record',
     'close-up of classified government documents on a table, dramatic side-lighting, heavy black redactions'),
    (r'disappear|vanish|missing|abduct|gone',
     'empty dark room, single overturned chair, door ajar, single dim bulb swinging, eerie silence'),
    (r'government|military|pentagon|CIA|FBI|NSA|agency|federal|intelligence',
     'imposing government building at night, surveillance cameras, concrete facade, distant floodlights'),
    (r'witness|survivor|victim|family|mother|father|child|brother|sister',
     'shadowy silhouette of a person standing at a dark window at night, back-lit, motionless'),
    (r'secret|hidden|cover|buried|suppress|conceal',
     'heavy vault door in darkness, single flashlight beam, rusted locks, deep shadows'),
    (r'helicopter|aircraft|military aircraft|jet|plane',
     'military helicopters flying at night with search beams, dark overcast sky, rotor motion blur'),
    (r'phone|call|wiretap|surveillance|listen|intercept',
     'vintage rotary phone on a dark desk, reel-to-reel recording equipment, sinister single lamp'),
    (r'newspaper|media|press|headline|journalist|editor|broadcast',
     'dark newspaper archive room, stacked yellowed papers under a single lamp, vintage film aesthetic'),
    (r'night|midnight|3.?am|dark|after dark|evening|dusk|dawn',
     'deep night environment, minimal isolated light sources, heavy fog, mysterious still atmosphere'),
    (r'road|highway|bridge|tunnel|path|route',
     'empty dark highway stretching to infinity at night, faint headlights in the distance, fog'),
    (r'19[0-9]{2}|20[0-2][0-9]|decade|era|century|year',
     'cinematic historical recreation, period-appropriate environment, dramatic vintage film grain'),
    (r'body|remains|skeleton|bones|buried|grave',
     'dark woodland clearing at night, disturbed earth, police forensic flashlights in the dark'),
    (r'explosion|fire|burn|smoke|destroy|demolish',
     'smoldering ruins at night, distant flames reflecting on wet ground, emergency lights in smoke'),
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

def make_prompt(scene_text):
    low = scene_text.lower()
    matched = []
    for pattern, visual in VISUAL_MAP:
        if re.search(pattern, low, re.IGNORECASE):
            matched.append(visual)
    if matched:
        base = ', '.join(matched[:2])
    else:
        base = 'dark mysterious empty environment, dramatic single light source, heavy shadows, fog'
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
    return float(json.loads(r.stdout)['format']['duration'])

print(f"🎙️   Generating voiceover  ({VOICE})...\\n")
audio_paths, vtt_paths, durations = [], [], []

for i, scene in enumerate(scenes):
    ap = f'/content/dark_files/audio/scene_{i:03d}.mp3'
    vp = f'/content/dark_files/audio/scene_{i:03d}.vtt'
    asyncio.run(gen_voice_simple(scene, VOICE, SPEAKING_RATE, SPEAKING_PITCH, ap))
    d = audio_dur(ap)
    with open(vp, 'w') as f:
        f.write(f"WEBVTT\\n\\n00:00.000 --> {int(d//60):02d}:{d%60:06.3f}\\n{scene}\\n\\n")
    audio_paths.append(ap); vtt_paths.append(vp); durations.append(d)
    print(f"  ✅  Scene {i+1}/{len(scenes)}: {d:.2f}s  |  {scene[:55]}...")

total_duration = sum(durations)
print(f"\\n✅  Voiceover complete!")
print(f"⏱️   Total duration: {total_duration:.1f}s  ({total_duration/60:.1f} min)")
""")

CELL_LOAD_MODEL = code("""\
# ── STEP 6: Load Stable Diffusion 1.5 image model ───────────────
#
#  SD 1.5: ~4 GB download — runs perfectly on free T4 GPU.
#  Generates one cinematic image per scene; FFmpeg adds
#  Ken Burns pan/zoom motion to create video clips.
# ─────────────────────────────────────────────────────────────────
import torch
from diffusers import StableDiffusionPipeline

torch.cuda.empty_cache()
print("Loading Stable Diffusion 1.5 (~4 GB — first run only, please wait)...\\n")

pipe = StableDiffusionPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5",
    torch_dtype=torch.float16,
    cache_dir='/content/dark_files/cache',
    safety_checker=None,
    requires_safety_checker=False,
)
pipe = pipe.to("cuda")

print(f"\\n✅  Stable Diffusion 1.5 loaded!")
print(f"    VRAM used: {torch.cuda.memory_allocated()/1e9:.2f} GB / 16 GB")
""")

CELL_GEN_CLIPS = code("""\
# ── STEP 7: Generate cinematic images + Ken Burns motion clips ───
#
#  Stable Diffusion generates one dark cinematic image per scene.
#  FFmpeg applies Ken Burns pan/zoom to turn each image into video.
#  Fast, memory-safe, cinematic results.
# ─────────────────────────────────────────────────────────────────
import time

KEN_BURNS = [
    "zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "zoompan=z='min(zoom+0.0012,1.4)':x='min(iw-iw/zoom,iw/2-(iw/zoom/2)+in*0.4)':y='ih/2-(ih/zoom/2)'",
    "zoompan=z='min(zoom+0.0012,1.4)':x='iw/2-(iw/zoom/2)':y='max(0,ih/2-(ih/zoom/2)-in*0.3)'",
    "zoompan=z='max(1.0,1.5-in*0.0018)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "zoompan=z='1.35':x='min(iw-iw/zoom,in*0.6)':y='ih/2-(ih/zoom/2)'",
]

def gen_image(prompt, neg, img_path, seed=0):
    gen = torch.Generator(device='cuda').manual_seed(seed)
    img = pipe(
        prompt=prompt,
        negative_prompt=neg,
        width=768, height=432,
        num_inference_steps=30,
        guidance_scale=7.5,
        generator=gen,
    ).images[0]
    img.save(img_path)

def image_to_video(img_path, out_path, duration, effect_idx=0):
    fps    = 25
    frames = int(duration * fps) + 2
    effect = KEN_BURNS[effect_idx % len(KEN_BURNS)]
    subprocess.run([
        'ffmpeg', '-loop', '1', '-i', img_path,
        '-vf', f"{effect}:d={frames}:s=768x432,fps={fps}",
        '-t', str(duration),
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
        '-pix_fmt', 'yuv420p', out_path, '-y'
    ], capture_output=True, check=True)

print(f"Generating {len(scenes)} cinematic clips ...\\n{'='*65}")
clip_paths = []
t0 = time.time()

for i, (scene, dur) in enumerate(zip(scenes, durations)):
    img_path = f'/content/dark_files/clips/scene_{i:03d}.png'
    out_path = f'/content/dark_files/clips/clip_{i:03d}.mp4'
    prompt, neg = make_prompt(scene)

    print(f"\\nScene {i+1}/{len(scenes)} ({dur:.1f}s)")
    print(f"    {prompt[:85]}...")

    t1 = time.time()
    gen_image(prompt, neg, img_path, seed=i * 17 + 42)
    image_to_video(img_path, out_path, dur, effect_idx=i)
    clip_paths.append(out_path)

    elapsed = time.time() - t1
    done    = i + 1
    eta     = (time.time() - t0) / done * (len(scenes) - done)
    print(f"    Done: {elapsed:.0f}s  |  ETA: ~{eta/60:.0f} min remaining")

print(f"\\nAll clips done! Total: {(time.time()-t0)/60:.1f} min")
""")

CELL_MUSIC = code("""\
# ── STEP 8: Generate dark ambient background music ───────────────
from transformers import pipeline as hf_pipeline
import scipy.io.wavfile as wav

# Free GPU memory from video model first
del pipe
torch.cuda.empty_cache()

print("🎵  Loading MusicGen-small ...")
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

print("🎵  Generating 30-second dark ambient loop ...")
music = music_pipe(MUSIC_PROMPT, forward_params={"do_sample": True, "max_new_tokens": 1500})

raw_wav = '/content/dark_files/audio/music_raw.wav'
wav.write(raw_wav, music[0]['sampling_rate'], music[0]['audio'].T)

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
print(f"✅  Music ready  ({total_duration:.0f}s, fades out at end)")
""")

CELL_ASSEMBLE = code("""\
# ── STEP 9: Assemble clips with fade transitions ─────────────────

def add_fades(src, dst, dur, fade_dur=0.4):
    \"\"\"Add fade-in + fade-out to a clip.\"\"\"
    fade_out_start = max(0, dur - fade_dur)
    subprocess.run([
        'ffmpeg', '-i', src,
        '-vf', (f'fade=t=in:st=0:d={fade_dur},'
                f'fade=t=out:st={fade_out_start:.2f}:d={fade_dur}'),
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
        '-pix_fmt', 'yuv420p', dst, '-y'
    ], capture_output=True, check=True)

print("✂️   Adding fade transitions to each clip ...")
faded_paths = []
for i, (cp, dur) in enumerate(zip(clip_paths, durations)):
    fp = f'/content/dark_files/clips/clip_{i:03d}_faded.mp4'
    add_fades(cp, fp, dur)
    faded_paths.append(fp)
    print(f"  ✅  Clip {i+1}/{len(scenes)} — fade in/out applied")

# Concatenate all faded clips
concat_list = '/content/dark_files/concat.txt'
with open(concat_list, 'w') as f:
    for p in faded_paths:
        f.write(f"file '{p}'\\n")

raw_video = '/content/dark_files/final/video_raw.mp4'
subprocess.run([
    'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_list,
    '-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-pix_fmt', 'yuv420p',
    raw_video, '-y'
], capture_output=True, check=True)
print("\\n✅  Clips concatenated")

# Concatenate all voiceover segments
audio_list = '/content/dark_files/audio_concat.txt'
with open(audio_list, 'w') as f:
    for p in audio_paths:
        f.write(f"file '{p}'\\n")

full_voice = '/content/dark_files/audio/voice_full.mp3'
subprocess.run([
    'ffmpeg', '-f', 'concat', '-safe', '0', '-i', audio_list,
    '-c:a', 'copy', full_voice, '-y'
], capture_output=True, check=True)

# Merge video + voiceover
video_with_voice = '/content/dark_files/final/video_voiced.mp4'
subprocess.run([
    'ffmpeg', '-i', raw_video, '-i', full_voice,
    '-map', '0:v', '-map', '1:a',
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
    '-shortest', video_with_voice, '-y'
], capture_output=True, check=True)
print("✅  Voiceover merged")
""")

CELL_GRADE = code("""\
# ── STEP 10: Apply Dark Files cinematic color grade ──────────────

print("🎨  Applying Dark Files color grade ...")
print("    → Cold blue channel shift")
print("    → Crushed blacks + compressed highlights")
print("    → Desaturated tones (0.65 saturation)")
print("    → High contrast (1.3)")
print("    → Subtle film grain")

DARK_FILES_GRADE = ",".join([
    # Cold blue shift: reduce red slightly, boost blue
    "colorchannelmixer=rr=0.82:rg=0.01:rb=0.0:gr=0.0:gg=0.88:gb=0.04:br=0.0:bg=0.05:bb=1.1",
    # S-curve: crush blacks, compress highlights
    "curves=all='0/0 0.18/0.08 0.5/0.44 0.82/0.72 1/0.87'",
    # Desaturate + contrast boost + slight darken
    "eq=saturation=0.65:contrast=1.3:brightness=-0.04:gamma=1.05",
    # Subtle film grain
    "noise=alls=3:allf=t+u",
    # Gentle detail sharpening
    "unsharp=5:5:0.35:3:3:0.0"
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
# ── STEP 13: Preview + download ──────────────────────────────────

print("🎬  Loading preview ...\\n")
display(Video(final_video, width=704, height=480, embed=True))

print("\\n📥  Downloading your Dark Files video ...")
if IN_COLAB:
    colab_files.download(final_video)
else:
    print(f"   File saved at: {final_video}")

print(\"\"\"
✅  YOUR VIDEO IS READY FOR YOUTUBE

YouTube Upload Checklist:
  ✅  MP4 container  (H.264 + AAC)
  ✅  16:9 aspect ratio
  ✅  25 fps
  ✅  192 kbps stereo audio
  ✅  Synced captions burned in
  ✅  Dark Files cinematic color grade
  ✅  Professional neural voiceover
  ✅  Dark ambient background music (royalty-free)

💡  Pro tips after upload:
  • Add a custom thumbnail in YouTube Studio
  • Paste your script as the video description for SEO
  • Add chapter markers manually for longer episodes
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
