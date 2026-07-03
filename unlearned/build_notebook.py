"""
Build the Unlearned Video Generator Colab notebook.
Run: python build_notebook.py
Output: unlearned_generator.ipynb

UNLEARNED CHANNEL STYLE:
  Visual  : PIL-drawn doodle stick-figure images per scene (no GPU)
  Sync    : Each clip = exact TTS audio duration (frame-perfect)
  Voice   : en-US-AndrewNeural via edge-tts  (-5% rate, 0Hz pitch)
  Music   : Pentatonic numpy loop (light, upbeat educational)
  Motion  : Ken Burns zoom per scene (alternating directions)
  Captions: SRT burned via ffmpeg subtitles filter
  Assembly: FFmpeg concat + amix
"""
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src}

def code(src):
    return {"cell_type": "code", "execution_count": None,
            "metadata": {}, "outputs": [], "source": src}

# ── CELL 1: Title ──────────────────────────────────────────────────────────────

CELL_TITLE = md("""\
# UNLEARNED — Automated Video Generator
### Psychology · Ancient History · Behavioral Science
---

**What this notebook does:**

| Cell | What it does |
|------|-------------|
| Cell 1 | Install packages (run once per session) |
| Cell 2 | Setup — directories, voice settings |
| Cell 3 | Upload your `.txt` script → voiceover generated automatically |
| Cell 4 | Draw one doodle image per scene (PIL, no GPU, ~0.1s/scene) |
| Cell 5 | Ken Burns motion clips — each clip = exact voiceover duration |
| Cell 6 | Generate background music (pentatonic, upbeat educational) |
| Cell 7 | Assemble all clips into one raw video |
| Cell 8 | Burn synced captions onto the video |
| Cell 9 | Mix in background music at 15% volume |
| Cell 10 | Download final MP4 |

> **No GPU required.** No Midjourney. No Canva. You write the script — everything else is automatic.
""")

# ── CELL 2: Install ────────────────────────────────────────────────────────────

CELL_INSTALL = code("""\
# ── CELL 1: Install packages (run once per Colab session) ────────────────────
import subprocess, sys

def _sh(*cmd):
    r = subprocess.run(list(cmd), capture_output=True, text=True)
    return r.returncode == 0

print('Installing system packages...')
_sh('apt-get', 'install', '-y', '-q', 'ffmpeg', 'libass-dev')
print('  ffmpeg + libass: ok')

print('Installing Python packages...')
for _pkg in ['edge-tts', 'Pillow', 'numpy', 'nest_asyncio']:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', _pkg],
                   capture_output=True)
    print(f'  {_pkg}: ok')

print('\\nAll packages installed. Run Cell 2.')
""")

# ── CELL 3: Setup ──────────────────────────────────────────────────────────────

CELL_SETUP = code("""\
# ── CELL 2: Setup — directories and voice settings ───────────────────────────
import os, json, re, subprocess, asyncio
import nest_asyncio
nest_asyncio.apply()

WORK_DIR  = '/content/unlearned'
IMG_DIR   = f'{WORK_DIR}/images'
AUDIO_DIR = f'{WORK_DIR}/audio'
CLIP_DIR  = f'{WORK_DIR}/clips'
for _d in [WORK_DIR, IMG_DIR, AUDIO_DIR, CLIP_DIR]:
    os.makedirs(_d, exist_ok=True)

VOICE       = 'en-US-AndrewNeural'
VOICE_RATE  = '-5%'
VOICE_PITCH = '0Hz'
MUSIC_VOL   = 0.15   # 15% background music volume

EPISODE_TITLE = 'Episode 1'   # ← change if you like; overwritten by Cell 3

print(f'Work dir  : {WORK_DIR}')
print(f'Voice     : {VOICE}  rate={VOICE_RATE}  pitch={VOICE_PITCH}')
print(f'Music vol : {int(MUSIC_VOL*100)}%')
print('\\nSetup done. Run Cell 3 to upload your script.')
""")

# ── CELL 4: Script upload + voiceover ─────────────────────────────────────────

