"""
Build the Unlearned Video Generator Colab notebook — v5 (Perfect Edition).
Run: python build_notebook.py
Output: unlearned_generator.ipynb

V5 vs V4:
  - Chunk-based Karplus-Strong (100x faster — period-by-period numpy, not sample-by-sample)
  - 16-bar music loop: C-G-Am-F (A) + Am-F-C-G (B) with ascending/descending melody line
  - Per-clip white fade transitions (0.15 s) — clean scene cuts without xfade complexity
  - 7 Ken Burns directions (was 5)
  - 6 soft background palettes cycling per scene (ivory, mint, lavender, peach, ice-blue, white)
  - 12 frame types (was 8): + timeline, quote_card, comparison, stat_bar
  - Scoring-based frame type detection — replaces brittle if/elif chain
  - VTT word grouping: 4 words per caption entry for comfortable reading
  - ASS subtitle font size 28 (was 24) for mobile readability
  - Figure accessories: graduation cap (idea/diagram), top hat (history)
  - Figure shoes: small ellipses at feet for polish
  - Scene props: book, screen, money-bag, heart based on keywords
  - Scene preview: first 3 doodle images shown inline after cell 4
  - Expanded keyword lists for psychology + history channel content
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
# UNLEARNED — Automated Video Generator  v5 ✦ Perfect Edition
### Psychology · Ancient History · Behavioral Science

| Cell | What it does |
|------|-------------|
| 1 | Install packages |
| 2 | Setup |
| 3 | Upload `.txt` script → voiceover + word-timing VTT |
| 4 | Doodle images — 12 frame types, 6 BG palettes, props, accessories |
| 5 | Ken Burns motion clips with per-clip white-fade transitions |
| 6 | Background music — chunk-KS harp, 16-bar loop + melody line |
| 7 | Assemble clips |
| 8 | Burn yellow ASS captions (4-word phrase sync, font 28) |
| 9 | Mix audio + master fade in/out + loudnorm |
| 10 | Download final MP4 + captions.srt |

**v5 highlights:** chunk-based KS music is ~100× faster · 12 scene types · 6 palette BGs ·
props (book / screen / money / heart) · graduation-cap & hat accessories · smooth white scene cuts
""")

# ── CELL 2: Install ────────────────────────────────────────────────────────────

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
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', _pkg], capture_output=True)
    print(f'  {_pkg}: ok')

_lf = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'
print(f'  Liberation Bold: {"found" if os.path.exists(_lf) else "missing — fallback active"}')
print('\\nAll packages ready. Run Cell 2.')
""")

# ── CELL 3: Setup ──────────────────────────────────────────────────────────────

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
MUSIC_VOL    = 0.14   # background music level (14 %)

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
        ['ffprobe','-v','quiet','-print_format','json','-show_format', path],
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
    _suf = '...' if len(_text) > 55 else ''
    print(f'  [{_i+1}/{len(_scenes)}] {_d:.1f}s  {_text[:55]}{_suf}')

with open(f'{WORK_DIR}/scene_data.json','w') as _f:
    json.dump(SCENE_DATA, _f, indent=2, ensure_ascii=False)
_total = sum(s['duration'] for s in SCENE_DATA)
print(f'\\nTotal: {_total:.0f}s ({_total/60:.1f} min) | {len(SCENE_DATA)} scenes')
print('Voiceover done. Run Cell 4.')
""")

# ── CELL 5: PIL Doodle Images (v5) ────────────────────────────────────────────

