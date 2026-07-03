"""
Build the Unlearned Video Generator Colab notebook — v4 (Definitive).
Run: python build_notebook.py
Output: unlearned_generator.ipynb

FIXES IN v4 vs v3:
  - REMOVED PIL caption band (was conflicting with ASS burned captions → double text)
  - Full 1280×720 frame for doodle art; ASS captions appear below the art zone
  - Bézier-curve wobble (_sl) — organic curve per line vs. old random jitter
  - Smooth PIL fill + sketchy outline for ellipses (crisp fill, hand-drawn edge)
  - Figure arms: V-raise on happy, guard-raise on scared, punch on angry
  - Watermark moved to top-right (was clashing with top labels)
  - Karplus-Strong string synthesis for music (sounds like guitar/harp)
  - np.random.seed(42) for reproducible music
  - Drawing zone defined: y=30–540; figure center y=285
  - More psychology keywords (mirror neuron, priming, confirmation bias, etc.)
  - ASS captions: yellow text, 2.5 px black outline, proper dual fallback
  - SRT also saved for YouTube upload
  - Master fade-in 0.8 s / fade-out 2.5 s (video + audio both)
  - loudnorm I=-16 LUFS on voiceover
"""
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src}

def code(src):
    return {"cell_type": "code", "execution_count": None,
            "metadata": {}, "outputs": [], "source": src}

# ── CELL 1 ─────────────────────────────────────────────────────────────────────

CELL_TITLE = md("""\
# UNLEARNED — Automated Video Generator  v4
### Psychology · Ancient History · Behavioral Science

| Cell | What it does |
|------|-------------|
| 1 | Install packages |
| 2 | Setup |
| 3 | Upload `.txt` script → voiceover + word-timing VTT |
| 4 | Doodle images — Bézier wobble lines, skin-fill figures, props (no GPU) |
| 5 | Ken Burns motion clips (5 alternating directions) |
| 6 | Background music — Karplus-Strong string synthesis, C-G-Am-F at 112 BPM |
| 7 | Assemble clips |
| 8 | Burn yellow ASS captions (word-level sync) |
| 9 | Mix audio + master fade in/out + loudnorm |
| 10 | Download final MP4 + captions.srt |

**Known tradeoffs (PIL + no-GPU limits):**
- Music sounds like harp/guitar (KS synthesis) — not a real piano sample
- Figures are static per scene — no frame-by-frame animation
- Scene transitions are hard cuts — no crossfade
""")

# ── CELL 2 ─────────────────────────────────────────────────────────────────────

CELL_INSTALL = code("""\
# ── CELL 1: Install ───────────────────────────────────────────────────────────
import subprocess, sys, os

def _sh(*cmd):
    return subprocess.run(list(cmd), capture_output=True, text=True).returncode == 0

print('System packages...')
_sh('apt-get', 'install', '-y', '-q', 'ffmpeg', 'libass-dev', 'fonts-liberation')
print('  ffmpeg + libass + Liberation fonts: ok')

print('Python packages...')
for _pkg in ['edge-tts', 'Pillow', 'numpy', 'nest_asyncio']:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', _pkg],
                   capture_output=True)
    print(f'  {_pkg}: ok')

_lf = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'
print(f'  Liberation Bold: {"found" if os.path.exists(_lf) else "missing — fallback active"}')
print('\\nAll packages ready. Run Cell 2.')
""")

# ── CELL 3 ─────────────────────────────────────────────────────────────────────

CELL_SETUP = code("""\
# ── CELL 2: Setup ─────────────────────────────────────────────────────────────
import os, json, re, subprocess, asyncio
import nest_asyncio; nest_asyncio.apply()

WORK_DIR  = '/content/unlearned'
IMG_DIR   = f'{WORK_DIR}/images'
AUDIO_DIR = f'{WORK_DIR}/audio'
CLIP_DIR  = f'{WORK_DIR}/clips'
for _d in [WORK_DIR, IMG_DIR, AUDIO_DIR, CLIP_DIR]:
    os.makedirs(_d, exist_ok=True)

VOICE        = 'en-US-AndrewNeural'
VOICE_RATE   = '-5%'
VOICE_PITCH  = '0Hz'
MUSIC_VOL    = 0.15

print(f'Work dir  : {WORK_DIR}')
print(f'Voice     : {VOICE}  rate={VOICE_RATE}  pitch={VOICE_PITCH}')
print(f'Music vol : {int(MUSIC_VOL*100)}%')
print('Setup done. Run Cell 3.')
""")

# ── CELL 4: Voiceover ──────────────────────────────────────────────────────────

CELL_VOICE = code("""\
# ── CELL 3: Upload script → voiceover + word-timing VTT ──────────────────────
import edge_tts, asyncio, json, os, re, subprocess, time
from google.colab import files as _gcf
import nest_asyncio; nest_asyncio.apply()

if 'WORK_DIR'    not in dir(): WORK_DIR    = '/content/unlearned'
if 'AUDIO_DIR'   not in dir(): AUDIO_DIR   = f'{WORK_DIR}/audio'
if 'IMG_DIR'     not in dir(): IMG_DIR     = f'{WORK_DIR}/images'
if 'VOICE'       not in dir(): VOICE       = 'en-US-AndrewNeural'
if 'VOICE_RATE'  not in dir(): VOICE_RATE  = '-5%'
if 'VOICE_PITCH' not in dir(): VOICE_PITCH = '0Hz'
os.makedirs(AUDIO_DIR, exist_ok=True); os.makedirs(IMG_DIR, exist_ok=True)

def _parse(text, max_words=22):
    text  = re.sub(r'[ \\t]+', ' ', text.strip())
    sents = re.split(r'(?<=[.!?])\\s+', text)
    scenes, buf, wc = [], [], 0
    for s in sents:
        s = s.strip()
        if not s: continue
        w = len(s.split())
        if wc + w > max_words and buf:
            scenes.append(' '.join(buf)); buf, wc = [s], w
        else:
            buf.append(s); wc += w
    if buf: scenes.append(' '.join(buf))
    return [s for s in scenes if s.strip()]

def _dur(path):
    r = subprocess.run(
        ['ffprobe','-v','quiet','-print_format','json','-show_format',path],
        capture_output=True, text=True)
    return float(json.loads(r.stdout)['format']['duration'])

async def _tts(text, apath, vpath):
    comm = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, pitch=VOICE_PITCH)
    sub  = edge_tts.SubMaker()
    with open(apath, 'wb') as af:
        async for chunk in comm.stream():
            if   chunk['type'] == 'audio': af.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                try:    sub.feed(chunk)
                except: sub.create_sub((chunk['offset'], chunk['duration']), chunk['text'])
    with open(vpath, 'w', encoding='utf-8') as vf:
        try:    vf.write(sub.get_subs())
        except: vf.write(sub.generate_subs())

print('Click Choose Files — select your script as a .txt file.')
_up = _gcf.upload()
if not _up: raise RuntimeError('No file uploaded.')
_fname = list(_up.keys())[0]
_raw   = _up[_fname].decode('utf-8', errors='replace').strip()
_base  = os.path.splitext(_fname)[0]
EPISODE_TITLE = re.sub(r'[_\\-]+', ' ', _base).strip().title()
with open(f'{WORK_DIR}/episode_title.txt','w') as _f: _f.write(EPISODE_TITLE)
print(f'\\nTitle  : {EPISODE_TITLE}')
print(f'Words  : {len(_raw.split())}  (~{round(len(_raw.split())/2.8/60,1)} min)')

_scenes = _parse(_raw)
print(f'\\nParsed {len(_scenes)} scenes. Generating voiceover...')
SCENE_DATA = []
_loop = asyncio.get_event_loop()
for _i, _text in enumerate(_scenes):
    _ap = f'{AUDIO_DIR}/scene_{_i:04d}.mp3'
    _vp = f'{AUDIO_DIR}/scene_{_i:04d}.vtt'
    for _t in range(3):
        try: _loop.run_until_complete(_tts(_text, _ap, _vp)); break
        except Exception as _e:
            if _t == 2: raise RuntimeError(f'TTS failed scene {_i}: {_e}')
            time.sleep(2**_t)
    _d = _dur(_ap)
    SCENE_DATA.append({'idx':_i,'text':_text,'duration':_d,
                       'audio':_ap,'vtt':_vp,
                       'image':f'{IMG_DIR}/scene_{_i:04d}.png'})
    _suf = '...' if len(_text)>55 else ''
    print(f'  [{_i+1}/{len(_scenes)}] {_d:.1f}s  {_text[:55]}{_suf}')

with open(f'{WORK_DIR}/scene_data.json','w') as _f:
    json.dump(SCENE_DATA, _f, indent=2, ensure_ascii=False)
_total = sum(s['duration'] for s in SCENE_DATA)
print(f'\\nTotal: {_total:.0f}s ({_total/60:.1f} min) | {len(SCENE_DATA)} scenes')
print('Voiceover done. Run Cell 4.')
""")