CELL_VOICE = code("""\
# ── CELL 3: Upload your script (.txt) → voiceover + scene data ───────────────
# 1. Run this cell.
# 2. Click Choose Files and pick your script saved as a plain .txt file.
# 3. Voiceover is generated automatically — one audio file per scene.
# 4. scene_data.json is saved for all subsequent cells.

import edge_tts, asyncio, json, os, re, subprocess, time
from google.colab import files as _gcf
import nest_asyncio; nest_asyncio.apply()

if 'WORK_DIR'   not in dir(): WORK_DIR   = '/content/unlearned'
if 'AUDIO_DIR'  not in dir(): AUDIO_DIR  = f'{WORK_DIR}/audio'
if 'IMG_DIR'    not in dir(): IMG_DIR    = f'{WORK_DIR}/images'
if 'VOICE'      not in dir(): VOICE      = 'en-US-AndrewNeural'
if 'VOICE_RATE' not in dir(): VOICE_RATE = '-5%'
if 'VOICE_PITCH' not in dir(): VOICE_PITCH = '0Hz'
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(IMG_DIR,   exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse(text, max_words=22):
    text = re.sub(r'[ \\t]+', ' ', text.strip())
    sents = re.split(r'(?<=[.!?])\\s+', text)
    scenes, buf, wc = [], [], 0
    for s in sents:
        s = s.strip()
        if not s: continue
        w = len(s.split())
        if wc + w > max_words and buf:
            scenes.append(' '.join(buf))
            buf, wc = [s], w
        else:
            buf.append(s); wc += w
    if buf: scenes.append(' '.join(buf))
    return [s for s in scenes if s.strip()]

def _dur(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path],
        capture_output=True, text=True)
    return float(json.loads(r.stdout)['format']['duration'])

async def _tts(text, audio_path, vtt_path):
    comm     = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, pitch=VOICE_PITCH)
    submaker = edge_tts.SubMaker()
    with open(audio_path, 'wb') as af:
        async for chunk in comm.stream():
            if chunk['type'] == 'audio':
                af.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                try:
                    submaker.feed(chunk)
                except TypeError:
                    submaker.create_sub((chunk['offset'], chunk['duration']), chunk['text'])
    with open(vtt_path, 'w', encoding='utf-8') as vf:
        try:
            vf.write(submaker.get_subs())
        except AttributeError:
            vf.write(submaker.generate_subs())

# ── Upload ────────────────────────────────────────────────────────────────────
print('Click Choose Files and select your script as a .txt file.')
_up = _gcf.upload()
if not _up:
    raise RuntimeError('No file uploaded.')

_fname = list(_up.keys())[0]
_raw   = _up[_fname].decode('utf-8', errors='replace').strip()

# Episode title from filename (strip .txt, replace _ and - with spaces)
_base = os.path.splitext(_fname)[0]
EPISODE_TITLE = re.sub(r'[_\\-]+', ' ', _base).strip().title()
with open(f'{WORK_DIR}/episode_title.txt', 'w') as _f:
    _f.write(EPISODE_TITLE)

_wc  = len(_raw.split())
_est = round(_wc / 2.8 / 60, 1)
print(f'\\nFile   : {_fname}')
print(f'Title  : {EPISODE_TITLE}')
print(f'Words  : {_wc}  (~{_est} min video)')

# ── Parse & generate ──────────────────────────────────────────────────────────
print('\\nParsing scenes...')
_scenes = _parse(_raw)
print(f'  {len(_scenes)} scenes')

print('Generating voiceover (edge-tts Andrew Neural)...')
SCENE_DATA = []
_loop = asyncio.get_event_loop()
for _i, _text in enumerate(_scenes):
    _ap  = f'{AUDIO_DIR}/scene_{_i:04d}.mp3'
    _vp  = f'{AUDIO_DIR}/scene_{_i:04d}.vtt'
    for _try in range(3):
        try:
            _loop.run_until_complete(_tts(_text, _ap, _vp))
            break
        except Exception as _e:
            if _try == 2: raise RuntimeError(f'TTS failed scene {_i}: {_e}')
            time.sleep(2 ** _try)
    _d = _dur(_ap)
    SCENE_DATA.append({
        'idx':    _i,
        'text':   _text,
        'duration': _d,
        'audio':  _ap,
        'vtt':    _vp,
        'image':  f'{IMG_DIR}/scene_{_i:04d}.png',
    })
    _suf = '...' if len(_text) > 55 else ''
    print(f'  [{_i+1}/{len(_scenes)}] {_d:.1f}s  {_text[:55]}{_suf}')

with open(f'{WORK_DIR}/scene_data.json', 'w') as _f:
    json.dump(SCENE_DATA, _f, indent=2, ensure_ascii=False)

_total = sum(s['duration'] for s in SCENE_DATA)
print(f'\\nTotal  : {_total:.0f}s  ({_total/60:.1f} min)  |  {len(SCENE_DATA)} scenes')
print('Voiceover done. Run Cell 4.')
""")

# ── CELL 5: PIL Doodle Images ──────────────────────────────────────────────────