CELL_DOODLE = code("""\
# ── CELL 4: Doodle Images v5 — 12 frame types, 6 BG palettes, props ──────────
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
DZ_TOP = 30          # top of drawing zone
DZ_BOT = 548         # bottom of drawing zone (ASS captions sit below ~560)
DZ_MID = (DZ_TOP + DZ_BOT) // 2   # = 289 — vertical centre

# ── Palette definitions ────────────────────────────────────────────────────────
C = {
    'orange': (245,130, 13), 'blue':  ( 45, 95,191), 'green': ( 58,158, 58),
    'yellow': (245,197, 24), 'red':   (217, 64, 64), 'brown': (139, 94, 60),
    'sky':    (110,181,232), 'tan':   (196,150, 90), 'white': (255,255,255),
    'black':  (  0,  0,  0), 'skin':  (255,210,165), 'gray':  (220,220,220),
    'dgray':  (150,150,150), 'lblue': (200,220,255), 'pink':  (255,182,193),
    'purple': (128, 80,200), 'teal':  ( 32,178,170), 'gold':  (212,175, 55),
}
# 6 soft scene backgrounds (cycle by scene index when no keyword match)
SOFT_BG = [
    (255,255,255),   # 0 classic white
    (255,252,242),   # 1 warm ivory
    (242,255,248),   # 2 mint
    (248,244,255),   # 3 lavender
    (255,246,238),   # 4 peach
    (238,248,255),   # 5 ice blue
]

# ── Font helper ────────────────────────────────────────────────────────────────
def _font(sz):
    for p in ['/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
              '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf']:
        try: return ImageFont.truetype(p, sz)
        except: pass
    return ImageFont.load_default()

def _wrap(text, draw, font, max_w):
    words = text.split(); lines, buf = [], []
    for w in words:
        test = ' '.join(buf+[w])
        bb = draw.textbbox((0,0), test, font=font)
        if bb[2]-bb[0] <= max_w: buf.append(w)
        else:
            if buf: lines.append(' '.join(buf))
            buf = [w]
    if buf: lines.append(' '.join(buf))
    return lines or ['']

_RNG = random.Random()   # seeded per scene for deterministic wobble

# ── BÉZIER PRIMITIVES ─────────────────────────────────────────────────────────
def _sl(draw, x1, y1, x2, y2, fill, width=3, wob=3):
    x1,y1,x2,y2 = int(x1),int(y1),int(x2),int(y2)
    dx,dy = x2-x1, y2-y1
    dist  = max(int((dx*dx+dy*dy)**0.5), 1)
    if dist < 12:
        draw.line([(x1,y1),(x2,y2)], fill=fill, width=width); return
    px,py = -dy/dist, dx/dist
    bend  = _RNG.randint(-wob, wob) * max(dist//16, 1)
    mx    = (x1+x2)//2 + int(px*bend)
    my    = (y1+y2)//2 + int(py*bend)
    steps = max(dist//5, 10)
    pts   = []
    for k in range(steps+1):
        t = k/steps
        pts.append((int((1-t)**2*x1+2*(1-t)*t*mx+t**2*x2),
                    int((1-t)**2*y1+2*(1-t)*t*my+t**2*y2)))
    for k in range(len(pts)-1):
        draw.line([pts[k],pts[k+1]], fill=fill, width=width)

def _se(draw, cx, cy, rx, ry, outline, fill=None, width=3, wob=2):
    cx,cy,rx,ry = int(cx),int(cy),max(int(rx),3),max(int(ry),3)
    if fill: draw.ellipse([cx-rx,cy-ry,cx+rx,cy+ry], fill=fill)
    n   = max(int((rx+ry)*1.7), 30)
    pts = [(int(cx+rx*math.cos(2*math.pi*k/n))+_RNG.randint(-wob,wob),
            int(cy+ry*math.sin(2*math.pi*k/n))+_RNG.randint(-wob,wob)) for k in range(n+1)]
    for k in range(len(pts)-1):
        draw.line([pts[k],pts[k+1]], fill=outline, width=width)

def _sarc(draw, cx, cy, rx, ry, a0, a1, fill, width=3, wob=2):
    cx,cy,rx,ry = int(cx),int(cy),max(int(rx),3),max(int(ry),3)
    r0,r1 = math.radians(a0), math.radians(a1)
    if r1 <= r0: r1 += 2*math.pi
    n   = max(int((r1-r0)*(rx+ry)/3.5), 8)
    pts = [(int(cx+rx*math.cos(r0+(r1-r0)*k/n))+_RNG.randint(-wob,wob),
            int(cy+ry*math.sin(r0+(r1-r0)*k/n))+_RNG.randint(-wob,wob)) for k in range(n+1)]
    for k in range(len(pts)-1):
        draw.line([pts[k],pts[k+1]], fill=fill, width=width)

def _sp(draw, pts, fill=None, outline=None, width=3, wob=2):
    ipts = [(int(x),int(y)) for x,y in pts]
    if fill:    draw.polygon(ipts, fill=fill)
    if outline:
        for k in range(len(ipts)):
            _sl(draw, ipts[k][0],ipts[k][1], ipts[(k+1)%len(ipts)][0],ipts[(k+1)%len(ipts)][1],
                outline, width, wob)

# ── BACKGROUND ────────────────────────────────────────────────────────────────
def _fill_bg(draw, text, idx=0):
    w = text.lower()
    if any(x in w for x in ['ancient','prehistoric','cave','stone age','neanderthal',
                              'fossil','egypt','rome','mesopotamia','babylon','empire',
                              'tribal','civilization','dynasty','pharaoh','greek','roman']):
        draw.rectangle([0,0,W,H], fill=C['tan'])
        for y in range(0, H, 30):
            draw.line([0,y,W,y], fill=(175,128,68), width=1)
        return 'tan'
    if any(x in w for x in ['ocean','sea','underwater','marine','fish','shark','whale']):
        draw.rectangle([0,0,W,H], fill=(30,90,180))
        for y in range(40,H,55):
            for x in range(0,W,90):
                draw.arc([x,y-9,x+65,y+9], 0,180, fill=(60,120,210), width=2)
        return 'blue'
    if any(x in w for x in ['nature','forest','tree','evolv','savanna','jungle','grass','wild']):
        draw.rectangle([0,0,W,H], fill=C['sky'])
        draw.rectangle([0,int(H*0.64),W,H], fill=C['green'])
        for gx in range(25,W,42):
            gy = int(H*0.64)
            for off,ht in [(-5,10),(0,14),(5,10)]:
                draw.line([gx,gy,gx+off,gy-ht], fill=(35,120,35), width=2)
        _se(draw, W-90,70, 36,36, C['yellow'],C['yellow'],3,1)
        for ang in range(0,360,40):
            rad = math.radians(ang)
            draw.line([int(W-90+(41)*math.cos(rad)),int(70+(41)*math.sin(rad)),
                       int(W-90+(54)*math.cos(rad)),int(70+(54)*math.sin(rad))],
                      fill=C['yellow'],width=3)
        return 'outdoor'
    if any(x in w for x in ['fire','night','ritual','torch','flame','dark','shadow']):
        draw.rectangle([0,0,W,H], fill=(200,90,20))
        for m in range(0,55,8):
            draw.rectangle([m,m,W-m,H-m], outline=tuple(max(c-m*4,0) for c in (200,90,20)), width=1)
        return 'orange'
    if any(x in w for x in ['science','lab','dna','neuron','atom','chemical','molecule','research']):
        draw.rectangle([0,0,W,H], fill=(24,44,100))
        for gx in range(0,W,65): draw.line([gx,0,gx,H], fill=(40,60,130),width=1)
        for gy in range(0,H,65): draw.line([0,gy,W,gy], fill=(40,60,130),width=1)
        return 'dark_blue'
    # Default: soft palette, cycling per scene
    bg = SOFT_BG[idx % len(SOFT_BG)]
    draw.rectangle([0,0,W,H], fill=bg)
    return 'soft'

# ── FRAME TYPE — scoring system (12 types) ────────────────────────────────────
def _frame_type(text, idx=0):
    w  = text.lower()
    sc = {k:0 for k in ['concept_text','evolution','villain','reaction','globe',
                          'diagram','idea','timeline','quote_card','comparison',
                          'stat_bar','scene']}
    # Number facts
    if re.search(r'\\b\\d[\\d,]*\\s*(million|thousand|billion|year|day|hour|minute|second)', w):
        sc['concept_text'] += 4
    # Percentages → bar chart
    if re.search(r'\\b\\d+\\s*(%|percent)\\b', w): sc['stat_bar'] += 4
    if any(x in w for x in ['survey','study found','research shows','majority','statistics',
                              'according to a study','scientists found','data shows']):
        sc['stat_bar'] += 2
    # Evolution / transformation
    for kw in ['evolv','transform','stages','progress','develop','became','sequence',
               'steps','million year','from ape','over time','gradually','generation',
               'mutation','adaptation','selection','species changed']:
        if kw in w: sc['evolution'] += 2
    # Psychology villain (brain)
    for kw in ['brain','stress','anxiety','dopamine','cortisol','ego','addiction','trauma',
               'amygdala','serotonin','cortex','priming','placebo','bias','neuron',
               'cognitive','phobia','depression','paranoia','subconscious','unconscious',
               'conformity','groupthink','herd','social proof','anchoring','dunning',
               'impostor','dissonance','attention','loss aversion','sunk cost',
               'negativity bias','optimism bias','recency bias','availability']:
        if kw in w: sc['villain'] += 2
    # Timeline / history
    if re.search(r'\\b(\\d{2,4})\\s*(bc|ad|ce|bce|century|decade)\\b', w): sc['timeline'] += 4
    for kw in ['history','century','decade','era','period','civilization','empire',
               'dynasty','revolution','ancient world','timeline','years ago',
               'discovered in','invented in','founded in','born in']:
        if kw in w: sc['timeline'] += 2
    # Quote card
    if '"' in text or '\\u201c' in text or '\\u201d' in text: sc['quote_card'] += 5
    for kw in ['said','stated','according to','wrote','believed','once said',
               'declared','claimed','argued','noted','observed']:
        if kw in w: sc['quote_card'] += 2
    # Comparison
    for kw in ['versus','vs.','compared to','difference between','unlike','however',
               'on the other hand','whereas','instead of','rather than','contrast',
               'while the other','one group','another group','group a','group b']:
        if kw in w: sc['comparison'] += 2
    # Reaction / wonder
    for kw in ['why','wonder','confus','strange','but wait','hmm','believe it',
               'how is that','did you know','turns out','surprisingly','hard to believe',
               'would you believe','here is the thing','actually','in fact']:
        if kw in w: sc['reaction'] += 2
    # Globe
    for kw in ['world','globe','earth','everywhere','planet','global','species',
               'continent','across','universal','worldwide','humanity','entire planet']:
        if kw in w: sc['globe'] += 2
    # Diagram / definition
    for kw in ['called','known as','labeled','type of','named','kind of',
               'defined as','refers to','this is called','we call it','term for']:
        if kw in w: sc['diagram'] += 2
    # Idea / discovery
    for kw in ['idea','discover','realiz','invent','insight','aha','eureka',
               'thought of','came up with','figured out','breakthrough','solution',
               'innovate','concept','first time','pioneered']:
        if kw in w: sc['idea'] += 2
    sc['scene'] = 1   # baseline
    return max(sc, key=sc.get)

def _expr(text):
    w = text.lower()
    if any(x in w for x in ['happy','joy','excit','celebrat','laugh','smile','success',
                              'win','achieve','triumph','positive','proud','glad']):
        return 'happy'
    if any(x in w for x in ['sad','cry','depress','grief','hurt','loss','mourn','lonely']):
        return 'sad'
    if any(x in w for x in ['angry','rage','frustrat','mad','furious','rage','outrage']):
        return 'angry'
    if any(x in w for x in ['fear','scared','panic','anxious','stress','terror','dread',
                              'phobia','threat','danger','alarm','horror']):
        return 'scared'
    return 'neutral'

# ── STICK FIGURE ──────────────────────────────────────────────────────────────
def _figure(draw, cx, cy, size=120, expr='neutral', col=None, accessory=None):
    col  = col or C['black']
    hr   = max(int(size*0.24), 14)
    lw   = max(int(size*0.05), 3)
    ew   = max(int(hr*0.17), 3)
    exo  = int(hr*0.37)
    eyo  = int(hr*0.18)
    ms   = int(hr*0.45)
    mby  = int(hr*0.30)
    bow  = int(hr*0.54)
    broy = cy - eyo - int(hr*0.22)

    _se(draw, cx, cy, hr, hr, col, C['skin'], lw, 2)
    draw.ellipse([cx-exo-ew, cy-eyo-ew, cx-exo+ew, cy-eyo+ew], fill=col)
    draw.ellipse([cx+exo-ew, cy-eyo-ew, cx+exo+ew, cy-eyo+ew], fill=col)

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
                      int(cx+(hr+20)*math.cos(_rad)),int(cy+(hr+20)*math.sin(_rad)), col,2,0)
    else:
        _sl(draw, cx-bow+5,broy, cx-exo+2,broy, col,lw,1)
        _sl(draw, cx+exo-2,broy, cx+bow-5,broy, col,lw,1)
        _sl(draw, cx-ms//2,cy+mby, cx+ms//2,cy+mby, col,lw,1)

    # Body
    neck_y = cy+hr; body_b = cy+hr+int(size*0.56)
    _sl(draw, cx,neck_y, cx,body_b, col,lw,2)

    # Arms
    arm_y = cy+hr+int(size*0.22)
    if expr == 'happy':
        for _sd in [-1,1]:
            _sl(draw, cx,arm_y, cx+_sd*int(size*0.40),arm_y-int(size*0.32), col,lw,2)
    elif expr == 'scared':
        for _sd in [-1,1]:
            _sl(draw, cx,arm_y, cx+_sd*int(size*0.28),arm_y-int(size*0.12), col,lw,2)
    elif expr == 'angry':
        for _sd in [-1,1]:
            _sl(draw, cx,arm_y, cx+_sd*int(size*0.38),arm_y+int(size*0.05), col,lw,2)
    else:
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
        # Shoes
        _sw2 = int(size*0.12)
        draw.ellipse([_fx-_sw2, _fy-4, _fx+_sw2+6, _fy+int(size*0.05)], fill=C['black'])

    # Ground shadow
    _sw = int(size*0.38); _sh2 = max(int(size*0.05),3)
    _sby = body_b+int(size*0.44)+_sh2+6
    draw.ellipse([cx-_sw,_sby-_sh2,cx+_sw,_sby+_sh2], fill=C['dgray'])

    # Accessories
    brim_y = cy-hr-4
    if accessory == 'graduation':
        draw.rectangle([cx-hr-8, brim_y-3, cx+hr+8, brim_y+4], fill=C['black'])
        draw.rectangle([cx-hr+3, brim_y-20, cx+hr-3, brim_y], fill=C['black'])
        _sl(draw, cx+hr+4, brim_y+2, cx+hr+14, brim_y+18, C['yellow'],3,0)
        draw.ellipse([cx+hr+10,brim_y+14,cx+hr+20,brim_y+24], fill=C['yellow'])
    elif accessory == 'tophat':
        draw.rectangle([cx-hr-10, brim_y-2, cx+hr+10, brim_y+5], fill=C['black'])
        draw.rectangle([cx-hr+5,  brim_y-28, cx+hr-5,  brim_y], fill=C['black'])
    elif accessory == 'halo':
        _se(draw, cx, cy-hr-14, int(hr*0.85), 8, C['gold'], None, 3, 1)

    return body_b + int(size*0.44)

# ── PROPS ─────────────────────────────────────────────────────────────────────
def _prop_book(draw, x, y, s=46):
    _sp(draw,[(x-s,y-s//2),(x,y-s//2+5),(x,y+s//2+5),(x-s,y+s//2)],
        fill=C['brown'],outline=C['black'],width=2,wob=1)
    _sp(draw,[(x,y-s//2+5),(x+s,y-s//2),(x+s,y+s//2),(x,y+s//2+5)],
        fill=C['lblue'],outline=C['black'],width=2,wob=1)
    _sl(draw,x,y-s//2+5,x,y+s//2+5,C['black'],3,1)
    for _ly in range(y-s//4, y+s//2-8, 10):
        _sl(draw,x+4,_ly,x+s-4,_ly,C['blue'],1,0)

def _prop_screen(draw, x, y, s=62):
    draw.rectangle([x-s,y-s//2,x+s,y+s//3], fill=C['black'])
    draw.rectangle([x-s+5,y-s//2+5,x+s-5,y+s//3-5], fill=C['lblue'])
    _sl(draw,x,y+s//3,x,y+s//2,C['black'],4,1)
    _sl(draw,x-18,y+s//2,x+18,y+s//2,C['black'],4,1)
    # Screen text lines
    for _ly in range(y-s//2+14, y+s//3-10, 12):
        _sl(draw,x-s+12,_ly,x+s-12,_ly,C['blue'],2,0)

def _prop_heart(draw, x, y, s=30):
    hs = s//2
    draw.ellipse([x-s,y-hs-4,x-4,y+hs-4], fill=C['red'])
    draw.ellipse([x+4,y-hs-4,x+s,y+hs-4], fill=C['red'])
    draw.polygon([(x-s,y+hs//2),(x,y+s+4),(x+s,y+hs//2)], fill=C['red'])

def _prop_money(draw, x, y, s=36):
    _se(draw,x,y,s,int(s*0.8),C['black'],C['green'],3,2)
    _sl(draw,x,y-s,x,y-s-14,C['black'],3,1)
    _sl(draw,x-s//3,y-s-10,x+s//3,y-s-4,C['black'],3,1)
    f=_font(26); bb=draw.textbbox((0,0),'$',font=f)
    draw.text((x-(bb[2]-bb[0])//2,y-(bb[3]-bb[1])//2-3),'$',fill=C['yellow'],font=f)

# ── THOUGHT BUBBLE ────────────────────────────────────────────────────────────
def _bubble(draw, cx, cy, hr, snippet):
    bx=cx+hr+22; by=cy-hr-95
    bw=min(290,W-bx-22); bh=84
    if bx+bw > W-18: bx=cx-bw-hr-22
    for shp in [(bx,by,bx+bw,by+bh),(bx-16,by+12,bx+44,by+bh+20),
                (bx+bw-44,by+12,bx+bw+16,by+bh+20),(bx+bw//4,by-16,bx+3*bw//4,by+24)]:
        _se(draw,(shp[0]+shp[2])//2,(shp[1]+shp[3])//2,
            (shp[2]-shp[0])//2,(shp[3]-shp[1])//2,C['black'],C['white'],3,2)
    f=_font(22); txt=(snippet[:24]+'...').upper() if len(snippet)>24 else snippet.upper()
    bb=draw.textbbox((0,0),txt,font=f)
    draw.text((bx+(bw-(bb[2]-bb[0]))//2,by+bh//2-12),txt,fill=C['black'],font=f)
    _dx=cx+max(int(hr*0.42),8)
    for _yoff in [14,32,52]:
        _r=5; _dy=cy-hr-_yoff
        draw.ellipse([_dx-_r,_dy-_r,_dx+_r,_dy+_r],fill=C['black'])

# ── HOURGLASS ─────────────────────────────────────────────────────────────────
def _hourglass(draw, cx, cy, s=100):
    s2=s//2
    _sp(draw,[(cx,cy-s2),(cx-s2,cy-s),(cx+s2,cy-s)],fill=C['yellow'],outline=C['black'],width=3)
    _sp(draw,[(cx,cy+s2),(cx-s2,cy+s),(cx+s2,cy+s)],fill=C['yellow'],outline=C['black'],width=3)
    _sp(draw,[(cx,cy+s2),(cx-s2//2,cy+s-12),(cx+s2//2,cy+s-12)],fill=C['brown'])
    for _lx in [-7,7]:
        _sl(draw,cx+_lx,cy-s2,cx+_lx,cy+s2,C['black'],3)
    _sl(draw,cx-7,cy-s2,cx+7,cy-s2,C['black'],3)
    _sl(draw,cx-7,cy+s2,cx+7,cy+s2,C['black'],3)

# ── GLOBE ─────────────────────────────────────────────────────────────────────
def _globe(draw, cx, cy, r=105):
    _se(draw,cx,cy,r,r,C['black'],C['blue'],4,2)
    for bx1,by1,bx2,by2 in [(-r//3,-r//2,r//3,4),(-r//2,2,-r//8,r//2),(r//8,r//4,r//2,r//2)]:
        _se(draw,(cx+bx1+cx+bx2)//2,(cy+by1+cy+by2)//2,(bx2-bx1)//2,(by2-by1)//2,
            C['black'],C['green'],2,2)
    for _fy in [-0.45,0.0,0.45]:
        _oy=cy+int(r*_fy); _rr2=max(int(r*r-(r*_fy)**2),0); _hw=int(_rr2**0.5)
        if _hw>4: _sarc(draw,cx,_oy,_hw,10,0,180,(255,255,255),2,1)
    _se(draw,cx,cy,r,r,C['black'],None,4,2)

# ── ARROW ─────────────────────────────────────────────────────────────────────
def _arrow(draw, x1, y1, x2, y2, label):
    _sl(draw,x1,y1,x2,y2,C['yellow'],7,1)
    ang=math.atan2(y2-y1,x2-x1); ahl=22
    p1=(x2+int(ahl*math.cos(ang+math.pi*5/6)),y2+int(ahl*math.sin(ang+math.pi*5/6)))
    p2=(x2+int(ahl*math.cos(ang-math.pi*5/6)),y2+int(ahl*math.sin(ang-math.pi*5/6)))
    _sp(draw,[(x2,y2),p1,p2],fill=C['yellow'])
    f=_font(32); bb=draw.textbbox((0,0),label.upper(),font=f)
    draw.text((x2+18,y2-(bb[3]-bb[1])//2),label.upper(),fill=C['black'],font=f)

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
                  int(cx+(r+16)*math.cos(_rad)),int(cy-r//2+(r+16)*math.sin(_rad)),C['yellow'],2,0)

# ── BRAIN VILLAIN ─────────────────────────────────────────────────────────────
def _villain(draw, cx, cy, label):
    r=95
    _se(draw,cx,cy,r,r,C['black'],C['blue'],5,3)
    for _bx,_by in [(-r+13,-r+14),(0,-r+8),(r-13,-r+14)]:
        _se(draw,cx+_bx,cy+_by,24,24,C['black'],C['blue'],3,2)
    ew=10
    draw.ellipse([cx-36-ew,cy-17-ew,cx-36+ew,cy-17+ew],fill=C['black'])
    draw.ellipse([cx+36-ew,cy-17-ew,cx+36+ew,cy-17+ew],fill=C['black'])
    _sl(draw,cx-46,cy-37,cx-22,cy-22,C['black'],4,1)
    _sl(draw,cx+22,cy-22,cx+46,cy-37,C['black'],4,1)
    _sarc(draw,cx,cy+15,34,22,0,180,C['black'],4,1)
    # Neural connection sparks
    for _ang in range(0,360,45):
        _rad=math.radians(_ang); _r1=r+4; _r2=r+22
        _sl(draw,int(cx+_r1*math.cos(_rad)),int(cy+_r1*math.sin(_rad)),
                  int(cx+_r2*math.cos(_rad)),int(cy+_r2*math.sin(_rad)),C['yellow'],2,0)
    f=_font(44); lb=label.upper(); bb=draw.textbbox((0,0),lb,font=f)
    draw.text(((W-(bb[2]-bb[0]))//2, DZ_TOP+8), lb, fill=C['red'], font=f)

# ── EVOLUTION ROW ─────────────────────────────────────────────────────────────
def _evo_row(draw, fig_y=DZ_MID):
    xs=[W//6,W//2,5*W//6]; lbs=['EARLY','MIDDLE','NOW']
    szs=[76,92,110]; exs=['neutral','neutral','happy']
    for i,(px,lb,sz,ex) in enumerate(zip(xs,lbs,szs,exs)):
        _figure(draw,px,fig_y,sz,ex)
        f=_font(26); bb=draw.textbbox((0,0),lb,font=f)
        draw.text((px-(bb[2]-bb[0])//2, fig_y+sz+18), lb, fill=C['black'],font=f)
        if i<2:
            ax1=px+szs[i]//2+12; ax2=xs[i+1]-szs[i+1]//2-12
            _sl(draw,ax1,fig_y,ax2,fig_y,C['black'],5,1)
            draw.polygon([(ax2+14,fig_y),(ax2-4,fig_y-11),(ax2-4,fig_y+11)],fill=C['black'])

# ── TIMELINE (NEW) ────────────────────────────────────────────────────────────
def _timeline(draw, text):
    # Extract dates/labels
    years = re.findall(r'\\b(\\d{2,4})\\s*(BC|AD|BCE|CE)?\\b', text)
    labels = [f"{y} {s}".strip() for y,s in years if 10<=int(y)<=2100][:5]
    if len(labels)<2:
        phases = re.findall(r'\\b(first|early|then|later|finally|next|today|now|modern)\\b',
                             text, re.I)
        labels = [p.upper() for p in phases[:5]]
    if len(labels)<2:
        labels = ['PAST','MIDDLE','PRESENT','NOW']
    labels = labels[:5]
    n  = len(labels)
    x0 = 110; x1 = W-130; y = DZ_MID
    # Main axis line
    _sl(draw, x0,y, x1,y, C['black'], 5, 1)
    # Arrow head
    draw.polygon([(x1+16,y),(x1-2,y-10),(x1-2,y+10)],fill=C['black'])
    f2=_font(22); f3=_font(20)
    draw.text((x1+22,y-11),'TIME',fill=C['blue'],font=f2)
    for i,label in enumerate(labels):
        x = x0 + (x1-x0)*i//max(n-1,1)
        col_dot = C['orange'] if i<n-1 else C['green']
        _se(draw,x,y,16,16,C['black'],col_dot,3,1)
        bb=draw.textbbox((0,0),label,font=f3)
        tw=bb[2]-bb[0]
        if i%2==0:
            _sl(draw,x,y-18,x,y-36,C['black'],2,0)
            draw.text((max(x-tw//2,8),y-56),label,fill=C['black'],font=f3)
        else:
            _sl(draw,x,y+18,x,y+36,C['black'],2,0)
            draw.text((max(x-tw//2,8),y+40),label,fill=C['black'],font=f3)
    # Top label
    _top_label(draw,'TIMELINE',C['blue'])

# ── QUOTE CARD (NEW) ──────────────────────────────────────────────────────────
def _quote_card(draw, text):
    fq=_font(120)
    draw.text((50, DZ_TOP+14), '\\u201c', fill=C['blue'], font=fq)
    # Centre text
    f=_font(34); words=text.split()
    clean=re.sub(r'[\\u201c\\u201d"\\u0022]','',text)[:110]
    lines=_wrap(clean[:110], draw, f, W-240)
    y=DZ_MID-(len(lines)*46)//2
    for line in lines:
        bb=draw.textbbox((0,0),line,font=f)
        draw.text(((W-(bb[2]-bb[0]))//2, y), line, fill=C['black'], font=f)
        y+=50
    # Closing mark
    fq2=_font(80)
    draw.text((W-100, y+10), '\\u201d', fill=C['blue'], font=fq2)
    # Decorative underline
    _sl(draw,W//2-90,y+36,W//2+90,y+36,C['blue'],3,1)

# ── COMPARISON (NEW) ──────────────────────────────────────────────────────────
def _comparison(draw, text, expr='neutral'):
    mid=W//2
    # Divider line
    _sl(draw,mid,DZ_TOP+40,mid,DZ_BOT-20,C['red'],4,1)
    # VS badge
    f=_font(50); bb=draw.textbbox((0,0),'VS',font=f)
    tw,th=bb[2]-bb[0],bb[3]-bb[1]
    draw.rectangle([mid-tw//2-12,DZ_MID-th//2-8,mid+tw//2+12,DZ_MID+th//2+8],fill=C['red'])
    draw.text((mid-tw//2,DZ_MID-th//2-2),'VS',fill=C['white'],font=f)
    # Two figures
    _figure(draw,W//4,DZ_MID,100,'happy')
    _figure(draw,3*W//4,DZ_MID,100,'sad')
    # Side labels from text split
    parts=re.split(r'\\b(vs\\.?|versus|compared to|but|while|whereas|however)\\b',
                   text,maxsplit=1,flags=re.I)
    f2=_font(24)
    sides=[(W//4,parts[0].strip()[:40]),(3*W//4,parts[-1].strip()[:40])] if len(parts)>=3 else []
    for sx,stxt in sides:
        lns=_wrap(stxt, draw, f2, W//2-70)
        yy=DZ_MID+120
        for ln in lns[:2]:
            bb=draw.textbbox((0,0),ln,font=f2)
            draw.text((sx-(bb[2]-bb[0])//2,yy),ln,fill=C['black'],font=f2)
            yy+=30

# ── STAT BAR CHART (NEW) ──────────────────────────────────────────────────────
def _stat_bar(draw, text):
    pcts=re.findall(r'(\\d+)\\s*(?:percent|%)',text.lower())
    if len(pcts)>=2:
        bars=[(p+'%',min(int(p),100)/100) for p in pcts[:3]]
    else:
        bars=[('67%',0.67),('23%',0.23),('10%',0.10)]
    cl=160; cr=W-160; cb=DZ_BOT-40; ct=DZ_TOP+60
    bcols=[C['blue'],C['orange'],C['green'],C['red']]
    n=len(bars); bw=(cr-cl)//(n*2); gap=bw//2
    _sl(draw,cl-10,ct,cl-10,cb,C['black'],3,1)
    _sl(draw,cl-10,cb,cr+10,cb,C['black'],3,1)
    for i,(label,pct) in enumerate(bars):
        x=cl+i*(cr-cl)//n+gap
        bh=int((cb-ct-28)*min(pct,1.0))
        col=bcols[i%len(bcols)]
        _sp(draw,[(x,cb-bh),(x+bw,cb-bh),(x+bw,cb),(x,cb)],
            fill=col,outline=C['black'],width=2,wob=2)
        f=_font(28); bb=draw.textbbox((0,0),label,font=f)
        draw.text((x+bw//2-(bb[2]-bb[0])//2,cb-bh-36),label,fill=col,font=f)
    _top_label(draw,'STATS',C['blue'])

# ── TOP LABEL / WATERMARK ─────────────────────────────────────────────────────
def _top_label(draw, text, col=None):
    col=col or C['black']; f=_font(44)
    bb=draw.textbbox((0,0),text.upper(),font=f)
    draw.text(((W-(bb[2]-bb[0]))//2, DZ_TOP+5), text.upper(), fill=col, font=f)

def _watermark(draw):
    f=_font(20); txt='UNLEARNED'
    bb=draw.textbbox((0,0),txt,font=f); tw,th=bb[2]-bb[0],bb[3]-bb[1]
    draw.rectangle([W-tw-36,10,W-10,th+28], fill=C['white'], outline=C['blue'], width=2)
    draw.text((W-tw-28,14), txt, fill=C['blue'], font=f)

def _stat(text):
    m=re.search(r'\\b(\\d[\\d,]*)\\s*(million|thousand|billion|percent|%|year|day|hour|minute)?',
                text.lower())
    if m:
        n=m.group(1); u=(m.group(2) or '').upper()
        return f'{n} {u}'.strip()
    words=[w for w in re.findall(r'\\b[A-Za-z]{5,}\\b',text)
           if w.lower() not in {'about','after','before','their','there','would',
                                  'could','should','being','every','which','these'}]
    return words[0].upper() if words else 'FACT'

# ── RENDER LOOP ───────────────────────────────────────────────────────────────
_n=len(SCENE_DATA)
_exist=sum(1 for s in SCENE_DATA if os.path.exists(s['image']))
if _exist==_n:
    print(f'All {_n} images already on disk. Run Cell 5.')
else:
    print(f'Drawing {_n} doodle images (v5: 12 frame types, 6 palettes, props)...')
    for _i, _sc in enumerate(SCENE_DATA):
        _out=_sc['image']
        if os.path.exists(_out): print(f'  [{_i+1}/{_n}] cached'); continue

        _RNG.seed(_i*137+7)
        _txt=_sc['text']
        _img=Image.new('RGB',(W,H),C['white'])
        _d  =ImageDraw.Draw(_img)
        _bg =_fill_bg(_d,_txt,_i)
        _ft =_frame_type(_txt,_i)
        _ex =_expr(_txt)
        _mx =W//2; _my=DZ_MID

        if _ft=='concept_text':
            _hourglass(_d,_mx,_my,98)
            _st=_stat(_txt); f=_font(68)
            bb=_d.textbbox((0,0),_st,font=f)
            _d.text((_mx-(bb[2]-bb[0])//2,_my-158),_st,fill=C['red'],font=f)
            _top_label(_d,'DID YOU KNOW?',C['blue'])

        elif _ft=='stat_bar':
            _stat_bar(_d,_txt)

        elif _ft=='evolution':
            _evo_row(_d,fig_y=_my)

        elif _ft=='villain':
            _kws=[w for w in re.findall(r'\\b[A-Za-z]{4,}\\b',_txt)
                  if w.lower() in {'brain','stress','anxiety','dopamine','cortisol','ego',
                                    'addiction','trauma','fear','depression','serotonin',
                                    'amygdala','cortex','priming','placebo','bias',
                                    'conformity','groupthink','anchoring','impostor',
                                    'dissonance','attention','loss','aversion'}]
            _villain(_d,_mx,_my,_kws[0] if _kws else 'BRAIN')

        elif _ft=='reaction':
            _fhr=max(int(120*0.24),14)
            _figure(_d,_mx,_my,120,'neutral')
            _bubble(_d,_mx,_my,_fhr,_txt[:30])

        elif _ft=='globe':
            _globe(_d,_mx,_my,105)

        elif _ft=='timeline':
            _timeline(_d,_txt)

        elif _ft=='quote_card':
            _quote_card(_d,_txt)

        elif _ft=='comparison':
            _comparison(_d,_txt,_ex)

        elif _ft=='diagram':
            _fy=_my
            _figure(_d,int(W*0.60),_fy,108,_ex,accessory='graduation')
            _lb_kws=[w for w in re.findall(r'\\b[A-Za-z]{4,}\\b',_txt)
                     if w.lower() not in {'this','that','they','them','with','from',
                                           'have','been','were','would','could','also',
                                           'when','then','some','more','most','kind'}]
            _lb=_lb_kws[0].upper() if _lb_kws else 'TYPE'
            _arrow(_d,int(W*0.13),int(DZ_MID-75),int(W*0.47),_fy,_lb)

        elif _ft=='idea':
            _fy=_my+40
            _figure(_d,_mx,_fy,118,'happy',accessory='graduation')
            _lightbulb(_d,_mx,_fy-max(int(118*0.24),14)-86,64)

        else:  # scene
            _two=any(x in _txt.lower() for x in
                     ['together','friend','group','team','meet','social','both',
                      'they','people','us','each other','pair','couple','someone',
                      'another person','social proof','conformity','authority'])
            _wl=_txt.lower()
            _prop=None
            if any(x in _wl for x in ['book','read','study','learn','knowledge','text','page','library']):
                _prop='book'
            elif any(x in _wl for x in ['computer','phone','screen','online','digital','internet','device','app']):
                _prop='screen'
            elif any(x in _wl for x in ['money','pay','cost','price','salary','wealth','rich','poor','dollar','income']):
                _prop='money'
            elif any(x in _wl for x in ['heart','love','care','relationship','feel','emotion','empathy','connect']):
                _prop='heart'
            # Accessory
            _acc=None
            if any(x in _wl for x in ['ancient','history','king','queen','royal','empire','medieval','pharaoh']):
                _acc='tophat'
            if _two:
                _figure(_d,_mx-140,_my,106,_ex)
                _figure(_d,_mx+140,_my,106,'neutral')
            else:
                _fy=_my
                _figure(_d,_mx,_fy,128,_ex,accessory=_acc)
                if _prop=='book'  and _mx-260 > 30:
                    _prop_book(_d,_mx-210,_fy,44)
                elif _prop=='screen' and _mx+260 < W-30:
                    _prop_screen(_d,_mx+210,_fy,58)
                elif _prop=='money':
                    _prop_money(_d,_mx+190,_fy+50,34)
                elif _prop=='heart':
                    _prop_heart(_d,_mx,_fy-max(int(128*0.24),14)-62,28)

        _watermark(_d)
        _img.save(_out)
        print(f'  [{_i+1}/{_n}] {_ft:<13} {_ex:<8} {_txt[:46]}')

    print(f'\\nAll {_n} images drawn.')

# Preview first 3 in notebook
try:
    from IPython.display import display, Image as _IPImg
    print('\\nPreview (first 3 scenes):')
    for _sc in SCENE_DATA[:3]:
        display(_IPImg(_sc['image'], width=600))
except Exception:
    pass
print('Run Cell 5.')
""")