# ── CELL 5: PIL Doodle Images ──────────────────────────────────────────────────

CELL_DOODLE = code("""\
# ── CELL 4: PIL Doodle Images — Bézier wobble, skin-fill, no caption band ─────
import json, os, re, math, random
from PIL import Image, ImageDraw, ImageFont

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'IMG_DIR'   not in dir(): IMG_DIR   = f'{WORK_DIR}/images'
os.makedirs(IMG_DIR, exist_ok=True)
if 'SCENE_DATA' not in dir():
    _jp = f'{WORK_DIR}/scene_data.json'
    if not os.path.exists(_jp): raise RuntimeError('Run Cell 3 first.')
    with open(_jp) as _f: SCENE_DATA = json.load(_f)

W, H = 1280, 720
# Drawing zone: keep art between y=28 and y=545; ASS captions appear below ~560
DZ_TOP = 28    # top of drawing area
DZ_BOT = 545   # bottom of drawing area (leave room for ASS captions)
DZ_MID = (DZ_TOP + DZ_BOT) // 2   # = 286 — vertical center for main elements

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
    'skin':   (255, 210, 165),
    'gray':   (220, 220, 220),
    'dgray':  (150, 150, 150),
    'lblue':  (200, 220, 255),
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
    words = text.split(); lines, buf = [], []
    for w in words:
        test = ' '.join(buf+[w])
        bb = draw.textbbox((0,0),test,font=font)
        if bb[2]-bb[0] <= max_w: buf.append(w)
        else:
            if buf: lines.append(' '.join(buf))
            buf = [w]
    if buf: lines.append(' '.join(buf))
    return lines or ['']

# ── Seeded RNG — deterministic per scene ──────────────────────────────────────
_RNG = random.Random()

# ── BÉZIER WOBBLE PRIMITIVES ──────────────────────────────────────────────────

def _sl(draw, x1, y1, x2, y2, fill, width=3, wob=3):
    '''Sketchy line: quadratic Bézier with perpendicular bend — organic curve.'''
    x1,y1,x2,y2 = int(x1),int(y1),int(x2),int(y2)
    dx,dy  = x2-x1, y2-y1
    dist   = max(int((dx*dx+dy*dy)**0.5), 1)
    if dist < 12:
        draw.line([(x1,y1),(x2,y2)], fill=fill, width=width); return
    # Perpendicular unit vector for bend
    px,py  = -dy/dist, dx/dist
    bend   = _RNG.randint(-wob,wob) * max(dist//16, 1)
    mx     = (x1+x2)//2 + int(px*bend)
    my     = (y1+y2)//2 + int(py*bend)
    # Quadratic Bézier as polyline
    steps  = max(dist//5, 10)
    pts    = []
    for k in range(steps+1):
        t = k/steps
        pts.append((int((1-t)**2*x1 + 2*(1-t)*t*mx + t**2*x2),
                    int((1-t)**2*y1 + 2*(1-t)*t*my + t**2*y2)))
    for k in range(len(pts)-1):
        draw.line([pts[k],pts[k+1]], fill=fill, width=width)

def _se(draw, cx, cy, rx, ry, outline, fill=None, width=3, wob=2):
    '''Sketchy ellipse: smooth PIL fill + wobbly outline polygon.'''
    cx,cy,rx,ry = int(cx),int(cy),max(int(rx),3),max(int(ry),3)
    if fill: draw.ellipse([cx-rx,cy-ry,cx+rx,cy+ry], fill=fill)
    n = max(int((rx+ry)*1.7), 30)
    pts = []
    for k in range(n+1):
        ang = 2*math.pi*k/n
        x   = int(cx+rx*math.cos(ang)) + _RNG.randint(-wob,wob)
        y   = int(cy+ry*math.sin(ang)) + _RNG.randint(-wob,wob)
        pts.append((x,y))
    for k in range(len(pts)-1):
        draw.line([pts[k],pts[k+1]], fill=outline, width=width)

def _sarc(draw, cx, cy, rx, ry, a0, a1, fill, width=3, wob=2):
    '''Sketchy arc from a0 to a1 (degrees).'''
    cx,cy,rx,ry = int(cx),int(cy),max(int(rx),3),max(int(ry),3)
    r0,r1 = math.radians(a0), math.radians(a1)
    if r1 <= r0: r1 += 2*math.pi
    n = max(int((r1-r0)*(rx+ry)/3.5), 8)
    pts = []
    for k in range(n+1):
        t = r0+(r1-r0)*k/n
        pts.append((int(cx+rx*math.cos(t))+_RNG.randint(-wob,wob),
                    int(cy+ry*math.sin(t))+_RNG.randint(-wob,wob)))
    for k in range(len(pts)-1):
        draw.line([pts[k],pts[k+1]], fill=fill, width=width)

def _sp(draw, pts, fill=None, outline=None, width=3, wob=2):
    '''Sketchy polygon: fill solid, outline with Bézier edges.'''
    ipts = [(int(x),int(y)) for x,y in pts]
    if fill: draw.polygon(ipts, fill=fill)
    if outline:
        for k in range(len(ipts)):
            p1,p2 = ipts[k], ipts[(k+1)%len(ipts)]
            _sl(draw, p1[0],p1[1], p2[0],p2[1], outline, width, wob)

# ── BACKGROUND ────────────────────────────────────────────────────────────────
def _fill_bg(draw, text):
    w = text.lower()
    if any(x in w for x in ['ancient','prehistoric','cave','stone age','neanderthal',
                              'fossil','egypt','rome','mesopotamia','empire','babylon','tribal']):
        draw.rectangle([0,0,W,H], fill=C['tan'])
        for y in range(0,H,30): draw.line([0,y,W,y], fill=(175,128,68), width=1)
        return 'tan'
    if any(x in w for x in ['ocean','sea','underwater','marine','fish','shark','whale','swim']):
        draw.rectangle([0,0,W,H], fill=C['blue'])
        for y in range(40,H,55):
            for x in range(0,W,90):
                draw.arc([x,y-9,x+65,y+9], 0,180, fill=(80,130,220), width=2)
        return 'blue'
    if any(x in w for x in ['nature','forest','tree','evolv','savanna','jungle','outdoor','grass','wild']):
        draw.rectangle([0,0,W,H], fill=C['sky'])
        draw.rectangle([0,int(H*0.64),W,H], fill=C['green'])
        for gx in range(25,W,42):
            gy = int(H*0.64)
            for off,ht in [(-5,10),(0,14),(5,10)]:
                draw.line([gx,gy,gx+off,gy-ht], fill=(35,120,35), width=2)
        # Sun
        _se(draw, W-90,70, 36,36, C['yellow'],C['yellow'],3,1)
        for ang in range(0,360,40):
            rad=math.radians(ang)
            draw.line([int(W-90+(36+5)*math.cos(rad)),int(70+(36+5)*math.sin(rad)),
                       int(W-90+(36+18)*math.cos(rad)),int(70+(36+18)*math.sin(rad))],
                      fill=C['yellow'],width=3)
        return 'outdoor'
    if any(x in w for x in ['fire','night','ritual','torch','primitive','flame','burnt']):
        draw.rectangle([0,0,W,H], fill=C['orange'])
        for m in range(0,55,7):
            draw.rectangle([m,m,W-m,H-m],
                           outline=tuple(max(c-m*4,0) for c in C['orange']),width=1)
        return 'orange'
    if any(x in w for x in ['science','lab','dna','neuron','atom','chemical','research','molecule']):
        draw.rectangle([0,0,W,H], fill=C['blue'])
        for gx in range(0,W,65): draw.line([gx,0,gx,H], fill=(58,108,205),width=1)
        for gy in range(0,H,65): draw.line([0,gy,W,gy], fill=(58,108,205),width=1)
        return 'blue'
    draw.rectangle([0,0,W,H], fill=C['white'])
    return 'white'

# ── FRAME TYPE (psychology-aware) ─────────────────────────────────────────────
def _frame_type(text):
    w = text.lower()
    if re.search(r'\\b\\d[\\d,]*\\s*(million|thousand|billion|year|day|hour|percent|%)', w):
        return 'concept_text'
    if any(x in w for x in ['evolv','transform','stages','progress','develop',
                              'became','sequence','steps','million year','from ape']):
        return 'evolution'
    if any(x in w for x in ['brain','stress','anxiety','dopamine','cortisol','ego',
                              'addiction','trauma','cortex','neuron','serotonin',
                              'amygdala','prefrontal','cognitive','confirmation bias',
                              'mirror neuron','priming','placebo']):
        return 'villain'
    if any(x in w for x in ['why','wonder','confus','strange','but wait','hmm',
                              'question','unsure','what if','believe it',
                              'how is that','did you know','turns out']):
        return 'reaction'
    if any(x in w for x in ['world','globe','earth','everywhere','planet',
                              'global','species','continent','across','universal']):
        return 'globe'
    if any(x in w for x in ['called','known as','labeled','type of','named',
                              'kind of','defined as','refers to','this is']):
        return 'diagram'
    if any(x in w for x in ['idea','discover','realiz','invent','insight','aha',
                              'eureka','thought of','came up with','figured out']):
        return 'idea'
    return 'scene'

def _expr(text):
    w = text.lower()
    if any(x in w for x in ['happy','joy','excit','celebrat','laugh','smile',
                              'success','win','achieve','triumph','positive']):
        return 'happy'
    if any(x in w for x in ['sad','cry','depress','grief','hurt','loss','mourn']):
        return 'sad'
    if any(x in w for x in ['angry','rage','frustrat','mad','furious']):
        return 'angry'
    if any(x in w for x in ['fear','scared','panic','anxious','stress','terror','dread']):
        return 'scared'
    return 'neutral'

# ── STICK FIGURE ──────────────────────────────────────────────────────────────
def _figure(draw, cx, cy, size=120, expr='neutral', col=None):
    col  = col or C['black']
    hr   = max(int(size*0.24), 14)   # head radius
    lw   = max(int(size*0.05), 3)    # line width
    ew   = max(int(hr*0.17), 3)      # eye size
    exo  = int(hr*0.37)              # eye x-offset
    eyo  = int(hr*0.18)              # eye y-offset
    ms   = int(hr*0.45)              # mouth half-width
    mby  = int(hr*0.30)              # mouth y (down from center)
    bow  = int(hr*0.54)              # brow half-width
    broy = cy - eyo - int(hr*0.22)  # brow y

    # Head — smooth fill, Bézier outline
    _se(draw, cx, cy, hr, hr, col, C['skin'], lw, 2)
    # Eyes
    draw.ellipse([cx-exo-ew,cy-eyo-ew,cx-exo+ew,cy-eyo+ew], fill=col)
    draw.ellipse([cx+exo-ew,cy-eyo-ew,cx+exo+ew,cy-eyo+ew], fill=col)

    # Brows + mouth per expression
    if expr == 'happy':
        _sl(draw, cx-bow,broy-4, cx-exo+4,broy-2, col,lw,1)
        _sl(draw, cx+exo-4,broy-2, cx+bow,broy-4, col,lw,1)
        _sarc(draw, cx,cy+mby, ms,int(ms*0.45), 0,180, col,lw,2)
    elif expr == 'sad':
        _sl(draw, cx-bow,broy, cx-exo+4,broy-7, col,lw,1)
        _sl(draw, cx+exo-4,broy-7, cx+bow,broy, col,lw,1)
        _sarc(draw, cx,cy+mby+ms//2, ms,int(ms*0.45), 180,360, col,lw,2)
        _sp(draw,[(cx+int(hr*0.56),cy+int(hr*0.28)),
                  (cx+int(hr*0.44),cy+int(hr*0.55)),
                  (cx+int(hr*0.68),cy+int(hr*0.55))], fill=C['sky'])
    elif expr == 'angry':
        _sl(draw, cx-bow,broy-7, cx-exo+4,broy+2, col,lw+1,1)
        _sl(draw, cx+exo-4,broy+2, cx+bow,broy-7, col,lw+1,1)
        _sarc(draw, cx,cy+mby+ms//3, ms,int(ms*0.3), 195,345, col,lw,1)
        for _sx in [-int(hr*0.72), int(hr*0.72)]:
            _sl(draw, cx+_sx,cy-hr-4, cx+_sx,cy-hr-20, C['red'],lw,1)
            _sl(draw, cx+_sx-6,cy-hr-12, cx+_sx+6,cy-hr-12, C['red'],lw,1)
    elif expr == 'scared':
        _sl(draw, cx-bow,broy-9, cx-exo+4,broy, col,lw,1)
        _sl(draw, cx+exo-4,broy, cx+bow,broy-9, col,lw,1)
        _se(draw, cx,cy+mby+7, int(ms*0.58),int(ms*0.54), col,C['white'],lw,1)
        for _ang in range(0,360,45):
            _rad = math.radians(_ang)
            _sl(draw, int(cx+(hr+7)*math.cos(_rad)),int(cy+(hr+7)*math.sin(_rad)),
                      int(cx+(hr+20)*math.cos(_rad)),int(cy+(hr+20)*math.sin(_rad)),
                      col, 2, 0)
    else:
        _sl(draw, cx-bow+5,broy, cx-exo+2,broy, col,lw,1)
        _sl(draw, cx+exo-2,broy, cx+bow-5,broy, col,lw,1)
        _sl(draw, cx-ms//2,cy+mby, cx+ms//2,cy+mby, col,lw,1)

    # Body
    neck_y = cy+hr; body_b = cy+hr+int(size*0.56)
    _sl(draw, cx,neck_y, cx,body_b, col,lw,2)

    # Arms — pose varies by expression
    arm_y = cy+hr+int(size*0.22)
    if expr == 'happy':
        # V-raise celebration
        for _sd in [-1,1]:
            _sl(draw, cx,arm_y, cx+_sd*int(size*0.40),arm_y-int(size*0.32), col,lw,2)
    elif expr == 'scared':
        # Hands up / guard
        for _sd in [-1,1]:
            _sl(draw, cx,arm_y, cx+_sd*int(size*0.28),arm_y-int(size*0.12), col,lw,2)
    elif expr == 'angry':
        # Fists forward
        for _sd in [-1,1]:
            _sl(draw, cx,arm_y, cx+_sd*int(size*0.38),arm_y+int(size*0.05), col,lw,2)
    else:
        # Default bent-elbow arms
        for _sd in [-1,1]:
            _elx = cx+_sd*int(size*0.26); _ely = arm_y+int(size*0.12)
            _hx  = cx+_sd*int(size*0.38); _hy  = arm_y+int(size*0.30)
            _sl(draw, cx,arm_y, _elx,_ely, col,lw,2)
            _sl(draw, _elx,_ely, _hx,_hy, col,lw,2)

    # Legs with knees
    for _sd in [-1,1]:
        _kx = cx+_sd*int(size*0.18); _ky = body_b+int(size*0.22)
        _fx = cx+_sd*int(size*0.30); _fy = body_b+int(size*0.44)
        _sl(draw, cx,body_b, _kx,_ky, col,lw,2)
        _sl(draw, _kx,_ky, _fx,_fy, col,lw,2)

    # Ground shadow
    _sw = int(size*0.40); _sh2 = max(int(size*0.055),3)
    _sby = body_b+int(size*0.44)+_sh2+2
    draw.ellipse([cx-_sw,_sby-_sh2,cx+_sw,_sby+_sh2], fill=C['dgray'])
    return body_b+int(size*0.44)

# ── THOUGHT BUBBLE ────────────────────────────────────────────────────────────
def _bubble(draw, cx, cy, hr, snippet):
    bx = cx+hr+24; by = cy-hr-100
    bw = min(295, W-bx-25); bh = 88
    if bx+bw > W-20: bx = cx-bw-hr-24
    for shp in [(bx,by,bx+bw,by+bh),(bx-18,by+13,bx+46,by+bh+22),
                (bx+bw-46,by+13,bx+bw+18,by+bh+22),(bx+bw//4,by-18,bx+3*bw//4,by+26)]:
        _se(draw,(shp[0]+shp[2])//2,(shp[1]+shp[3])//2,
            (shp[2]-shp[0])//2,(shp[3]-shp[1])//2, C['black'],C['white'],3,2)
    f   = _font(24)
    txt = (snippet[:26]+'...').upper() if len(snippet)>26 else snippet.upper()
    bb  = draw.textbbox((0,0),txt,font=f)
    draw.text((bx+(bw-(bb[2]-bb[0]))//2, by+bh//2-14), txt, fill=C['black'],font=f)
    _dx = cx+max(int(hr*0.42),8)
    for _yoff in [14,34,54]:
        _r=5; _dy=cy-hr-_yoff
        draw.ellipse([_dx-_r,_dy-_r,_dx+_r,_dy+_r], fill=C['black'])

# ── HOURGLASS ─────────────────────────────────────────────────────────────────
def _hourglass(draw, cx, cy, s=100):
    s2=s//2
    _sp(draw,[(cx,cy-s2),(cx-s2,cy-s),(cx+s2,cy-s)],fill=C['yellow'],outline=C['black'],width=3)
    _sp(draw,[(cx,cy+s2),(cx-s2,cy+s),(cx+s2,cy+s)],fill=C['yellow'],outline=C['black'],width=3)
    _sp(draw,[(cx,cy+s2),(cx-s2//2,cy+s-14),(cx+s2//2,cy+s-14)],fill=C['brown'])
    _sl(draw,cx-7,cy-s2,cx-7,cy+s2,C['black'],3)
    _sl(draw,cx+7,cy-s2,cx+7,cy+s2,C['black'],3)
    _sl(draw,cx-7,cy-s2,cx+7,cy-s2,C['black'],3)
    _sl(draw,cx-7,cy+s2,cx+7,cy+s2,C['black'],3)

# ── GLOBE ─────────────────────────────────────────────────────────────────────
def _globe(draw, cx, cy, r=105):
    _se(draw,cx,cy,r,r,C['black'],C['blue'],4,2)
    for bx1,by1,bx2,by2 in [(-r//3,-r//2,r//3,2),(-r//2,0,-r//8,r//2),(r//8,r//4,r//2,r//2)]:
        _se(draw,(cx+bx1+cx+bx2)//2,(cy+by1+cy+by2)//2,
            (bx2-bx1)//2,(by2-by1)//2,C['black'],C['green'],2,2)
    for _fy in [-0.45,0.0,0.45]:
        _oy=cy+int(r*_fy); _rr2=max(int(r*r-(r*_fy)**2),0); _hw=int(_rr2**0.5)
        if _hw>4: _sarc(draw,cx,_oy,_hw,10,0,180,'white',2,1)
    _se(draw,cx,cy,r,r,C['black'],None,4,2)

# ── ARROW ─────────────────────────────────────────────────────────────────────
def _arrow(draw, x1, y1, x2, y2, label):
    _sl(draw,x1,y1,x2,y2,C['yellow'],7,1)
    ang=math.atan2(y2-y1,x2-x1); ahl=22
    p1=(x2+int(ahl*math.cos(ang+math.pi*5/6)),y2+int(ahl*math.sin(ang+math.pi*5/6)))
    p2=(x2+int(ahl*math.cos(ang-math.pi*5/6)),y2+int(ahl*math.sin(ang-math.pi*5/6)))
    _sp(draw,[(x2,y2),p1,p2],fill=C['yellow'])
    f=_font(34); bb=draw.textbbox((0,0),label.upper(),font=f)
    draw.text((x2+20,y2-(bb[3]-bb[1])//2),label.upper(),fill=C['black'],font=f)

# ── EVOLUTION ROW ─────────────────────────────────────────────────────────────
def _evo_row(draw, fig_y=DZ_MID):
    xs,lbs,szs,exs=[W//6,W//2,5*W//6],['EARLY','MIDDLE','NOW'],[76,92,108],['neutral','neutral','happy']
    for i,(px,lb,sz,ex) in enumerate(zip(xs,lbs,szs,exs)):
        _figure(draw,px,fig_y,sz,ex)
        f=_font(27); bb=draw.textbbox((0,0),lb,font=f)
        draw.text((px-(bb[2]-bb[0])//2,fig_y+sz+14),lb,fill=C['black'],font=f)
        if i<2:
            _ax1=px+szs[i]//2+14; _ax2=xs[i+1]-szs[i+1]//2-14
            _sl(draw,_ax1,fig_y,_ax2,fig_y,C['black'],5,1)
            draw.polygon([(_ax2+14,fig_y),(_ax2-4,fig_y-11),(_ax2-4,fig_y+11)],fill=C['black'])

# ── BRAIN VILLAIN ─────────────────────────────────────────────────────────────
def _villain(draw, cx, cy, label):
    r=95
    _se(draw,cx,cy,r,r,C['black'],C['blue'],5,3)
    for _bx,_by in [(-r+13,-r+14),(0,-r+7),(r-13,-r+14)]:
        _se(draw,cx+_bx,cy+_by,25,25,C['black'],C['blue'],3,2)
    ew=10
    draw.ellipse([cx-36-ew,cy-17-ew,cx-36+ew,cy-17+ew],fill=C['black'])
    draw.ellipse([cx+36-ew,cy-17-ew,cx+36+ew,cy-17+ew],fill=C['black'])
    _sl(draw,cx-46,cy-37,cx-22,cy-22,C['black'],4,1)
    _sl(draw,cx+22,cy-22,cx+46,cy-37,C['black'],4,1)
    _sarc(draw,cx,cy+15,34,22,0,180,C['black'],4,1)
    f=_font(46); lb=label.upper(); bb=draw.textbbox((0,0),lb,font=f)
    draw.text(((W-(bb[2]-bb[0]))//2,DZ_TOP+6),lb,fill=C['red'],font=f)

# ── LIGHTBULB ─────────────────────────────────────────────────────────────────
def _lightbulb(draw, cx, cy, size=68):
    r=size//2
    _se(draw,cx,cy-r//2,r,r,C['black'],C['yellow'],3,2)
    bx=cx-r//3; by=cy+r//2
    _sp(draw,[(bx,by),(bx+2*r//3,by),(bx+2*r//3,by+r//2),(bx,by+r//2)],
        fill=C['brown'],outline=C['black'],width=2)
    for _sr in [-r//3,0,r//3]:
        _sl(draw,cx+_sr,cy-r,cx+_sr,cy-r-11,C['yellow'],2,0)
    for _alb in [30,90,150]:
        _rad=math.radians(_alb)
        _sl(draw,int(cx+(r+4)*math.cos(_rad)),int(cy-r//2+(r+4)*math.sin(_rad)),
                  int(cx+(r+16)*math.cos(_rad)),int(cy-r//2+(r+16)*math.sin(_rad)),
                  C['yellow'],2,0)

# ── STAT EXTRACTOR ────────────────────────────────────────────────────────────
def _stat(text):
    m=re.search(r'\\b(\\d[\\d,]*)\\s*(million|thousand|billion|percent|%|year|day|hour|minute)?',text.lower())
    if m:
        n=m.group(1); u=(m.group(2) or '').upper()
        return f'{n} {u}'.strip()
    words=[w for w in re.findall(r'\\b[A-Za-z]{5,}\\b',text)
           if w.lower() not in {'about','after','before','their','there',
                                  'would','could','should','being','every','which'}]
    return words[0].upper() if words else 'FACT'

# ── TOP LABEL ─────────────────────────────────────────────────────────────────
def _top_label(draw, text, col=None):
    col=col or C['black']; f=_font(46)
    bb=draw.textbbox((0,0),text.upper(),font=f)
    draw.text(((W-(bb[2]-bb[0]))//2, DZ_TOP+4), text.upper(), fill=col, font=f)

# ── WATERMARK (top-right, avoids centered labels) ─────────────────────────────
def _watermark(draw, bg):
    f=_font(20); txt='UNLEARNED'
    bb=draw.textbbox((0,0),txt,font=f); tw,th=bb[2]-bb[0],bb[3]-bb[1]
    box_col = C['white'] if bg in ('blue','orange') else C['white']
    txt_col = C['blue']
    draw.rectangle([W-tw-34, 12, W-12, th+26], fill=box_col, outline=C['blue'], width=2)
    draw.text((W-tw-26, 16), txt, fill=txt_col, font=f)

# ── RENDER LOOP ───────────────────────────────────────────────────────────────
_n     = len(SCENE_DATA)
_exist = sum(1 for s in SCENE_DATA if os.path.exists(s['image']))
if _exist == _n:
    print(f'All {_n} images already on disk. Run Cell 5.')
else:
    print(f'Drawing {_n} doodle images (Bézier wobble, skin-fill, no caption band)...')
    for _i, _sc in enumerate(SCENE_DATA):
        _out=_sc['image']
        if os.path.exists(_out): print(f'  [{_i+1}/{_n}] cached'); continue

        _RNG.seed(_i*137+7)   # deterministic wobble per scene
        _txt=_sc['text']
        _img=Image.new('RGB',(W,H),C['white'])
        _d  =ImageDraw.Draw(_img)
        _bg =_fill_bg(_d,_txt)
        _ft =_frame_type(_txt)
        _ex =_expr(_txt)
        _mx =W//2; _my=DZ_MID

        if _ft == 'concept_text':
            _hourglass(_d,_mx,_my,100)
            _st=_stat(_txt); f=_font(72)
            bb=_d.textbbox((0,0),_st,font=f)
            _d.text((_mx-(bb[2]-bb[0])//2,_my-165),_st,fill=C['red'],font=f)
            _top_label(_d,'DID YOU KNOW?',C['blue'])

        elif _ft == 'evolution':
            _evo_row(_d,fig_y=_my)

        elif _ft == 'villain':
            _kws=[w for w in re.findall(r'\\b[A-Za-z]{4,}\\b',_txt)
                  if w.lower() in {'brain','stress','anxiety','dopamine','cortisol','ego',
                                    'addiction','trauma','fear','depression','serotonin',
                                    'amygdala','cortex','priming','placebo','bias'}]
            _villain(_d,_mx,_my,_kws[0] if _kws else 'BRAIN')

        elif _ft == 'reaction':
            _fhr=max(int(120*0.24),14)
            _figure(_d,_mx,_my,120,'neutral')
            _bubble(_d,_mx,_my,_fhr,_txt[:32])

        elif _ft == 'globe':
            _globe(_d,_mx,_my,105)

        elif _ft == 'diagram':
            _fy=_my
            _figure(_d,int(W*0.60),_fy,108,_ex)
            _lb_kws=[w for w in re.findall(r'\\b[A-Za-z]{4,}\\b',_txt)
                     if w.lower() not in {'this','that','they','them','with','from',
                                           'have','been','were','would','could','also',
                                           'when','then','some','more','most','kind'}]
            _lb=_lb_kws[0].upper() if _lb_kws else 'TYPE'
            _arrow(_d,int(W*0.14),int(DZ_MID-80),int(W*0.47),_fy,_lb)

        elif _ft == 'idea':
            _fy=_my+40
            _figure(_d,_mx,_fy,118,'happy')
            _lightbulb(_d,_mx,_fy-max(int(118*0.24),14)-88,65)

        else:  # scene
            _two=any(x in _txt.lower() for x in
                     ['together','friend','group','team','meet','social','both',
                      'they','people','us','each other','pair','couple','someone',
                      'another person','social proof','conformity','authority'])
            if _two:
                _figure(_d,_mx-140,_my,106,_ex)
                _figure(_d,_mx+140,_my,106,'neutral')
            else:
                _figure(_d,_mx,_my,128,_ex)

        _watermark(_d,_bg)
        _img.save(_out)
        print(f'  [{_i+1}/{_n}] {_ft:<13} {_txt[:50]}')

    print(f'\\nAll {_n} images drawn. Run Cell 5.')
""")