CELL_DOODLE = code("""\
# ── CELL 4: PIL Doodle Image Generation — no GPU needed ─────────────────────
import json, os, re, math
from PIL import Image, ImageDraw, ImageFont

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'IMG_DIR'   not in dir(): IMG_DIR   = f'{WORK_DIR}/images'
os.makedirs(IMG_DIR, exist_ok=True)

if 'SCENE_DATA' not in dir():
    _jp = f'{WORK_DIR}/scene_data.json'
    if not os.path.exists(_jp): raise RuntimeError('Run Cell 3 first.')
    with open(_jp) as _f: SCENE_DATA = json.load(_f)

W, H = 1280, 720

# ── Palette ───────────────────────────────────────────────────────────────────
C = {
    'orange': (245, 130,  13),
    'blue':   ( 45,  95, 191),
    'green':  ( 58, 158,  58),
    'yellow': (245, 197,  24),
    'red':    (217,  64,  64),
    'brown':  (139,  94,  60),
    'sky':    (110, 181, 232),
    'tan':    (196, 150,  90),
    'white':  (255, 255, 255),
    'black':  (  0,   0,   0),
}

def _font(sz):
    for p in [
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    ]:
        try: return ImageFont.truetype(p, sz)
        except: pass
    return ImageFont.load_default()

def _wrap(text, draw, font, max_w):
    words = text.split()
    lines, buf = [], []
    for w in words:
        test = ' '.join(buf + [w])
        bb = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_w:
            buf.append(w)
        else:
            if buf: lines.append(' '.join(buf))
            buf = [w]
    if buf: lines.append(' '.join(buf))
    return lines or ['']

# ── Background ────────────────────────────────────────────────────────────────
def _fill_bg(draw, text):
    w = text.lower()
    if any(x in w for x in ['ancient','prehistoric','cave','stone age','neanderthal',
                              'fossil','egypt','rome','mesopotamia','empire','babylon','tribal']):
        draw.rectangle([0, 0, W, H], fill=C['tan'])
        return 'tan'
    if any(x in w for x in ['ocean','sea','underwater','marine','fish','shark','whale','swim','dive']):
        draw.rectangle([0, 0, W, H], fill=C['blue'])
        return 'blue'
    if any(x in w for x in ['nature','forest','tree','evolv','savanna','jungle','outdoor','grass','wild']):
        draw.rectangle([0, 0, W, H], fill=C['sky'])
        draw.rectangle([0, int(H * 0.65), W, H], fill=C['green'])
        return 'outdoor'
    if any(x in w for x in ['fire','night','ritual','torch','primitive','flame','burnt']):
        draw.rectangle([0, 0, W, H], fill=C['orange'])
        return 'orange'
    if any(x in w for x in ['science','lab','dna','neuron','atom','chemical','research','molecule']):
        draw.rectangle([0, 0, W, H], fill=C['blue'])
        return 'blue'
    draw.rectangle([0, 0, W, H], fill=C['white'])
    return 'white'

# ── Frame type ────────────────────────────────────────────────────────────────
def _frame_type(text):
    w = text.lower()
    if re.search(r'\\b\\d[\\d,]*\\s*(million|thousand|billion|year|day|hour|percent|%)', w):
        return 'concept_text'
    if any(x in w for x in ['evolv','transform','stages','progress','develop',
                              'became','sequence','steps','million year','from ape']):
        return 'evolution'
    if any(x in w for x in ['brain','stress','anxiety','dopamine','cortisol',
                              'ego','addiction','trauma','cortex','neuron']):
        return 'villain'
    if any(x in w for x in ['why','wonder','confus','strange','but wait',
                              'hmm','question','unsure','what if']):
        return 'reaction'
    if any(x in w for x in ['world','globe','earth','everywhere','planet',
                              'global','species','continent','across the']):
        return 'globe'
    if any(x in w for x in ['called','known as','labeled','type of',
                              'named','kind of','defined as']):
        return 'diagram'
    return 'scene'

# ── Expression ────────────────────────────────────────────────────────────────
def _expr(text):
    w = text.lower()
    if any(x in w for x in ['happy','joy','excit','celebrat','laugh',
                              'smile','success','win','achieve','triumph']):
        return 'happy'
    if any(x in w for x in ['sad','cry','depress','grief','hurt','loss','mourn']):
        return 'sad'
    if any(x in w for x in ['angry','rage','frustrat','mad','furious']):
        return 'angry'
    if any(x in w for x in ['fear','scared','panic','anxious','stress',
                              'terror','horror','dread']):
        return 'scared'
    return 'neutral'

# ── Stick figure ──────────────────────────────────────────────────────────────
def _figure(draw, cx, cy, size=120, expr='neutral', col=None):
    col = col or C['black']
    hr  = max(int(size * 0.22), 14)
    lw  = max(int(size * 0.045), 3)
    ew  = max(int(hr * 0.18), 3)
    exo = int(hr * 0.35)
    eyo = int(hr * 0.18)
    ms  = int(hr * 0.42)
    mby = int(hr * 0.35)

    draw.ellipse([cx-hr, cy-hr, cx+hr, cy+hr], outline=col, width=lw)
    draw.ellipse([cx-exo-ew, cy-eyo-ew, cx-exo+ew, cy-eyo+ew], fill=col)
    draw.ellipse([cx+exo-ew, cy-eyo-ew, cx+exo+ew, cy-eyo+ew], fill=col)

    if expr == 'happy':
        draw.arc([cx-ms, cy+mby-ms//2, cx+ms, cy+mby+ms//2], 0, 180, fill=col, width=lw)
    elif expr == 'sad':
        draw.arc([cx-ms, cy+mby-ms//2, cx+ms, cy+mby+ms//2], 180, 360, fill=col, width=lw)
        draw.line([cx-int(hr*0.45), cy-int(hr*0.42), cx-int(hr*0.1), cy-int(hr*0.6)],
                  fill=col, width=lw)
        draw.line([cx+int(hr*0.1), cy-int(hr*0.6), cx+int(hr*0.45), cy-int(hr*0.42)],
                  fill=col, width=lw)
    elif expr == 'angry':
        draw.line([cx-ms, cy+mby, cx+ms, cy+mby], fill=col, width=lw)
        draw.line([cx-int(hr*0.5), cy-int(hr*0.58), cx-int(hr*0.08), cy-int(hr*0.3)],
                  fill=col, width=lw+1)
        draw.line([cx+int(hr*0.08), cy-int(hr*0.3), cx+int(hr*0.5), cy-int(hr*0.58)],
                  fill=col, width=lw+1)
    elif expr == 'scared':
        draw.arc([cx-ms, cy+mby-ms//2, cx+ms, cy+mby+ms//2], 180, 360, fill=col, width=lw)
        draw.ellipse([cx-exo-ew*2, cy-eyo-ew*2, cx-exo+ew*2, cy-eyo+ew*2], outline=col, width=lw)
        draw.ellipse([cx+exo-ew*2, cy-eyo-ew*2, cx+exo+ew*2, cy-eyo+ew*2], outline=col, width=lw)
    else:
        draw.line([cx-ms, cy+mby, cx+ms, cy+mby], fill=col, width=lw)

    neck_y = cy + hr
    body_b = cy + hr + int(size * 0.55)
    draw.line([cx, neck_y, cx, body_b], fill=col, width=lw)
    arm_y = cy + hr + int(size * 0.22)
    draw.line([cx, arm_y, cx-int(size*0.32), arm_y+int(size*0.18)], fill=col, width=lw)
    draw.line([cx, arm_y, cx+int(size*0.32), arm_y+int(size*0.18)], fill=col, width=lw)
    draw.line([cx, body_b, cx-int(size*0.28), body_b+int(size*0.40)], fill=col, width=lw)
    draw.line([cx, body_b, cx+int(size*0.28), body_b+int(size*0.40)], fill=col, width=lw)

# ── Thought bubble ────────────────────────────────────────────────────────────
def _bubble(draw, cx, cy, hr, snippet):
    bx = cx + hr + 20
    by = cy - hr - 90
    bw = min(300, W - bx - 30)
    bh = 85
    if bx + bw > W - 20:
        bx = cx - bw - hr - 20
    for shape in [
        [bx,    by,    bx+bw,    by+bh],
        [bx-18, by+14, bx+48,    by+bh+22],
        [bx+bw-48, by+14, bx+bw+18, by+bh+22],
        [bx+bw//4, by-18, bx+3*bw//4, by+28],
    ]:
        draw.ellipse(shape, fill=C['white'], outline=C['black'], width=3)
    f = _font(24)
    txt = (snippet[:26] + '...').upper() if len(snippet) > 26 else snippet.upper()
    bb  = draw.textbbox((0, 0), txt, font=f)
    draw.text((bx+(bw-(bb[2]-bb[0]))//2, by+bh//2-14), txt, fill=C['black'], font=f)
    dot_x = cx + max(int(hr * 0.4), 8)
    for fy_off in [15, 35, 55]:
        r = 5
        dy = cy - hr - fy_off
        draw.ellipse([dot_x-r, dy-r, dot_x+r, dy+r], fill=C['black'])

# ── Hourglass ─────────────────────────────────────────────────────────────────
def _hourglass(draw, cx, cy, s=105):
    s2 = s // 2
    draw.polygon([(cx, cy-s2), (cx-s2, cy-s), (cx+s2, cy-s)],
                 fill=C['yellow'], outline=C['black'])
    draw.polygon([(cx, cy+s2), (cx-s2, cy+s), (cx+s2, cy+s)],
                 fill=C['yellow'], outline=C['black'])
    draw.polygon([(cx, cy+s2), (cx-s2//2, cy+s-14), (cx+s2//2, cy+s-14)],
                 fill=C['brown'])
    draw.rectangle([cx-8, cy-s2, cx+8, cy+s2], fill=C['yellow'], outline=C['black'])

# ── Globe ─────────────────────────────────────────────────────────────────────
def _globe(draw, cx, cy, r=108):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=C['blue'], outline=C['black'], width=4)
    for bx1, by1, bx2, by2 in [
        (-r//3, -r//2, r//3, 2),
        (-r//2, 0, -r//8, r//2),
        (r//8,  r//4, r//2, r//2),
    ]:
        draw.ellipse([cx+bx1, cy+by1, cx+bx2, cy+by2], fill=C['green'])
    for fy in [-0.45, 0.0, 0.45]:
        oy  = cy + int(r * fy)
        rr2 = max(int(r*r - (r*fy)**2), 0)
        hw  = int(rr2 ** 0.5)
        if hw > 4:
            draw.arc([cx-hw, oy-10, cx+hw, oy+10], 0, 180, fill='white', width=2)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=C['black'], width=4)

# ── Arrow label ───────────────────────────────────────────────────────────────
def _arrow(draw, x1, y1, x2, y2, label):
    draw.line([x1, y1, x2, y2], fill=C['yellow'], width=7)
    ang = math.atan2(y2 - y1, x2 - x1)
    ahl = 22
    p1  = (x2 + int(ahl * math.cos(ang + math.pi*5/6)),
           y2 + int(ahl * math.sin(ang + math.pi*5/6)))
    p2  = (x2 + int(ahl * math.cos(ang - math.pi*5/6)),
           y2 + int(ahl * math.sin(ang - math.pi*5/6)))
    draw.polygon([(x2, y2), p1, p2], fill=C['yellow'])
    f  = _font(34)
    bb = draw.textbbox((0, 0), label.upper(), font=f)
    draw.text((x2+18, y2-(bb[3]-bb[1])//2), label.upper(), fill=C['black'], font=f)

# ── Evolution row ─────────────────────────────────────────────────────────────
def _evo_row(draw, fig_y=310):
    xs     = [W//6, W//2, 5*W//6]
    labels = ['EARLY', 'MIDDLE', 'NOW']
    sizes  = [80, 95, 110]
    exprs  = ['neutral', 'neutral', 'happy']
    for i, (px, lb, sz, ex) in enumerate(zip(xs, labels, sizes, exprs)):
        _figure(draw, px, fig_y, sz, ex)
        f  = _font(28)
        bb = draw.textbbox((0, 0), lb, font=f)
        draw.text((px-(bb[2]-bb[0])//2, fig_y+sz+10), lb, fill=C['black'], font=f)
        if i < 2:
            ax1 = px + sz//2 + 12
            ax2 = xs[i+1] - sizes[i+1]//2 - 12
            draw.line([ax1, fig_y, ax2, fig_y], fill=C['black'], width=5)
            draw.polygon([(ax2+14, fig_y), (ax2-4, fig_y-11), (ax2-4, fig_y+11)],
                         fill=C['black'])

# ── Brain villain ─────────────────────────────────────────────────────────────
def _villain(draw, cx, cy, label):
    r = 95
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=C['blue'], outline=C['black'], width=5)
    for bx, by in [(-r+10, -r+12), (0, -r+6), (r-10, -r+12)]:
        draw.ellipse([cx+bx-26, cy+by-26, cx+bx+26, cy+by+26],
                     fill=C['blue'], outline=C['black'], width=3)
    ew = 10
    draw.ellipse([cx-38-ew, cy-18-ew, cx-38+ew, cy-18+ew], fill=C['black'])
    draw.ellipse([cx+38-ew, cy-18-ew, cx+38+ew, cy-18+ew], fill=C['black'])
    draw.line([cx-48, cy-38, cx-24, cy-24], fill=C['black'], width=4)
    draw.line([cx+24, cy-24, cx+48, cy-38], fill=C['black'], width=4)
    draw.arc([cx-34, cy+14, cx+34, cy+52], 0, 180, fill=C['black'], width=4)
    f  = _font(44)
    lb = label.upper()
    bb = draw.textbbox((0, 0), lb, font=f)
    draw.text(((W-(bb[2]-bb[0]))//2, 28), lb, fill=C['red'], font=f)

# ── Top label ─────────────────────────────────────────────────────────────────
def _top_label(draw, text, col=None):
    col = col or C['black']
    f   = _font(46)
    bb  = draw.textbbox((0, 0), text.upper(), font=f)
    draw.text(((W-(bb[2]-bb[0]))//2, 28), text.upper(), fill=col, font=f)

# ── Stat extractor ────────────────────────────────────────────────────────────
def _stat(text):
    m = re.search(
        r'\\b(\\d[\\d,]*)\\s*(million|thousand|billion|percent|%|year|day|hour|minute)?',
        text.lower())
    if m:
        n = m.group(1)
        u = (m.group(2) or '').upper()
        return f'{n} {u}'.strip()
    words = [w for w in re.findall(r'\\b[A-Za-z]{5,}\\b', text)
             if w.lower() not in {'about','after','before','their','there',
                                   'would','could','should','being','every'}]
    return words[0].upper() if words else 'FACT'

# ── Caption band (bottom of frame) ────────────────────────────────────────────
def _caption_band(draw, text, bg):
    f      = _font(36)
    lines  = _wrap(text, draw, f, W - 100)[:3]
    lh     = 46
    tot_h  = len(lines) * lh + 28
    y0     = H - tot_h - 8
    strip  = (235, 235, 235) if bg in ('white', 'tan') else (0, 0, 0)
    draw.rectangle([0, y0, W, H], fill=strip)
    txt_c  = C['black'] if bg in ('white', 'tan', 'outdoor') else C['white']
    out_c  = C['white'] if txt_c == C['black'] else C['black']
    y = y0 + 14
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=f)
        tw = bb[2] - bb[0]
        x  = (W - tw) // 2
        for dx, dy in [(-1,-1),(1,-1),(-1,1),(1,1)]:
            draw.text((x+dx, y+dy), line, fill=out_c, font=f)
        draw.text((x, y), line, fill=txt_c, font=f)
        y += lh

# ── Main rendering loop ───────────────────────────────────────────────────────
_n     = len(SCENE_DATA)
_exist = sum(1 for s in SCENE_DATA if os.path.exists(s['image']))
if _exist == _n:
    print(f'All {_n} images already on disk. Run Cell 5.')
else:
    print(f'Drawing {_n} doodle images (PIL, no GPU)...')
    for _i, _sc in enumerate(SCENE_DATA):
        _out = _sc['image']
        if os.path.exists(_out):
            print(f'  [{_i+1}/{_n}] cached')
            continue

        _txt = _sc['text']
        _img = Image.new('RGB', (W, H), C['white'])
        _d   = ImageDraw.Draw(_img)
        _bg  = _fill_bg(_d, _txt)
        _ft  = _frame_type(_txt)
        _ex  = _expr(_txt)
        _mx, _my = W // 2, int(H * 0.37)

        if _ft == 'concept_text':
            _hourglass(_d, _mx, _my, 105)
            _st = _stat(_txt)
            f   = _font(72)
            bb  = _d.textbbox((0, 0), _st, font=f)
            _d.text((_mx-(bb[2]-bb[0])//2, _my-165), _st, fill=C['red'], font=f)
            _top_label(_d, 'DID YOU KNOW?', C['blue'])

        elif _ft == 'evolution':
            _evo_row(_d, fig_y=300)

        elif _ft == 'villain':
            _kws = [w for w in re.findall(r'\\b[A-Za-z]{4,}\\b', _txt)
                    if w.lower() in {'brain','stress','anxiety','dopamine','cortisol',
                                      'ego','addiction','trauma','fear','depression'}]
            _villain(_d, _mx, _my, _kws[0] if _kws else 'BRAIN')

        elif _ft == 'reaction':
            _fig_hr = max(int(120 * 0.22), 14)
            _figure(_d, _mx, int(H * 0.40), 120, 'neutral')
            _bubble(_d, _mx, int(H * 0.40), _fig_hr, _txt[:32])

        elif _ft == 'globe':
            _globe(_d, _mx, _my, 108)

        elif _ft == 'diagram':
            _fig_y = int(H * 0.40)
            _figure(_d, int(W * 0.58), _fig_y, 110, _ex)
            _lb_kws = [w for w in re.findall(r'\\b[A-Za-z]{4,}\\b', _txt)
                       if w.lower() not in {'this','that','they','them','with',
                                             'from','have','been','were','would',
                                             'could','also','when','then'}]
            _lb = _lb_kws[0].upper() if _lb_kws else 'TYPE'
            _arrow(_d, int(W*0.18), int(H*0.28), int(W*0.46), _fig_y, _lb)

        else:  # scene
            _two = any(x in _txt.lower() for x in
                       ['together','friend','group','team','meet','social',
                        'both','they','people','us','each other','pair','couple'])
            if _two:
                _figure(_d, _mx - 135, int(H*0.40), 108, _ex)
                _figure(_d, _mx + 135, int(H*0.40), 108, 'neutral')
            else:
                _figure(_d, _mx, int(H*0.40), 130, _ex)

        _caption_band(_d, _txt, _bg)
        _img.save(_out)
        print(f'  [{_i+1}/{_n}] {_ft:<13} {_txt[:52]}')

    print(f'\\nAll {_n} images drawn. Run Cell 5.')
""")