# ── CELL 6: Ken Burns with per-clip white transitions ──────────────────────────

CELL_MOTION = code("""\
# ── CELL 5: Ken Burns + per-clip white fade transitions ──────────────────────
import json, os, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'CLIP_DIR'  not in dir(): CLIP_DIR  = f'{WORK_DIR}/clips'
os.makedirs(CLIP_DIR, exist_ok=True)
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_n=len(SCENE_DATA); _clips=[]; _TD=0.15  # transition fade duration (s)
print(f'Building {_n} Ken Burns clips (7 directions, {int(_TD*1000)}ms white fade transitions)...')

for _i, _sc in enumerate(SCENE_DATA):
    _img=_sc['image']; _audio=_sc['audio']; _dur=_sc['duration']
    _clip=f'{CLIP_DIR}/clip_{_i:04d}.mp4'; _clips.append(_clip)
    if os.path.exists(_clip): print(f'  [{_i+1}/{_n}] cached'); continue

    _nf=max(int(_dur*30),2); _p=_i%7
    # 7 Ken Burns directions
    if   _p==0: _zp=f"z='min(zoom+0.0004,1.16)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"
    elif _p==1: _zp=f"z='min(zoom+0.0004,1.16)':x='0':y='0':d={_nf}"
    elif _p==2: _zp=f"z='min(zoom+0.0004,1.16)':x='iw-iw/zoom':y='ih-ih/zoom':d={_nf}"
    elif _p==3: _zp=f"z='if(lte(zoom,1.0),1.16,zoom-0.0004)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"
    elif _p==4: _zp=f"z='min(zoom+0.0004,1.16)':x='iw-iw/zoom':y='0':d={_nf}"
    elif _p==5: _zp=f"z='min(zoom+0.0004,1.16)':x='0':y='ih-ih/zoom':d={_nf}"
    else:       _zp=f"z='if(lte(zoom,1.0),1.16,zoom-0.0004)':x='iw-iw/zoom':y='0':d={_nf}"

    # Per-clip fade: fade-in (except scene 0) + fade-out to white
    _fo_st=max(0.0, _dur-_TD-0.05)
    _fi=f',fade=t=in:st=0:d={_TD}:color=white' if _i>0 else ''
    _fo=f',fade=t=out:st={_fo_st:.2f}:d={_TD}:color=white'
    _vf=f'[0:v]scale=1280:720,zoompan={_zp}:s=1280x720:fps=30{_fi}{_fo}[v]'

    _r=subprocess.run([
        'ffmpeg','-y','-loop','1','-i',_img,'-i',_audio,
        '-filter_complex',_vf,
        '-map','[v]','-map','1:a',
        '-c:v','libx264','-crf','17','-preset','fast',
        '-c:a','aac','-b:a','192k','-shortest','-pix_fmt','yuv420p',_clip,
    ], capture_output=True, text=True)
    if _r.returncode!=0:
        print(f'  Clip {_i} error:\\n{_r.stderr[-400:]}')
        raise RuntimeError(f'Clip {_i} failed')
    print(f'  [{_i+1}/{_n}] {_dur:.1f}s  KB-dir={_p}  clip_{_i:04d}.mp4')

import json as _jj
with open(f'{WORK_DIR}/clip_paths.json','w') as _f: _jj.dump(_clips,_f)
print(f'\\n{_n} clips done. Run Cell 6.')
""")