# ── CELL 6: Ken Burns ─────────────────────────────────────────────────────────

CELL_MOTION = code("""\
# ── CELL 5: Ken Burns motion clips ───────────────────────────────────────────
import json, os, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'CLIP_DIR'  not in dir(): CLIP_DIR  = f'{WORK_DIR}/clips'
os.makedirs(CLIP_DIR, exist_ok=True)
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_n=len(SCENE_DATA); _clips=[]; print(f'Building {_n} Ken Burns clips...')

for _i, _sc in enumerate(SCENE_DATA):
    _img=_sc['image']; _audio=_sc['audio']; _dur=_sc['duration']
    _clip=f'{CLIP_DIR}/clip_{_i:04d}.mp4'; _clips.append(_clip)
    if os.path.exists(_clip): print(f'  [{_i+1}/{_n}] cached'); continue

    _nf=max(int(_dur*30),2); _p=_i%5
    if   _p==0: _zp=f"z='min(zoom+0.0004,1.16)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"
    elif _p==1: _zp=f"z='min(zoom+0.0004,1.16)':x='0':y='0':d={_nf}"
    elif _p==2: _zp=f"z='min(zoom+0.0004,1.16)':x='iw-iw/zoom':y='ih-ih/zoom':d={_nf}"
    elif _p==3: _zp=f"z='if(lte(zoom,1.0),1.16,zoom-0.0004)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"
    else:       _zp=f"z='min(zoom+0.0004,1.16)':x='iw-iw/zoom':y='0':d={_nf}"

    _r=subprocess.run([
        'ffmpeg','-y','-loop','1','-i',_img,'-i',_audio,
        '-filter_complex',f'[0:v]scale=1280:720,zoompan={_zp}:s=1280x720:fps=30[v]',
        '-map','[v]','-map','1:a',
        '-c:v','libx264','-crf','17','-preset','fast',
        '-c:a','aac','-b:a','192k','-shortest','-pix_fmt','yuv420p',_clip,
    ], capture_output=True, text=True)
    if _r.returncode!=0:
        print(f'  Clip {_i} error:\\n{_r.stderr[-400:]}')
        raise RuntimeError(f'Clip {_i} failed')
    print(f'  [{_i+1}/{_n}] {_dur:.1f}s  clip_{_i:04d}.mp4')

import json as _jj
with open(f'{WORK_DIR}/clip_paths.json','w') as _f: _jj.dump(_clips,_f)
print(f'\\n{_n} clips done. Run Cell 6.')
""")