# ── CELL 6: Ken Burns Motion Clips ────────────────────────────────────────────

CELL_MOTION = code("""\
# ── CELL 5: Ken Burns motion clips — each clip = exact voiceover duration ────
import json, os, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'CLIP_DIR'  not in dir(): CLIP_DIR  = f'{WORK_DIR}/clips'
os.makedirs(CLIP_DIR, exist_ok=True)

if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_n = len(SCENE_DATA)
print(f'Building {_n} Ken Burns clips...')
_clips = []

for _i, _sc in enumerate(SCENE_DATA):
    _img   = _sc['image']
    _audio = _sc['audio']
    _dur   = _sc['duration']
    _clip  = f'{CLIP_DIR}/clip_{_i:04d}.mp4'
    _clips.append(_clip)

    if os.path.exists(_clip):
        print(f'  [{_i+1}/{_n}] cached')
        continue

    _nf = max(int(_dur * 30), 2)
    _p  = _i % 4
    if   _p == 0:
        _zp = f"z='min(zoom+0.0003,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"
    elif _p == 1:
        _zp = f"z='min(zoom+0.0003,1.12)':x='0':y='0':d={_nf}"
    elif _p == 2:
        _zp = f"z='min(zoom+0.0003,1.12)':x='iw-iw/zoom':y='ih-ih/zoom':d={_nf}"
    else:
        _zp = f"z='if(lte(zoom,1.0),1.12,zoom-0.0003)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"

    _r = subprocess.run([
        'ffmpeg', '-y',
        '-loop', '1', '-i', _img,
        '-i', _audio,
        '-filter_complex',
            f'[0:v]scale=1280:720,zoompan={_zp}:s=1280x720:fps=30[v]',
        '-map', '[v]', '-map', '1:a',
        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest', '-pix_fmt', 'yuv420p',
        _clip,
    ], capture_output=True, text=True)

    if _r.returncode != 0:
        print(f'  Clip {_i} error:\\n{_r.stderr[-500:]}')
        raise RuntimeError(f'Clip {_i} failed')

    print(f'  [{_i+1}/{_n}] {_dur:.1f}s  clip_{_i:04d}.mp4')

import json as _j2
_j2_path = f'{WORK_DIR}/clip_list_paths.json'
with open(_j2_path, 'w') as _f:
    _j2.dump(_clips, _f)

print(f'\\n{_n} clips done. Run Cell 6.')
""")