# ── CELL 7: Karplus-Strong Music v5 ───────────────────────────────────────────

CELL_MUSIC = code("""\
# ── CELL 6: Music v5 — chunk-KS (100x faster), 16-bar + melody ───────────────
# Karplus-Strong via period-by-period numpy (NOT sample-by-sample) — ~100x faster.
# 16-bar loop: bars 1-8 C-G-Am-F (arpeggio ascending) +
#              bars 9-16 Am-F-C-G (arpeggio descending) + pentatonic melody line.
import numpy as np, wave, os, subprocess, json

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_total_dur = sum(s['duration'] for s in SCENE_DATA)
_music_dur = _total_dur + 12.0
SR         = 44100
BPM        = 112.0
BEAT       = 60.0/BPM        # 0.5357 s
HALF_BEAT  = BEAT/2           # 0.2679 s
LOOP_BARS  = 16
LOOP_SAMP  = int(SR * LOOP_BARS * 4 * BEAT)

np.random.seed(42)   # reproducible

def _ks(freq, dur_sec, damping=0.9965):
    '''Chunk-based KS: iterate period-by-period with numpy roll (100x faster).'''
    n      = int(SR * dur_sec)
    period = max(int(round(SR / freq)), 1)
    buf    = np.random.uniform(-0.5, 0.5, period).astype(np.float32)
    n_cks  = n // period + 2
    chunks = []
    for _ in range(n_cks):
        chunks.append(buf.copy())
        buf = damping * 0.5 * (buf + np.roll(buf, -1))
    return np.concatenate(chunks)[:n]

# Chord definitions
CHORDS_A = [              # C-G-Am-F × 2  (bars 1-8)
    [261.63,329.63,392.00],   # C major
    [196.00,246.94,293.66],   # G major
    [220.00,261.63,329.63],   # A minor
    [174.61,220.00,261.63],   # F major
]*2
CHORDS_B = [              # Am-F-C-G × 2  (bars 9-16)
    [220.00,261.63,329.63],   # A minor
    [174.61,220.00,261.63],   # F major
    [261.63,329.63,392.00],   # C major
    [196.00,246.94,293.66],   # G major
]*2

ARP_A=[(0,0.34),(1,0.27),(2,0.24),(0,0.19)]  # root 3rd 5th root (ascending)
ARP_B=[(2,0.30),(1,0.26),(0,0.22),(2,0.18)]  # 5th 3rd root 5th (descending)

# Pentatonic melody (C5-A5 range) — A=ascending, B=descending
PENTA_A=[523.25,587.33,659.25,783.99,880.00,783.99,659.25,587.33]
PENTA_B=[880.00,783.99,659.25,587.33,523.25,587.33,659.25,783.99]
MELODY_VOL=0.09

print(f'Generating 16-bar KS loop × {_music_dur//(LOOP_BARS*4*BEAT):.1f}...')
print('(chunk-based — should finish in a few seconds)')

mix = np.zeros(LOOP_SAMP, dtype=np.float32)

for bar_idx in range(LOOP_BARS):
    is_b    = bar_idx >= LOOP_BARS//2
    chord   = CHORDS_B[bar_idx-LOOP_BARS//2] if is_b else CHORDS_A[bar_idx]
    arp     = ARP_B if is_b else ARP_A
    melody  = PENTA_B if is_b else PENTA_A
    root,third,fifth = chord

    # Arpeggio
    for beat_idx,(ni,vol) in enumerate(arp):
        freq = [root,third,fifth][ni]
        samp_st = int((bar_idx*4+beat_idx)*BEAT*SR)
        note    = _ks(freq, BEAT*0.88)*vol
        end     = min(samp_st+len(note), LOOP_SAMP)
        mix[samp_st:end] += note[:end-samp_st]

    # Bass (root -1 octave, longer decay)
    bvol = 0.20 if is_b else 0.22
    bass = _ks(root/2, BEAT*1.6, damping=0.999)*bvol
    bst  = int(bar_idx*4*BEAT*SR)
    end  = min(bst+len(bass), LOOP_SAMP)
    mix[bst:end] += bass[:end-bst]

    # Melody (pentatonic, 8 notes per bar, half-beat spacing)
    for ni,mel_freq in enumerate(melody):
        samp_st=int((bar_idx*8+ni)*HALF_BEAT*SR)
        note=_ks(mel_freq, HALF_BEAT*0.76, damping=0.9945)*MELODY_VOL
        end=min(samp_st+len(note), LOOP_SAMP)
        mix[samp_st:end] += note[:end-samp_st]

print('KS loop done.')

# Normalise + master fade
mix /= (np.max(np.abs(mix))+1e-9); mix *= 0.60
_fi=int(SR*1.5); _fo=int(SR*2.0)
mix[:_fi]  *= np.linspace(0,1,_fi,  dtype=np.float32)
mix[-_fo:] *= np.linspace(1,0,_fo,  dtype=np.float32)

_loop_wav=f'{WORK_DIR}/music_loop.wav'
MUSIC_MP3 =f'{WORK_DIR}/background_music.mp3'
_pcm=(mix*32767).clip(-32768,32767).astype(np.int16)
with wave.open(_loop_wav,'w') as _wf:
    _wf.setnchannels(1); _wf.setsampwidth(2); _wf.setframerate(SR)
    _wf.writeframes(_pcm.tobytes())

_fade_st=max(0,_music_dur-7.0)
subprocess.run([
    'ffmpeg','-y','-stream_loop','-1','-i',_loop_wav,
    '-t',str(_music_dur),
    '-af',f'afade=t=in:st=0:d=2,afade=t=out:st={_fade_st:.1f}:d=7',
    '-q:a','4',MUSIC_MP3,
], capture_output=True, check=True)
os.remove(_loop_wav)

print(f'Music: 16-bar KS harp+melody  {_music_dur:.0f}s  ({MUSIC_MP3})')
print('Run Cell 7.')
""")