# ── CELL 7: Karplus-Strong Music ──────────────────────────────────────────────

CELL_MUSIC = code("""\
# ── CELL 6: Karplus-Strong harp/guitar — C-G-Am-F at 112 BPM ─────────────────
# Karplus-Strong string synthesis: sounds like guitar/harp (no GPU, no samples)
import numpy as np, wave, os, subprocess, json

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_total_dur  = sum(s['duration'] for s in SCENE_DATA)
_music_dur  = _total_dur + 10.0
SR          = 44100
BPM         = 112.0
BEAT        = 60.0 / BPM        # 0.536 s
LOOP_BARS   = 8
LOOP_DUR    = LOOP_BARS * 4 * BEAT
LOOP_SAMP   = int(SR * LOOP_DUR)

# C-G-Am-F × 2 = 8 bars
CHORDS = [
    [261.63, 329.63, 392.00],   # C major
    [196.00, 246.94, 293.66],   # G major
    [220.00, 261.63, 329.63],   # A minor
    [174.61, 220.00, 261.63],   # F major
] * 2

np.random.seed(42)   # reproducible sound

def _ks(freq, dur_sec, damping=0.9965):
    '''Karplus-Strong plucked string — guitar/harp timbre.'''
    n      = int(SR * dur_sec)
    period = max(int(round(SR / freq)), 1)
    buf    = np.random.uniform(-0.5, 0.5, period).astype(np.float32)
    out    = np.zeros(n, dtype=np.float32)
    for i in range(n):
        idx       = i % period
        nxt       = (i + 1) % period
        out[i]    = buf[idx]
        buf[idx]  = damping * 0.5 * (buf[idx] + buf[nxt])
    return out

print(f'Generating {LOOP_DUR:.1f}s Karplus-Strong loop × {_music_dur/LOOP_DUR:.1f}...')
print('(KS runs a Python loop — takes ~10-20 s for an 8-bar loop)')

mix       = np.zeros(LOOP_SAMP, dtype=np.float32)
note_dur  = BEAT * 0.88

for bar_idx, chord in enumerate(CHORDS):
    root, third, fifth = chord
    # Arpeggio: root, third, fifth, root-octave
    for beat_idx,(freq,vol) in enumerate([(root,0.34),(third,0.27),(fifth,0.24),(root*2,0.19)]):
        samp_st = int((bar_idx*4+beat_idx)*BEAT*SR)
        note    = _ks(freq, note_dur)*vol
        end     = min(samp_st+len(note), LOOP_SAMP)
        mix[samp_st:end] += note[:end-samp_st]
    # Bass root on beat 1 (one octave lower, longer decay)
    bass = _ks(root/2, BEAT*1.6, damping=0.999)*0.22
    bst  = int(bar_idx*4*BEAT*SR)
    end  = min(bst+len(bass), LOOP_SAMP)
    mix[bst:end] += bass[:end-bst]

print('KS done.')

mix /= (np.max(np.abs(mix))+1e-9); mix *= 0.62
_fi=int(SR*1.5); _fo=int(SR*2.0)
mix[:_fi]  *= np.linspace(0,1,_fi,dtype=np.float32)
mix[-_fo:] *= np.linspace(1,0,_fo,dtype=np.float32)

_loop_wav = f'{WORK_DIR}/music_loop.wav'
MUSIC_MP3  = f'{WORK_DIR}/background_music.mp3'
_pcm=(mix*32767).clip(-32768,32767).astype(np.int16)
with wave.open(_loop_wav,'w') as _wf:
    _wf.setnchannels(1); _wf.setsampwidth(2); _wf.setframerate(SR)
    _wf.writeframes(_pcm.tobytes())

_fade_st = max(0, _music_dur-6.0)
subprocess.run([
    'ffmpeg','-y','-stream_loop','-1','-i',_loop_wav,
    '-t',str(_music_dur),
    '-af',f'afade=t=in:st=0:d=2,afade=t=out:st={_fade_st:.1f}:d=6',
    '-q:a','4', MUSIC_MP3,
], capture_output=True, check=True)
os.remove(_loop_wav)

print(f'Music: C-G-Am-F KS harp/guitar  {_music_dur:.0f}s  ({MUSIC_MP3})')
print('Run Cell 7.')
""")