# ── CELL 7: Background Music ───────────────────────────────────────────────────

CELL_MUSIC = code("""\
# ── CELL 6: Generate background music (pentatonic, light educational) ─────────
import numpy as np, wave, os, subprocess, json

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_total_dur = sum(s['duration'] for s in SCENE_DATA)
_music_dur = _total_dur + 10.0

# 90-second base loop — FFmpeg will extend it to full length
_LOOP = 90.0
SR    = 44100
t     = np.linspace(0, _LOOP, int(SR * _LOOP), endpoint=False)

# Light upbeat pentatonic scale (C major pentatonic, higher register)
_NOTES = [261.63, 293.66, 329.63, 392.00, 440.00,
          523.25, 587.33, 659.25, 784.00, 880.00]
_AMPS  = [0.25,   0.18,   0.20,   0.22,   0.16,
          0.12,   0.10,   0.12,   0.11,   0.08]

mix = np.zeros(len(t), dtype=np.float32)
for _freq, _amp in zip(_NOTES, _AMPS):
    mix += _amp       * np.sin(2 * np.pi * _freq * t).astype(np.float32)
    mix += _amp * 0.3 * np.sin(2 * np.pi * _freq * 2 * t).astype(np.float32)
    mix += _amp * 0.1 * np.sin(2 * np.pi * _freq * 3 * t).astype(np.float32)

# Pluck envelope — soft attack, gentle decay per note period
_env = np.exp(-0.8 * (t % 0.5))
mix *= _env.astype(np.float32)
mix /= (np.max(np.abs(mix)) + 1e-9)
mix *= 0.55

_fi = int(SR * 3.0)
_fo = int(SR * 4.0)
mix[:_fi]  *= np.linspace(0, 1, _fi, dtype=np.float32)
mix[-_fo:] *= np.linspace(1, 0, _fo, dtype=np.float32)

_loop_wav = f'{WORK_DIR}/music_loop.wav'
MUSIC_MP3  = f'{WORK_DIR}/background_music.mp3'

_pcm = (mix * 32767).clip(-32768, 32767).astype(np.int16)
with wave.open(_loop_wav, 'w') as _wf:
    _wf.setnchannels(1)
    _wf.setsampwidth(2)
    _wf.setframerate(SR)
    _wf.writeframes(_pcm.tobytes())

_fade_st = max(0, _music_dur - 5.0)
subprocess.run([
    'ffmpeg', '-y',
    '-stream_loop', '-1', '-i', _loop_wav,
    '-t', str(_music_dur),
    '-af', f'afade=t=out:st={_fade_st:.1f}:d=5',
    '-q:a', '4', MUSIC_MP3,
], capture_output=True, check=True)
os.remove(_loop_wav)

print(f'Music: {_music_dur:.0f}s  ({MUSIC_MP3})')
print('Run Cell 7.')
""")