# ── CELL 8: Assemble ──────────────────────────────────────────────────────────

CELL_ASSEMBLE = code("""\
# ── CELL 7: Assemble clips ────────────────────────────────────────────────────
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

# ── CELL 9: ASS Captions (4-word phrase grouping, font 28) ────────────────────

CELL_CAPTIONS = code("""\
# ── CELL 8: Yellow ASS captions — 4-word phrase groups, font 28 ──────────────
# No PIL caption band. These ASS captions ARE the only on-screen text.
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

def _group_words(entries, n=4):
    '''Group word-level VTT entries into n-word phrase chunks.'''
    if not entries: return []
    groups=[]
    for i in range(0, len(entries), n):
        chunk=entries[i:i+n]
        s,e=chunk[0][0],chunk[-1][1]
        txt=' '.join(c[2] for c in chunk)
        groups.append((s,e,txt))
    return groups

def _ass_ts(sec):
    h=int(sec//3600);m=int((sec%3600)//60);s=int(sec%60);cs=int((sec%1)*100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'
def _srt_ts(sec):
    h=int(sec//3600);m=int((sec%3600)//60);s=int(sec%60);ms=int((sec%1)*1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

_all=[]; _offset=0.0
for _sc in SCENE_DATA:
    _entries=_parse_vtt(_sc.get('vtt',''), _offset)
    if _entries:
        # Detect word-level VTT (avg ≤2 words per entry) → group into 4-word phrases
        _avg=sum(len(e[2].split()) for e in _entries)/len(_entries)
        if _avg<=2.5:
            _entries=_group_words(_entries, n=4)
        _all.extend(_entries)
    else:
        _all.append((_offset, _offset+_sc['duration'], _sc['text']))
    _offset+=_sc['duration']

# ASS style: yellow, font 28, 2.5px black outline, bottom-centre, 32px margin
ASS_HEADER='''[Script Info]
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1280
PlayResY: 720
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2.5,0,2,10,10,32,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''

_ass_path=f'{WORK_DIR}/captions.ass'
_srt_path=f'{WORK_DIR}/captions.srt'

with open(_ass_path,'w',encoding='utf-8') as f:
    f.write(ASS_HEADER)
    for s,e,txt in _all:
        clean=txt.replace('{','').replace('}','').strip()
        if clean:
            f.write(f"Dialogue: 0,{_ass_ts(s)},{_ass_ts(e)},Default,,0,0,0,,{clean}\\n")
with open(_srt_path,'w',encoding='utf-8') as f:
    for idx,(s,e,txt) in enumerate(_all,1):
        f.write(f'{idx}\\n{_srt_ts(s)} --> {_srt_ts(e)}\\n{txt.strip()}\\n\\n')

print(f'Captions: {len(_all)} entries (4-word phrases, font 28, yellow)')

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
    _style="FontName=Arial,FontSize=26,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2.5,Bold=1,Alignment=2,MarginV=32"
    _r2=subprocess.run([
        'ffmpeg','-y','-i',RAW_VIDEO,
        '-vf',f"subtitles='{_srt_esc}':force_style='{_style}'",
        '-c:a','copy','-c:v','libx264','-crf','17','-preset','fast',
        CAPTIONED_VIDEO,
    ], capture_output=True, text=True)
    if _r2.returncode!=0:
        print('Both sub filters failed — copying without burn.')
        print('Upload captions.srt to YouTube Studio manually.')
        import shutil; shutil.copy2(RAW_VIDEO, CAPTIONED_VIDEO)
    else:
        print('SRT fallback OK.')
else:
    print('Captions burned: yellow/font-28/2.5px-outline.')

print('Run Cell 9.')
""")

# ── CELL 10: Mix ──────────────────────────────────────────────────────────────

CELL_MIX = code("""\
# ── CELL 9: Mix music + loudnorm voiceover + white fade in/out ────────────────
import json, os, re, subprocess

if 'WORK_DIR'    not in dir(): WORK_DIR    = '/content/unlearned'
if 'MUSIC_VOL'   not in dir(): MUSIC_VOL   = 0.14
if 'CAPTIONED_VIDEO' not in dir(): CAPTIONED_VIDEO=f'{WORK_DIR}/video_captioned.mp4'
if 'MUSIC_MP3'   not in dir(): MUSIC_MP3   = f'{WORK_DIR}/background_music.mp3'
if not os.path.exists(CAPTIONED_VIDEO): CAPTIONED_VIDEO=f'{WORK_DIR}/video_raw.mp4'
if 'EPISODE_TITLE' not in dir():
    _tp=f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE=open(_tp).read().strip() if os.path.exists(_tp) else 'Episode'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA=json.load(_f)

_total=sum(s['duration'] for s in SCENE_DATA)
_fo_st=max(0, _total-2.5)
_safe=re.sub(r'[^\\w\\s-]+','',EPISODE_TITLE).strip().replace(' ','_')
FINAL_VIDEO=f'{WORK_DIR}/UNLEARNED_{_safe}.mp4'

print(f'Mixing: voiceover loudnorm -16 LUFS + music {int(MUSIC_VOL*100)}%')
print(f'Fade: in 0.8s white  |  out 2.5s white')

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
    if _r2.returncode!=0:
        print(_r2.stderr[-600:]); raise RuntimeError('Mix failed')

_mb=os.path.getsize(FINAL_VIDEO)/1_048_576
print(f'\\nFinal video : {FINAL_VIDEO}')
print(f'Size        : {_mb:.1f} MB  |  Duration: {_total:.0f}s ({_total/60:.1f} min)')
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
    raise RuntimeError(f'Video not found: {FINAL_VIDEO}  — run Cell 9 first.')

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
    print('  • Upload UNLEARNED_*.mp4 as the main video')
    print('  • Upload captions.srt in YouTube Studio → Subtitles (word-synced)')
    print('  • captions.ass burned-in version is already inside the video')

print('\\nDone!')
""")

# ── Assemble notebook ──────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE, CELL_INSTALL, CELL_SETUP, CELL_VOICE,
    CELL_DOODLE, CELL_MOTION, CELL_MUSIC, CELL_ASSEMBLE,
    CELL_CAPTIONS, CELL_MIX, CELL_DOWNLOAD,
]

NOTEBOOK = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {
        "colab":      {"provenance": [], "gpuType": "None"},
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