# ── CELL 8: Assemble ──────────────────────────────────────────────────────────

CELL_ASSEMBLE = code("""\
# ── CELL 7: Assemble all clips ────────────────────────────────────────────────
import json, os, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'CLIP_DIR'  not in dir(): CLIP_DIR  = f'{WORK_DIR}/clips'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_cpf=f'{WORK_DIR}/clip_paths.json'
if os.path.exists(_cpf):
    with open(_cpf) as _f: _clips=json.load(_f)
else:
    _clips=sorted([f'{CLIP_DIR}/{fn}' for fn in os.listdir(CLIP_DIR)
                   if fn.startswith('clip_') and fn.endswith('.mp4')])

_list=f'{WORK_DIR}/clip_list.txt'
with open(_list,'w') as _f:
    for _c in _clips: _f.write(f"file '{_c}'\\n")

RAW_VIDEO=f'{WORK_DIR}/video_raw.mp4'
print(f'Concatenating {len(_clips)} clips...')
_r=subprocess.run(['ffmpeg','-y','-f','concat','-safe','0',
                   '-i',_list,'-c','copy',RAW_VIDEO],
                  capture_output=True, text=True)
if _r.returncode!=0:
    print(_r.stderr[-600:]); raise RuntimeError('Concat failed')

_mb=os.path.getsize(RAW_VIDEO)/1_048_576
_total=sum(s['duration'] for s in SCENE_DATA)
print(f'Raw video: {_total:.0f}s  {_mb:.1f} MB')
print('Run Cell 8.')
""")