# ── CELL 8: Assemble Clips ────────────────────────────────────────────────────

CELL_ASSEMBLE = code("""\
# ── CELL 7: Assemble all clips into one raw video ─────────────────────────────
import json, os, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'CLIP_DIR'  not in dir(): CLIP_DIR  = f'{WORK_DIR}/clips'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_clips_file = f'{WORK_DIR}/clip_list_paths.json'
if os.path.exists(_clips_file):
    with open(_clips_file) as _f:
        _clips = json.load(_f)
else:
    _clips = sorted([
        f'{CLIP_DIR}/{fn}' for fn in os.listdir(CLIP_DIR)
        if fn.startswith('clip_') and fn.endswith('.mp4')
    ])

_list = f'{WORK_DIR}/clip_list.txt'
with open(_list, 'w') as _f:
    for _c in _clips:
        _f.write(f"file '{_c}'\\n")

RAW_VIDEO = f'{WORK_DIR}/video_raw.mp4'
print(f'Concatenating {len(_clips)} clips...')
_r = subprocess.run([
    'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
    '-i', _list, '-c', 'copy', RAW_VIDEO,
], capture_output=True, text=True)

if _r.returncode != 0:
    print(_r.stderr[-800:])
    raise RuntimeError('Concat failed')

_mb = os.path.getsize(RAW_VIDEO) / 1_048_576
print(f'Raw video: {_mb:.1f} MB  ({RAW_VIDEO})')
print('Run Cell 8.')
""")