# ── CELL 9: ASS Captions ──────────────────────────────────────────────────────

CELL_CAPTIONS = code("""\
# ── CELL 8: Yellow ASS captions — word-level, burned onto full-frame doodle ───
# NOTE: PIL images have NO caption band. These ASS captions ARE the only text.
import json, os, re, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'RAW_VIDEO' not in dir(): RAW_VIDEO = f'{WORK_DIR}/video_raw.mp4'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

def _parse_vtt(vtt_path, offset=0.0):
    if not os.path.exists(vtt_path): return []
    with open(vtt_path, encoding='utf-8') as f: content=f.read()
    entries=[]
    for block in re.split(r'\\n\\n+', content.strip()):
        lines=block.strip().split('\\n')
        tline=next((l for l in lines if '-->' in l), None)
        if not tline: continue
        m=re.match(r'(\\d+):(\\d+):(\\d+\\.\\d+)\\s+-->\\s+(\\d+):(\\d+):(\\d+\\.\\d+)',tline)
        if not m: continue
        s=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3))+offset
        e=int(m.group(4))*3600+int(m.group(5))*60+float(m.group(6))+offset
        txt=' '.join(l for l in lines if l and '-->' not in l
                     and not l.startswith('WEBVTT') and not l.strip().isdigit()).strip()
        if txt: entries.append((s,e,txt))
    return entries

def _ass_ts(sec):
    h=int(sec//3600);m=int((sec%3600)//60);s=int(sec%60);cs=int((sec%1)*100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'
def _srt_ts(sec):
    h=int(sec//3600);m=int((sec%3600)//60);s=int(sec%60);ms=int((sec%1)*1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

_all=[]; _offset=0.0
for _sc in SCENE_DATA:
    _entries=_parse_vtt(_sc.get('vtt',''),_offset)
    if _entries: _all.extend(_entries)
    else: _all.append((_offset,_offset+_sc['duration'],_sc['text']))
    _offset+=_sc['duration']

# ASS: yellow (&H0000FFFF), black outline 2.5px, bottom-center, 30px margin
ASS_HEADER='''[Script Info]
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1280
PlayResY: 720
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,24,&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2.5,0,2,10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''

_ass_path=f'{WORK_DIR}/captions.ass'
_srt_path=f'{WORK_DIR}/captions.srt'

with open(_ass_path,'w',encoding='utf-8') as f:
    f.write(ASS_HEADER)
    for s,e,txt in _all:
        f.write(f"Dialogue: 0,{_ass_ts(s)},{_ass_ts(e)},Default,,0,0,0,,{txt.replace('{','').replace('}','')}\\n")
with open(_srt_path,'w',encoding='utf-8') as f:
    for idx,(s,e,txt) in enumerate(_all,1):
        f.write(f'{idx}\\n{_srt_ts(s)} --> {_srt_ts(e)}\\n{txt}\\n\\n')

print(f'ASS captions: {len(_all)} entries')

_ass_esc=_ass_path.replace('\\\\','/').replace(':','\\\\:')
CAPTIONED_VIDEO=f'{WORK_DIR}/video_captioned.mp4'

_r=subprocess.run([
    'ffmpeg','-y','-i',RAW_VIDEO,
    '-vf',f"ass='{_ass_esc}'",
    '-c:a','copy','-c:v','libx264','-crf','17','-preset','fast',
    CAPTIONED_VIDEO,
], capture_output=True, text=True)

if _r.returncode!=0:
    print('ASS burn failed — trying SRT subtitles filter...')
    _srt_esc=_srt_path.replace('\\\\','/').replace(':','\\\\:')
    _style="FontName=Arial,FontSize=22,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2.5,Bold=1,Alignment=2,MarginV=30"
    _r2=subprocess.run([
        'ffmpeg','-y','-i',RAW_VIDEO,
        '-vf',f"subtitles='{_srt_esc}':force_style='{_style}'",
        '-c:a','copy','-c:v','libx264','-crf','17','-preset','fast',
        CAPTIONED_VIDEO,
    ], capture_output=True, text=True)
    if _r2.returncode!=0:
        print('Subtitles filter also failed — copying without burn.')
        print('captions.srt still available for YouTube upload.')
        import shutil; shutil.copy2(RAW_VIDEO,CAPTIONED_VIDEO)
    else: print('SRT fallback OK.')
else:
    print(f'Captions burned: yellow text, 2.5px black outline')

print('Run Cell 9.')
""")