# ── CELL 9: Burn Captions ─────────────────────────────────────────────────────

CELL_CAPTIONS = code("""\
# ── CELL 8: Build SRT captions and burn onto video ────────────────────────────
import json, os, re, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'RAW_VIDEO' not in dir(): RAW_VIDEO = f'{WORK_DIR}/video_raw.mp4'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

# ── Build SRT from VTT files (word-level if VTT exists, else scene-level) ─────
def _vtt_to_entries(vtt_path, offset=0.0):
    if not os.path.exists(vtt_path):
        return []
    with open(vtt_path, encoding='utf-8') as f:
        content = f.read()
    entries = []
    for block in re.split(r'\\n\\n+', content.strip()):
        lines = block.strip().split('\\n')
        tline = next((l for l in lines if '-->' in l), None)
        if not tline: continue
        m = re.match(
            r'(\\d+):(\\d+):(\\d+\\.\\d+)\\s+-->\\s+(\\d+):(\\d+):(\\d+\\.\\d+)', tline)
        if not m: continue
        s = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3)) + offset
        e = int(m.group(4))*3600 + int(m.group(5))*60 + float(m.group(6)) + offset
        txt_lines = [l for l in lines if l and '-->' not in l
                     and not l.startswith('WEBVTT') and not l.strip().isdigit()]
        txt = ' '.join(txt_lines).strip()
        if txt:
            entries.append((s, e, txt))
    return entries

def _ts(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f'{h:02d}:{m:02d}:{s:06.3f}'.replace('.', ',')

# Build master SRT
_all_entries = []
_offset      = 0.0
for _sc in SCENE_DATA:
    _vtt     = _sc.get('vtt', '')
    _entries = _vtt_to_entries(_vtt, _offset)
    if _entries:
        _all_entries.extend(_entries)
    else:
        # fallback: whole scene as one subtitle
        _all_entries.append((_offset, _offset + _sc['duration'], _sc['text']))
    _offset += _sc['duration']

_srt_path = f'{WORK_DIR}/captions.srt'
with open(_srt_path, 'w', encoding='utf-8') as f:
    for idx, (s, e, txt) in enumerate(_all_entries, 1):
        f.write(f'{idx}\\n{_ts(s)} --> {_ts(e)}\\n{txt}\\n\\n')
print(f'SRT: {len(_all_entries)} entries -> {_srt_path}')

# ── Burn captions ─────────────────────────────────────────────────────────────
# Escape the path for ffmpeg subtitles filter (colons on Windows, backslashes)
_srt_esc = _srt_path.replace('\\\\', '/').replace(':', '\\\\:')
CAPTIONED_VIDEO = f'{WORK_DIR}/video_captioned.mp4'

_style = (
    "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,Outline=2,Shadow=0,Bold=1,Alignment=2,"
    "MarginV=18"
)
_r = subprocess.run([
    'ffmpeg', '-y',
    '-i', RAW_VIDEO,
    '-vf', f"subtitles='{_srt_esc}':force_style='{_style}'",
    '-c:a', 'copy',
    '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
    CAPTIONED_VIDEO,
], capture_output=True, text=True)

if _r.returncode != 0:
    print('Caption burn failed — copying video without subtitles.')
    print(_r.stderr[-600:])
    import shutil
    shutil.copy2(RAW_VIDEO, CAPTIONED_VIDEO)
else:
    _mb = os.path.getsize(CAPTIONED_VIDEO) / 1_048_576
    print(f'Captioned video: {_mb:.1f} MB')

print('Run Cell 9.')
""")