# ── CELL 10: Mix Audio ────────────────────────────────────────────────────────

CELL_MIX = code("""\
# ── CELL 9: Mix music + loudnorm voiceover + master fade in/out ───────────────
import json, os, re, subprocess

if 'WORK_DIR'    not in dir(): WORK_DIR    = '/content/unlearned'
if 'MUSIC_VOL'   not in dir(): MUSIC_VOL   = 0.15
if 'CAPTIONED_VIDEO' not in dir(): CAPTIONED_VIDEO=f'{WORK_DIR}/video_captioned.mp4'
if 'MUSIC_MP3'   not in dir(): MUSIC_MP3   = f'{WORK_DIR}/background_music.mp3'
if not os.path.exists(CAPTIONED_VIDEO): CAPTIONED_VIDEO=f'{WORK_DIR}/video_raw.mp4'
if 'EPISODE_TITLE' not in dir():
    _tp=f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE=open(_tp).read().strip() if os.path.exists(_tp) else 'Episode'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA=json.load(_f)

_total=sum(s['duration'] for s in SCENE_DATA)
_fo_st=max(0,_total-2.5)   # fade-out start
_safe=re.sub(r'[^\\w\\s-]+','',EPISODE_TITLE).strip().replace(' ','_')
FINAL_VIDEO=f'{WORK_DIR}/UNLEARNED_{_safe}.mp4'

print(f'Mixing: voiceover loudnorm (-16 LUFS) + music ({int(MUSIC_VOL*100)}%)')
print(f'Video/audio fade: in 0.8s white  |  out 2.5s white')

# loudnorm on voiceover, amix with music, then master audio fade
_r=subprocess.run([
    'ffmpeg','-y',
    '-i',CAPTIONED_VIDEO,'-i',MUSIC_MP3,
    '-filter_complex',
        f'[0:a]loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[vo_n];'
        f'[1:a]volume={MUSIC_VOL}[mu];'
        f'[vo_n][mu]amix=inputs=2:duration=first[a_mix];'
        f'[a_mix]afade=t=in:st=0:d=0.8,afade=t=out:st={_fo_st:.1f}:d=2.5[aout]',
    '-map','0:v','-map','[aout]',
    '-vf',f'fade=t=in:st=0:d=0.8:color=white,fade=t=out:st={_fo_st:.1f}:d=2.5:color=white',
    '-c:v','libx264','-crf','17','-preset','fast',
    '-c:a','aac','-b:a','192k','-shortest',
    FINAL_VIDEO,
], capture_output=True, text=True)

if _r.returncode!=0:
    print('Full mix failed — trying without video fade...')
    _r2=subprocess.run([
        'ffmpeg','-y','-i',CAPTIONED_VIDEO,'-i',MUSIC_MP3,
        '-filter_complex',
            f'[0:a]loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[vo_n];'
            f'[1:a]volume={MUSIC_VOL}[mu];'
            f'[vo_n][mu]amix=inputs=2:duration=first[aout]',
        '-map','0:v','-map','[aout]',
        '-c:v','copy','-c:a','aac','-b:a','192k','-shortest',
        FINAL_VIDEO,
    ], capture_output=True, text=True)
    if _r2.returncode!=0: print(_r2.stderr[-600:]); raise RuntimeError('Mix failed')

_mb=os.path.getsize(FINAL_VIDEO)/1_048_576
print(f'\\nFinal video : {FINAL_VIDEO}')
print(f'Size        : {_mb:.1f} MB')
print('Run Cell 10 to download.')
""")

# ── CELL 11: Download ─────────────────────────────────────────────────────────

CELL_DOWNLOAD = code("""\
# ── CELL 10: Download ─────────────────────────────────────────────────────────
import os, re, json
from google.colab import files as _gcf

if 'WORK_DIR' not in dir(): WORK_DIR='/content/unlearned'
if 'FINAL_VIDEO' not in dir():
    _tp=f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE=open(_tp).read().strip() if os.path.exists(_tp) else 'Episode'
    _safe=re.sub(r'[^\\w\\s-]+','',EPISODE_TITLE).strip().replace(' ','_')
    FINAL_VIDEO=f'{WORK_DIR}/UNLEARNED_{_safe}.mp4'

if not os.path.exists(FINAL_VIDEO):
    raise RuntimeError(f'Video not found: {FINAL_VIDEO} — Run Cell 9 first.')

_mb=os.path.getsize(FINAL_VIDEO)/1_048_576
print(f'Downloading: {os.path.basename(FINAL_VIDEO)}  ({_mb:.1f} MB)')
_gcf.download(FINAL_VIDEO)

for _cf in [f'{WORK_DIR}/captions.srt', f'{WORK_DIR}/captions.ass']:
    if os.path.exists(_cf):
        print(f'Downloading: {os.path.basename(_cf)}')
        _gcf.download(_cf)

if 'SCENE_DATA' not in dir():
    _jp=f'{WORK_DIR}/scene_data.json'
    if os.path.exists(_jp):
        with open(_jp) as _f: SCENE_DATA=json.load(_f)

if 'SCENE_DATA' in dir():
    _total=sum(s['duration'] for s in SCENE_DATA)
    _ep=EPISODE_TITLE if 'EPISODE_TITLE' in dir() else '—'
    print(f'\\nEpisode  : {_ep}')
    print(f'Duration : {_total:.0f}s  ({_total/60:.1f} min)')
    print(f'Scenes   : {len(SCENE_DATA)}')
    print()
    print('YouTube upload tips:')
    print('  • Upload UNLEARNED_*.mp4 as the video')
    print('  • Upload captions.srt in Studio → Subtitles for word-level captions')
    print('  • captions.ass is the burned-in version (already in the video)')

print('\\nDone!')
""")

# ── Notebook ───────────────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE, CELL_INSTALL, CELL_SETUP, CELL_VOICE,
    CELL_DOODLE, CELL_MOTION, CELL_MUSIC, CELL_ASSEMBLE,
    CELL_CAPTIONS, CELL_MIX, CELL_DOWNLOAD,
]

NOTEBOOK = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {
        "colab":     {"provenance": [], "gpuType": "None"},
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