# ── CELL 10: Mix Audio ────────────────────────────────────────────────────────

CELL_MIX = code("""\
# ── CELL 9: Mix background music at 15% volume ───────────────────────────────
import json, os, re, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'MUSIC_VOL' not in dir(): MUSIC_VOL = 0.15
if 'CAPTIONED_VIDEO' not in dir():
    CAPTIONED_VIDEO = f'{WORK_DIR}/video_captioned.mp4'
if 'MUSIC_MP3'  not in dir():
    MUSIC_MP3 = f'{WORK_DIR}/background_music.mp3'
if not os.path.exists(CAPTIONED_VIDEO):
    CAPTIONED_VIDEO = f'{WORK_DIR}/video_raw.mp4'   # fallback if caption cell skipped

if 'EPISODE_TITLE' not in dir():
    _tp = f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE = open(_tp).read().strip() if os.path.exists(_tp) else 'Episode'

_safe = re.sub(r'[^\\w\\s-]+', '', EPISODE_TITLE).strip().replace(' ', '_')
FINAL_VIDEO = f'{WORK_DIR}/UNLEARNED_{_safe}.mp4'

print(f'Mixing: voiceover (100%) + music ({int(MUSIC_VOL*100)}%)...')
_r = subprocess.run([
    'ffmpeg', '-y',
    '-i', CAPTIONED_VIDEO,
    '-i', MUSIC_MP3,
    '-filter_complex',
        f'[0:a]volume=1.0[vo];[1:a]volume={MUSIC_VOL}[mu];'
        '[vo][mu]amix=inputs=2:duration=first[aout]',
    '-map', '0:v',
    '-map', '[aout]',
    '-c:v', 'copy',
    '-c:a', 'aac', '-b:a', '192k',
    '-shortest',
    FINAL_VIDEO,
], capture_output=True, text=True)

if _r.returncode != 0:
    print('Mix failed:\\n' + _r.stderr[-800:])
    raise RuntimeError('Audio mix failed')

_mb = os.path.getsize(FINAL_VIDEO) / 1_048_576
print(f'\\nFinal video: {FINAL_VIDEO}')
print(f'Size       : {_mb:.1f} MB')
print('Run Cell 10 to download.')
""")

# ── CELL 11: Download ─────────────────────────────────────────────────────────

CELL_DOWNLOAD = code("""\
# ── CELL 10: Download final MP4 ───────────────────────────────────────────────
import os, re, json
from google.colab import files as _gcf

if 'WORK_DIR' not in dir(): WORK_DIR = '/content/unlearned'

if 'FINAL_VIDEO' not in dir():
    _tp = f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE = open(_tp).read().strip() if os.path.exists(_tp) else 'Episode'
    _safe = re.sub(r'[^\\w\\s-]+', '', EPISODE_TITLE).strip().replace(' ', '_')
    FINAL_VIDEO = f'{WORK_DIR}/UNLEARNED_{_safe}.mp4'

if not os.path.exists(FINAL_VIDEO):
    raise RuntimeError(f'Video not found: {FINAL_VIDEO} — Run Cell 9 first.')

# Also download the SRT for YouTube caption upload
_srt = f'{WORK_DIR}/captions.srt'

_mb = os.path.getsize(FINAL_VIDEO) / 1_048_576
print(f'Downloading: {os.path.basename(FINAL_VIDEO)}  ({_mb:.1f} MB)')
_gcf.download(FINAL_VIDEO)

if os.path.exists(_srt):
    print(f'Downloading: captions.srt  (upload to YouTube for auto-captions)')
    _gcf.download(_srt)

if 'SCENE_DATA' not in dir():
    _jp = f'{WORK_DIR}/scene_data.json'
    if os.path.exists(_jp):
        with open(_jp) as _f: SCENE_DATA = json.load(_f)

if 'SCENE_DATA' in dir():
    _total = sum(s['duration'] for s in SCENE_DATA)
    print(f'\\nEpisode  : {EPISODE_TITLE}')
    print(f'Duration : {_total:.0f}s  ({_total/60:.1f} min)')
    print(f'Scenes   : {len(SCENE_DATA)}')

print('\\nDone!')
""")

# ── Notebook assembly ──────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE,
    CELL_INSTALL,
    CELL_SETUP,
    CELL_VOICE,
    CELL_DOODLE,
    CELL_MOTION,
    CELL_MUSIC,
    CELL_ASSEMBLE,
    CELL_CAPTIONS,
    CELL_MIX,
    CELL_DOWNLOAD,
]

NOTEBOOK = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {
        "colab": {"provenance": [], "gpuType": "None"},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
        "accelerator": "None",
    },
    "cells": CELLS,
}

OUT = os.path.join(_HERE, "unlearned_generator.ipynb")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(NOTEBOOK, f, indent=1, ensure_ascii=False)
print(f"Written {len(CELLS)} cells -> {OUT}")
