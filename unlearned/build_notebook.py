"""
Build the Unlearned Video Generator Colab notebook — v7 (YouTube Standard).
Run: python build_notebook.py
Output: unlearned_generator.ipynb

V7 vs V6 — YouTube Standard fixes:
  - 1920×1080 output (all clips, title card, end card upscaled via LANCZOS)
  - Audio loudnorm target -14 LUFS (YouTube recommended, was -16)
  - Stereo audio enforced (-ac 2) on every ffmpeg output stage
  - Subscribe end card extended 4 s → 20 s (fits YouTube end-screen overlay)
  - ASS captions updated: PlayRes 1920×1080, font 42, outline 3.5, MarginV 48

V6 features carried forward:
  - Branded 3 s title card (dark navy + episode title + UNLEARNED badge)
  - YouTube thumbnail.jpg auto-generated (eye-catching dark bg + spotlight)
  - yt_description.txt + yt_chapters.txt downloaded with video
  - Music echo reverb (aecho 0.85:0.90:40:0.35)
  - 5 skin-tone variations cycling per scene
  - Dot-grid texture on soft/white backgrounds
  - 13 frame types including numbered_list
  - Caption timing offset reads title_dur.txt
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
# UNLEARNED — Automated Video Generator  v7 ✦ YouTube Standard
### Psychology · Ancient History · Behavioral Science

| Cell | What it does |
|------|-------------|
| 1 | Install packages |
| 2 | Setup — voice selector, volume |
| 3 | Upload `.txt` script → voiceover + word-timing VTT |
| 4 | Doodle images — 13 frame types, skin tones, dot-grid BG, title/end/thumbnail |
| 5 | Ken Burns motion clips (1920×1080) + title card + 20 s end card |
| 6 | Background music — chunk-KS harp, 16-bar loop, echo reverb |
| 7 | Assemble: title card + scenes + end card |
| 8 | Burn yellow ASS captions (4-word sync, 1080p scale) |
| 9 | Mix audio — loudnorm -14 LUFS stereo + white master fade |
| 10 | Download MP4 + captions + thumbnail + YT description + chapters |

**v7 fixes:** 1920×1080 · -14 LUFS · 192k AAC stereo · 20 s end card · H.264 High Profile · 2 s keyframes
**v6 features:** branded intro/outro · thumbnail · YT description & chapters ·
5 skin tones · dot-grid BG · numbered-list frame · echo music · caption offset
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

# ── Voice selector (uncomment one) ───────────────────────────────────────────
VOICE = 'en-US-AndrewNeural'       # default — male, calm, clear
# VOICE = 'en-US-JennyNeural'      # female, friendly
# VOICE = 'en-US-GuyNeural'        # male, professional
# VOICE = 'en-GB-RyanNeural'       # British male, authoritative

VOICE_RATE  = '-5%'
VOICE_PITCH = '+0Hz'
MUSIC_VOL   = 0.14   # background music level (14%)

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
if 'VOICE_PITCH' not in dir(): VOICE_PITCH = '+0Hz'
os.makedirs(AUDIO_DIR, exist_ok=True); os.makedirs(IMG_DIR, exist_ok=True)

print('''
SCRIPT FORMATTING GUIDE
────────────────────────────────────────────────────────
• Write in plain paragraphs — no headers, no bullet points
• Each sentence should be complete and natural-sounding
• Aim for 10-22 words per sentence
• Do NOT write timestamps, scene numbers, or speaker labels
• One concept per sentence/paragraph works best
• Optimal length: 800-1500 words  (~5-8 min video)
────────────────────────────────────────────────────────
''')

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
    _words = []
    with open(apath, 'wb') as af:
        async for chunk in comm.stream():
            if chunk['type'] == 'audio':
                af.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                try: sub.feed(chunk)
                except:
                    try: sub.create_sub((chunk['offset'], chunk['duration']), chunk['text'])
                    except: pass
                try:
                    _ws = chunk.get('offset', 0) / 10_000_000
                    _wd = chunk.get('duration', 0) / 10_000_000
                    _words.append((_ws, _ws + _wd, chunk.get('text', '')))
                except: pass
    with open(vpath, 'w', encoding='utf-8') as vf:
        _vtt = None
        for _attr in ['get_subs', 'generate_subs', 'merge_subs', 'get_srt', 'get_vtt']:
            if hasattr(sub, _attr):
                try: _vtt = getattr(sub, _attr)(); break
                except TypeError:
                    try: _vtt = getattr(sub, _attr)(words_in_cue=10); break
                    except: pass
                except: pass
        if _vtt:
            vf.write(_vtt)
        elif _words:
            def _ts(s):
                h,m,sc=int(s//3600),int((s%3600)//60),s%60
                return f'{h:02d}:{m:02d}:{sc:06.3f}'
            vf.write('WEBVTT\\n\\n')
            for _wi,(_ws,_we,_wt) in enumerate(_words):
                vf.write(f'{_wi+1}\\n{_ts(_ws)} --> {_ts(_we)}\\n{_wt}\\n\\n')
        else:
            vf.write('WEBVTT\\n\\n')

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

# ── Scene validation ───────────────────────────────────────────────────────────
_warns = []
for _si, _sc in enumerate(SCENE_DATA):
    _wc = len(_sc['text'].split())
    if _wc < 8:
        _warns.append(f'  Scene {_si+1}: very short ({_wc} words) — "{_sc["text"][:40]}"')
    elif _wc > 25:
        _warns.append(f'  Scene {_si+1}: long ({_wc} words) — consider splitting')
if _warns:
    print(f'\\nWarnings ({len(_warns)}):')
    for _w in _warns: print(_w)
else:
    print('\\nAll scenes: word count OK.')
print('Voiceover done. Run Cell 4.')
""")

# ── CELL 5: PIL Doodle Images (v6) ────────────────────────────────────────────

CELL_DOODLE = code("""\
# ── CELL 4: Doodle Images v6 — 13 frame types, skin tones, dot-grid, cards ───
import json, os, re, math, random
from PIL import Image, ImageDraw, ImageFont

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'IMG_DIR'   not in dir(): IMG_DIR   = f'{WORK_DIR}/images'
os.makedirs(IMG_DIR, exist_ok=True)
if 'SCENE_DATA' not in dir():
    _jp = f'{WORK_DIR}/scene_data.json'
    if not os.path.exists(_jp): raise RuntimeError('Run Cell 3 first.')
    with open(_jp) as _f: SCENE_DATA = json.load(_f)
if 'EPISODE_TITLE' not in dir():
    _ep_f = f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE = open(_ep_f).read().strip() if os.path.exists(_ep_f) else 'UNLEARNED EPISODE'

W, H = 1280, 720
DZ_TOP = 30
DZ_BOT = 548
DZ_MID = (DZ_TOP + DZ_BOT) // 2

# ── Colour palette ─────────────────────────────────────────────────────────────
C = {
    'orange': (245,130, 13), 'blue':  ( 45, 95,191), 'green': ( 58,158, 58),
    'yellow': (245,197, 24), 'red':   (217, 64, 64), 'brown': (139, 94, 60),
    'sky':    (110,181,232), 'tan':   (196,150, 90), 'white': (255,255,255),
    'black':  (  0,  0,  0), 'skin':  (255,210,165), 'gray':  (220,220,220),
    'dgray':  (150,150,150), 'lblue': (200,220,255), 'pink':  (255,182,193),
    'purple': (128, 80,200), 'teal':  ( 32,178,170), 'gold':  (212,175, 55),
}
SOFT_BG = [
    (255,255,255),
    (255,252,242),
    (242,255,248),
    (248,244,255),
    (255,246,238),
    (238,248,255),
]
SKIN_TONES = [
    (255,210,165),
    (240,184,120),
    (198,134, 66),
    (141, 85, 36),
    (255,224,189),
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

_RNG = random.Random()

# ── Bézier primitives ──────────────────────────────────────────────────────────
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

# ── Background ─────────────────────────────────────────────────────────────────
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
    bg = SOFT_BG[idx % len(SOFT_BG)]
    draw.rectangle([0,0,W,H], fill=bg)
    _dot = tuple(max(0,c-18) for c in bg)
    for _gy in range(0,H,36):
        for _gx in range(0,W,36):
            draw.ellipse([_gx-2,_gy-2,_gx+2,_gy+2], fill=_dot)
    return 'soft'

# ── Frame type — scoring (13 types) ───────────────────────────────────────────
def _frame_type(text, idx=0):
    w  = text.lower()
    sc = {k:0 for k in ['concept_text','evolution','villain','reaction','globe',
                          'diagram','idea','timeline','quote_card','comparison',
                          'stat_bar','numbered_list','scene']}
    if re.search(r'\\b\\d[\\d,]*\\s*(million|thousand|billion|year|day|hour|minute|second)', w):
        sc['concept_text'] += 4
    if re.search(r'\\b\\d+\\s*(%|percent)\\b', w): sc['stat_bar'] += 4
    if any(x in w for x in ['survey','study found','research shows','majority','statistics',
                              'according to a study','scientists found','data shows']):
        sc['stat_bar'] += 2
    for kw in ['evolv','transform','stages','progress','develop','became','sequence',
               'steps','million year','from ape','over time','gradually','generation',
               'mutation','adaptation','selection','species changed']:
        if kw in w: sc['evolution'] += 2
    for kw in ['brain','stress','anxiety','dopamine','cortisol','ego','addiction','trauma',
               'amygdala','serotonin','cortex','priming','placebo','bias','neuron',
               'cognitive','phobia','depression','paranoia','subconscious','unconscious',
               'conformity','groupthink','herd','social proof','anchoring','dunning',
               'impostor','dissonance','attention','loss aversion','sunk cost',
               'negativity bias','optimism bias','recency bias','availability']:
        if kw in w: sc['villain'] += 2
    if re.search(r'\\b(\\d{2,4})\\s*(bc|ad|ce|bce|century|decade)\\b', w): sc['timeline'] += 4
    for kw in ['history','century','decade','era','period','civilization','empire',
               'dynasty','revolution','ancient world','timeline','years ago',
               'discovered in','invented in','founded in','born in']:
        if kw in w: sc['timeline'] += 2
    if '"' in text or '\\u201c' in text or '\\u201d' in text: sc['quote_card'] += 5
    for kw in ['said','stated','according to','wrote','believed','once said',
               'declared','claimed','argued','noted','observed']:
        if kw in w: sc['quote_card'] += 2
    for kw in ['versus','vs.','compared to','difference between','unlike','however',
               'on the other hand','whereas','instead of','rather than','contrast',
               'while the other','one group','another group','group a','group b']:
        if kw in w: sc['comparison'] += 2
    for kw in ['why','wonder','confus','strange','but wait','hmm','believe it',
               'how is that','did you know','turns out','surprisingly','hard to believe',
               'would you believe','here is the thing','actually','in fact']:
        if kw in w: sc['reaction'] += 2
    for kw in ['world','globe','earth','everywhere','planet','global','species',
               'continent','across','universal','worldwide','humanity','entire planet']:
        if kw in w: sc['globe'] += 2
    for kw in ['called','known as','labeled','type of','named','kind of',
               'defined as','refers to','this is called','we call it','term for']:
        if kw in w: sc['diagram'] += 2
    for kw in ['idea','discover','realiz','invent','insight','aha','eureka',
               'thought of','came up with','figured out','breakthrough','solution',
               'innovate','concept','first time','pioneered']:
        if kw in w: sc['idea'] += 2
    if re.search(r'\\b[1-5]\\.\\s', text): sc['numbered_list'] += 5
    for kw in ['first','second','third','fourth','fifth',
               'step','steps','ways','reasons','habits','rules','tips','things']:
        if kw in w: sc['numbered_list'] += 2
    sc['scene'] = 1
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

# ── Stick figure ───────────────────────────────────────────────────────────────
def _figure(draw, cx, cy, size=120, expr='neutral', col=None, accessory=None, skin_col=None):
    col      = col or C['black']
    skin_col = skin_col or C['skin']
    hr   = max(int(size*0.24), 14)
    lw   = max(int(size*0.05), 3)
    ew   = max(int(hr*0.17), 3)
    exo  = int(hr*0.37)
    eyo  = int(hr*0.18)
    ms   = int(hr*0.45)
    mby  = int(hr*0.30)
    bow  = int(hr*0.54)
    broy = cy - eyo - int(hr*0.22)

    _se(draw, cx, cy, hr, hr, col, skin_col, lw, 2)
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

    neck_y = cy+hr; body_b = cy+hr+int(size*0.56)
    _sl(draw, cx,neck_y, cx,body_b, col,lw,2)

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

    for _sd in [-1,1]:
        _kx = cx+_sd*int(size*0.18); _ky = body_b+int(size*0.22)
        _fx = cx+_sd*int(size*0.30); _fy = body_b+int(size*0.44)
        _sl(draw, cx,body_b, _kx,_ky, col,lw,2)
        _sl(draw, _kx,_ky, _fx,_fy, col,lw,2)
        _sw2 = int(size*0.12)
        draw.ellipse([_fx-_sw2, _fy-4, _fx+_sw2+6, _fy+int(size*0.05)], fill=C['black'])

    _sw = int(size*0.38); _sh2 = max(int(size*0.05),3)
    _sby = body_b+int(size*0.44)+_sh2+6
    draw.ellipse([cx-_sw,_sby-_sh2,cx+_sw,_sby+_sh2], fill=C['dgray'])

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

# ── Props ──────────────────────────────────────────────────────────────────────
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

# ── Thought bubble ─────────────────────────────────────────────────────────────
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

# ── Hourglass ──────────────────────────────────────────────────────────────────
def _hourglass(draw, cx, cy, s=100):
    s2=s//2
    _sp(draw,[(cx,cy-s2),(cx-s2,cy-s),(cx+s2,cy-s)],fill=C['yellow'],outline=C['black'],width=3)
    _sp(draw,[(cx,cy+s2),(cx-s2,cy+s),(cx+s2,cy+s)],fill=C['yellow'],outline=C['black'],width=3)
    _sp(draw,[(cx,cy+s2),(cx-s2//2,cy+s-12),(cx+s2//2,cy+s-12)],fill=C['brown'])
    for _lx in [-7,7]:
        _sl(draw,cx+_lx,cy-s2,cx+_lx,cy+s2,C['black'],3)
    _sl(draw,cx-7,cy-s2,cx+7,cy-s2,C['black'],3)
    _sl(draw,cx-7,cy+s2,cx+7,cy+s2,C['black'],3)

# ── Globe ──────────────────────────────────────────────────────────────────────
def _globe(draw, cx, cy, r=105):
    _se(draw,cx,cy,r,r,C['black'],C['blue'],4,2)
    for bx1,by1,bx2,by2 in [(-r//3,-r//2,r//3,4),(-r//2,2,-r//8,r//2),(r//8,r//4,r//2,r//2)]:
        _se(draw,(cx+bx1+cx+bx2)//2,(cy+by1+cy+by2)//2,(bx2-bx1)//2,(by2-by1)//2,
            C['black'],C['green'],2,2)
    for _fy in [-0.45,0.0,0.45]:
        _oy=cy+int(r*_fy); _rr2=max(int(r*r-(r*_fy)**2),0); _hw=int(_rr2**0.5)
        if _hw>4: _sarc(draw,cx,_oy,_hw,10,0,180,(255,255,255),2,1)
    _se(draw,cx,cy,r,r,C['black'],None,4,2)

# ── Arrow ──────────────────────────────────────────────────────────────────────
def _arrow(draw, x1, y1, x2, y2, label):
    _sl(draw,x1,y1,x2,y2,C['yellow'],7,1)
    ang=math.atan2(y2-y1,x2-x1); ahl=22
    p1=(x2+int(ahl*math.cos(ang+math.pi*5/6)),y2+int(ahl*math.sin(ang+math.pi*5/6)))
    p2=(x2+int(ahl*math.cos(ang-math.pi*5/6)),y2+int(ahl*math.sin(ang-math.pi*5/6)))
    _sp(draw,[(x2,y2),p1,p2],fill=C['yellow'])
    f=_font(32); bb=draw.textbbox((0,0),label.upper(),font=f)
    draw.text((x2+18,y2-(bb[3]-bb[1])//2),label.upper(),fill=C['black'],font=f)

# ── Lightbulb ──────────────────────────────────────────────────────────────────
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

# ── Brain villain ──────────────────────────────────────────────────────────────
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
    for _ang in range(0,360,45):
        _rad=math.radians(_ang); _r1=r+4; _r2=r+22
        _sl(draw,int(cx+_r1*math.cos(_rad)),int(cy+_r1*math.sin(_rad)),
                  int(cx+_r2*math.cos(_rad)),int(cy+_r2*math.sin(_rad)),C['yellow'],2,0)
    f=_font(44); lb=label.upper(); bb=draw.textbbox((0,0),lb,font=f)
    draw.text(((W-(bb[2]-bb[0]))//2, DZ_TOP+8), lb, fill=C['red'], font=f)

# ── Evolution row ──────────────────────────────────────────────────────────────
def _evo_row(draw, fig_y=DZ_MID, skin_col=None):
    skin_col = skin_col or C['skin']
    xs=[W//6,W//2,5*W//6]; lbs=['EARLY','MIDDLE','NOW']
    szs=[76,92,110]; exs=['neutral','neutral','happy']
    for i,(px,lb,sz,ex) in enumerate(zip(xs,lbs,szs,exs)):
        _figure(draw,px,fig_y,sz,ex,skin_col=skin_col)
        f=_font(26); bb=draw.textbbox((0,0),lb,font=f)
        draw.text((px-(bb[2]-bb[0])//2, fig_y+sz+18), lb, fill=C['black'],font=f)
        if i<2:
            ax1=px+szs[i]//2+12; ax2=xs[i+1]-szs[i+1]//2-12
            _sl(draw,ax1,fig_y,ax2,fig_y,C['black'],5,1)
            draw.polygon([(ax2+14,fig_y),(ax2-4,fig_y-11),(ax2-4,fig_y+11)],fill=C['black'])

# ── Timeline ───────────────────────────────────────────────────────────────────
def _timeline(draw, text):
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
    _sl(draw, x0,y, x1,y, C['black'], 5, 1)
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
    _top_label(draw,'TIMELINE',C['blue'])

# ── Quote card ─────────────────────────────────────────────────────────────────
def _quote_card(draw, text):
    fq=_font(120)
    draw.text((50, DZ_TOP+14), '\\u201c', fill=C['blue'], font=fq)
    f=_font(34)
    clean=re.sub(r'[\\u201c\\u201d"\\u0022]','',text)[:110]
    lines=_wrap(clean, draw, f, W-240)
    y=DZ_MID-(len(lines)*46)//2
    for line in lines:
        bb=draw.textbbox((0,0),line,font=f)
        draw.text(((W-(bb[2]-bb[0]))//2, y), line, fill=C['black'], font=f)
        y+=50
    fq2=_font(80)
    draw.text((W-100, y+10), '\\u201d', fill=C['blue'], font=fq2)
    _sl(draw,W//2-90,y+36,W//2+90,y+36,C['blue'],3,1)

# ── Comparison ─────────────────────────────────────────────────────────────────
def _comparison(draw, text, expr='neutral', skin_col=None):
    skin_col = skin_col or C['skin']
    mid=W//2
    _sl(draw,mid,DZ_TOP+40,mid,DZ_BOT-20,C['red'],4,1)
    f=_font(50); bb=draw.textbbox((0,0),'VS',font=f)
    tw,th=bb[2]-bb[0],bb[3]-bb[1]
    draw.rectangle([mid-tw//2-12,DZ_MID-th//2-8,mid+tw//2+12,DZ_MID+th//2+8],fill=C['red'])
    draw.text((mid-tw//2,DZ_MID-th//2-2),'VS',fill=C['white'],font=f)
    _figure(draw,W//4,DZ_MID,100,'happy',skin_col=skin_col)
    _figure(draw,3*W//4,DZ_MID,100,'sad',skin_col=skin_col)
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

# ── Stat bar chart ─────────────────────────────────────────────────────────────
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

# ── Numbered list (NEW) ────────────────────────────────────────────────────────
def _numbered_list(draw, text):
    _items = re.split(r'[,;]|\\band\\b|\\bor\\b|\\bthen\\b', text)
    _items = [i.strip() for i in _items if len(i.strip()) > 3][:5]
    if not _items:
        _wds = text.split()
        _items = [' '.join(_wds[i:i+4]) for i in range(0,min(len(_wds),20),4)][:5]
    _bcols = [C['orange'],C['blue'],C['green'],C['red'],C['purple']]
    _y = DZ_TOP + 52
    _fn = _font(28)
    for _ni, _itm in enumerate(_items[:5]):
        _bc = _bcols[_ni % len(_bcols)]
        _cx2, _cy2 = 88, _y + 22
        draw.ellipse([_cx2-24,_cy2-24,_cx2+24,_cy2+24], fill=_bc)
        _nf = _font(26); _ns = str(_ni+1)
        _nb = draw.textbbox((0,0), _ns, font=_nf)
        draw.text((_cx2-(_nb[2]-_nb[0])//2, _cy2-(_nb[3]-_nb[1])//2), _ns,
                  fill=C['white'], font=_nf)
        _lns = _wrap(_itm.strip()[:60], draw, _fn, W-185)
        _ty = _y + 6
        for _ln in _lns[:2]:
            draw.text((132, _ty), _ln, fill=C['black'], font=_fn)
            _ty += 34
        _y += max(74, _ty - _y + 10)
    _top_label(draw, 'HOW IT WORKS', C['blue'])

# ── Top label / watermark ──────────────────────────────────────────────────────
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

# ── Render loop ────────────────────────────────────────────────────────────────
_n=len(SCENE_DATA)
_exist=sum(1 for s in SCENE_DATA if os.path.exists(s['image']))
if _exist==_n:
    print(f'All {_n} images already on disk.')
else:
    print(f'Drawing {_n} doodle images (v6: 13 frame types, 5 skin tones, dot-grid)...')
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
        _sk =SKIN_TONES[_i % len(SKIN_TONES)]

        if _ft=='concept_text':
            _hourglass(_d,_mx,_my,98)
            _st=_stat(_txt); f=_font(68)
            bb=_d.textbbox((0,0),_st,font=f)
            _d.text((_mx-(bb[2]-bb[0])//2,_my-158),_st,fill=C['red'],font=f)
            _top_label(_d,'DID YOU KNOW?',C['blue'])

        elif _ft=='stat_bar':
            _stat_bar(_d,_txt)

        elif _ft=='evolution':
            _evo_row(_d,fig_y=_my,skin_col=_sk)

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
            _figure(_d,_mx,_my,120,'neutral',skin_col=_sk)
            _bubble(_d,_mx,_my,_fhr,_txt[:30])

        elif _ft=='globe':
            _globe(_d,_mx,_my,105)

        elif _ft=='timeline':
            _timeline(_d,_txt)

        elif _ft=='quote_card':
            _quote_card(_d,_txt)

        elif _ft=='comparison':
            _comparison(_d,_txt,_ex,skin_col=_sk)

        elif _ft=='diagram':
            _figure(_d,int(W*0.60),_my,108,_ex,accessory='graduation',skin_col=_sk)
            _lb_kws=[w for w in re.findall(r'\\b[A-Za-z]{4,}\\b',_txt)
                     if w.lower() not in {'this','that','they','them','with','from',
                                           'have','been','were','would','could','also',
                                           'when','then','some','more','most','kind'}]
            _lb=_lb_kws[0].upper() if _lb_kws else 'TYPE'
            _arrow(_d,int(W*0.13),int(DZ_MID-75),int(W*0.47),_my,_lb)

        elif _ft=='idea':
            _figure(_d,_mx,_my+40,118,'happy',accessory='graduation',skin_col=_sk)
            _lightbulb(_d,_mx,_my+40-max(int(118*0.24),14)-86,64)

        elif _ft=='numbered_list':
            _numbered_list(_d,_txt)

        else:
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
            _acc=None
            if any(x in _wl for x in ['ancient','history','king','queen','royal','empire','medieval','pharaoh']):
                _acc='tophat'
            if _two:
                _figure(_d,_mx-140,_my,106,_ex,skin_col=_sk)
                _figure(_d,_mx+140,_my,106,'neutral',skin_col=SKIN_TONES[(_i+2)%len(SKIN_TONES)])
            else:
                _fy=_my
                _figure(_d,_mx,_fy,128,_ex,accessory=_acc,skin_col=_sk)
                if _prop=='book'  and _mx-260 > 30:
                    _prop_book(_d,_mx-210,_fy,44)
                elif _prop=='screen' and _mx+260 < W-30:
                    _prop_screen(_d,_mx+210,_fy,58)
                elif _prop=='money':
                    _prop_money(_d,_mx+190,_fy+50,34)
                elif _prop=='heart':
                    _prop_heart(_d,_mx,_fy-max(int(128*0.24),14)-62,28)

        _watermark(_d)
        _img.resize((1920, 1080), Image.LANCZOS).save(_out)
        print(f'  [{_i+1}/{_n}] {_ft:<14} {_ex:<8} {_txt[:46]}')

    print(f'\\nAll {_n} images drawn.')

# ── Title card image ───────────────────────────────────────────────────────────
_tc_path = f'{WORK_DIR}/title_card.png'
if not os.path.exists(_tc_path):
    _tc = Image.new('RGB',(W,H),(24,44,100))
    _tcd = ImageDraw.Draw(_tc)
    for _gx in range(0,W,70): _tcd.line([(_gx,0),(_gx,H)],fill=(38,60,125),width=1)
    for _gy in range(0,H,70): _tcd.line([(0,_gy),(W,_gy)],fill=(38,60,125),width=1)
    _tcd.line([(0,H//2-3),(W,H//2-3)],fill=C['orange'],width=4)
    _tcd.line([(0,H//2+3),(W,H//2+3)],fill=C['orange'],width=2)
    _bf=_font(30); _btxt='UNLEARNED'
    _bbb=_tcd.textbbox((0,0),_btxt,font=_bf)
    _bw=_bbb[2]-_bbb[0]+44; _bh=_bbb[3]-_bbb[1]+20
    _tcd.rectangle([W//2-_bw//2,72,W//2+_bw//2,72+_bh],fill=C['orange'])
    _tcd.text((W//2-(_bbb[2]-_bbb[0])//2,72+10),_btxt,fill=C['white'],font=_bf)
    _tf=_font(72); _tls=_wrap(EPISODE_TITLE.upper(),_tcd,_tf,W-160)
    _tty=H//2-len(_tls)*90//2+30
    for _tl in _tls[:3]:
        _tb=_tcd.textbbox((0,0),_tl,font=_tf)
        _tcd.text((W//2-(_tb[2]-_tb[0])//2,_tty),_tl,fill=C['white'],font=_tf)
        _tty+=92
    _tcd.line([(90,H-90),(W-90,H-90)],fill=C['orange'],width=2)
    _tc.resize((1920, 1080), Image.LANCZOS).save(_tc_path)
    print(f'Title card: {_tc_path}')

# ── Eye-catching YouTube thumbnail ────────────────────────────────────────────
def _thumb_gen():
    W2, H2 = 1280, 720
    _t  = Image.new('RGB', (W2, H2), (18, 20, 35))
    _d2 = ImageDraw.Draw(_t)
    # Diagonal stripe texture
    for _xi in range(-H2, W2+H2, 24):
        _d2.line([(_xi,0),(_xi+H2,H2)], fill=(26,28,47), width=1)
    # Orange energy slash (right-side accent)
    _d2.polygon([
        (int(W2*0.53),0),(int(W2*0.69),0),
        (W2,int(H2*0.42)),(W2,int(H2*0.58))
    ], fill=(210,80,5))
    # White spotlight circle (right panel)
    _ccx, _ccy = int(W2*0.795), H2//2+22
    _d2.ellipse([_ccx-218,_ccy-218,_ccx+218,_ccy+218], fill=(250,250,254))
    # Large expressive stick figure
    _RNG.seed(77)
    _sc0_txt = SCENE_DATA[0]['text'] if SCENE_DATA else ''
    _ex3 = _expr(_sc0_txt) if _sc0_txt else 'happy'
    _sk3 = SKIN_TONES[0]
    _hr3 = max(int(220*0.24), 14)
    _fig_cy = _ccy - 72
    _figure(_d2, _ccx, _fig_cy, 220, _ex3, skin_col=_sk3)
    # Key-word badge above head (speech bubble style)
    _kw3 = _stat(_sc0_txt)[:16] if _sc0_txt else 'MIND'
    _kf3 = _font(30)
    _kb3 = _d2.textbbox((0,0), _kw3, font=_kf3)
    _kw3_w = _kb3[2]-_kb3[0]+32
    _kbx = _ccx - _kw3_w//2
    _kby = _fig_cy - _hr3 - 60
    _d2.rectangle([_kbx, _kby, _kbx+_kw3_w, _kby+46], fill=C['yellow'])
    _d2.polygon([(_ccx-9,_kby+46),(_ccx+9,_kby+46),(_ccx,_fig_cy-_hr3-6)],
                fill=C['yellow'])
    _d2.text((_kbx+16, _kby+8), _kw3, fill=C['black'], font=_kf3)
    # Episode title (left panel) — auto-size
    _ef3, _lh3 = _font(88), 106
    _el3 = _wrap(EPISODE_TITLE.upper(), _d2, _ef3, int(W2*0.50)-20)
    if len(_el3) > 3:
        _ef3, _lh3 = _font(72), 88
        _el3 = _wrap(EPISODE_TITLE.upper(), _d2, _ef3, int(W2*0.50)-20)
    if len(_el3) > 4:
        _ef3, _lh3 = _font(58), 72
        _el3 = _wrap(EPISODE_TITLE.upper(), _d2, _ef3, int(W2*0.50)-20)
    _ety = H2//2 - len(_el3)*_lh3//2 + 14
    for _eln in _el3[:4]:
        _ebb = _d2.textbbox((0,0), _eln, font=_ef3)
        _d2.text((64+3, _ety+3), _eln, fill=(0,0,0), font=_ef3)   # drop shadow
        _d2.text((64, _ety), _eln, fill=(255,255,255), font=_ef3)
        _ety += _lh3
    # Orange accent line under title
    _d2.rectangle([60, _ety+10, min(int(W2*0.50)-30, 60+420), _ety+16], fill=C['orange'])
    # UNLEARNED badge (top-left)
    _uf3 = _font(28); _utxt = 'UNLEARNED'
    _ub3 = _d2.textbbox((0,0), _utxt, font=_uf3)
    _uw3 = _ub3[2]-_ub3[0]+40; _uh3 = _ub3[3]-_ub3[1]+18
    _d2.rectangle([52, 34, 52+_uw3, 34+_uh3], fill=C['orange'])
    _d2.text((52+20, 34+9), _utxt, fill=C['white'], font=_uf3)
    # Bottom orange bar
    _d2.rectangle([0, H2-10, W2, H2], fill=C['orange'])
    _t.save(f'{WORK_DIR}/thumbnail.jpg', 'JPEG', quality=96)
    print(f'Thumbnail : {WORK_DIR}/thumbnail.jpg')

_thumb_gen()

# ── End card image ─────────────────────────────────────────────────────────────
_ec_path = f'{WORK_DIR}/end_card.png'
if not os.path.exists(_ec_path):
    _ec = Image.new('RGB',(W,H),(15,15,25))
    _ecd = ImageDraw.Draw(_ec)
    for _rr in range(30,240,40):
        _v = 35+_rr//6
        _ecd.ellipse([W//2-_rr,H//2-90-_rr,W//2+_rr,H//2-90+_rr],outline=(_v,_v,_v+18),width=1)
    # Bell body
    _bx2,_by2=W//2,H//2-80
    _ecd.ellipse([_bx2-44,_by2-22,_bx2+44,_by2+50],fill=C['gold'])
    _ecd.rectangle([_bx2-52,_by2+30,_bx2+52,_by2+54],fill=C['gold'])
    _ecd.ellipse([_bx2-11,_by2-44,_bx2+11,_by2-26],fill=C['gold'])
    _ecd.ellipse([_bx2-15,_by2+52,_bx2+15,_by2+72],fill=C['gold'])
    # SUBSCRIBE
    _sf2=_font(80); _stxt='SUBSCRIBE'
    _sbb=_ecd.textbbox((0,0),_stxt,font=_sf2)
    _ecd.text((W//2-(_sbb[2]-_sbb[0])//2,H//2+44),_stxt,fill=C['orange'],font=_sf2)
    # Channel name
    _cf3=_font(38); _ctxt='UNLEARNED'
    _cbb=_ecd.textbbox((0,0),_ctxt,font=_cf3)
    _ecd.text((W//2-(_cbb[2]-_cbb[0])//2,H//2+148),_ctxt,fill=C['white'],font=_cf3)
    _sf3=_font(24); _sub='Psychology  .  Ancient History  .  Behavioral Science'
    _sb3=_ecd.textbbox((0,0),_sub,font=_sf3)
    _ecd.text((W//2-(_sb3[2]-_sb3[0])//2,H//2+200),_sub,fill=(170,170,170),font=_sf3)
    _ec.resize((1920, 1080), Image.LANCZOS).save(_ec_path)
    print(f'End card  : {_ec_path}')

# Preview first 3 scenes in notebook
try:
    from IPython.display import display, Image as _IPImg
    print('\\nPreview (first 3 scenes):')
    for _sc in SCENE_DATA[:3]:
        display(_IPImg(_sc['image'], width=600))
except Exception:
    pass
print('Run Cell 5.')
""")

# ── CELL 6: Ken Burns + title/end card clips ───────────────────────────────────

CELL_MOTION = code("""\
# ── CELL 5: Ken Burns clips + title card clip + end card clip ─────────────────
import json, os, subprocess

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'CLIP_DIR'  not in dir(): CLIP_DIR  = f'{WORK_DIR}/clips'
os.makedirs(CLIP_DIR, exist_ok=True)
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_n=len(SCENE_DATA); _clips=[]; _TD=0.15
print(f'Building {_n} Ken Burns clips (7 directions, {int(_TD*1000)}ms white transitions)...')

for _i, _sc in enumerate(SCENE_DATA):
    _img=_sc['image']; _audio=_sc['audio']; _dur=_sc['duration']
    _clip=f'{CLIP_DIR}/clip_{_i:04d}.mp4'; _clips.append(_clip)
    if os.path.exists(_clip): print(f'  [{_i+1}/{_n}] cached'); continue

    _nf=max(int(_dur*30),2); _p=_i%7
    if   _p==0: _zp=f"z='min(zoom+0.0004,1.16)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"
    elif _p==1: _zp=f"z='min(zoom+0.0004,1.16)':x='0':y='0':d={_nf}"
    elif _p==2: _zp=f"z='min(zoom+0.0004,1.16)':x='iw-iw/zoom':y='ih-ih/zoom':d={_nf}"
    elif _p==3: _zp=f"z='if(lte(zoom,1.0),1.16,zoom-0.0004)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={_nf}"
    elif _p==4: _zp=f"z='min(zoom+0.0004,1.16)':x='iw-iw/zoom':y='0':d={_nf}"
    elif _p==5: _zp=f"z='min(zoom+0.0004,1.16)':x='0':y='ih-ih/zoom':d={_nf}"
    else:       _zp=f"z='if(lte(zoom,1.0),1.16,zoom-0.0004)':x='iw-iw/zoom':y='0':d={_nf}"

    _fo_st=max(0.0, _dur-_TD-0.05)
    _fi=f',fade=t=in:st=0:d={_TD}:color=white' if _i>0 else ''
    _fo=f',fade=t=out:st={_fo_st:.2f}:d={_TD}:color=white'
    _vf=f'[0:v]scale=1920:1080,zoompan={_zp}:s=1920x1080:fps=30{_fi}{_fo}[v]'

    _r=subprocess.run([
        'ffmpeg','-y','-loop','1','-i',_img,'-i',_audio,
        '-filter_complex',_vf,
        '-map','[v]','-map','1:a',
        '-c:v','libx264','-crf','17','-preset','fast','-profile:v','high','-level:v','4.0',
        '-g','60','-keyint_min','30',
        '-c:a','aac','-b:a','192k','-ac','2','-shortest','-pix_fmt','yuv420p',_clip,
    ], capture_output=True, text=True)
    if _r.returncode!=0:
        print(f'  Clip {_i} error:\\n{_r.stderr[-400:]}')
        raise RuntimeError(f'Clip {_i} failed')
    print(f'  [{_i+1}/{_n}] {_dur:.1f}s  KB-dir={_p}  clip_{_i:04d}.mp4')

import json as _jj
with open(f'{WORK_DIR}/clip_paths.json','w') as _f: _jj.dump(_clips,_f)

# ── Title card clip (3 s) ─────────────────────────────────────────────────────
TITLE_DUR = 3.0
_tc_img = f'{WORK_DIR}/title_card.png'
_tc_clip = f'{CLIP_DIR}/clip_title.mp4'
if os.path.exists(_tc_img) and not os.path.exists(_tc_clip):
    _r=subprocess.run([
        'ffmpeg','-y','-loop','1','-i',_tc_img,
        '-f','lavfi','-i','anullsrc=r=44100:cl=stereo',
        '-t',str(TITLE_DUR),
        '-vf',f'scale=1920:1080,fade=t=in:st=0:d=0.5:color=black,fade=t=out:st={TITLE_DUR-0.5:.1f}:d=0.5:color=white',
        '-c:v','libx264','-crf','17','-preset','fast','-profile:v','high','-level:v','4.0',
        '-g','60','-keyint_min','30',
        '-c:a','aac','-b:a','192k','-ac','2','-pix_fmt','yuv420p',_tc_clip,
    ],capture_output=True,text=True)
    if _r.returncode==0: print(f'Title card clip: {TITLE_DUR}s OK')
    else: print(f'Title clip error: {_r.stderr[-200:]}')

_td_f = f'{WORK_DIR}/title_dur.txt'
with open(_td_f,'w') as _f:
    _f.write(str(TITLE_DUR) if os.path.exists(_tc_clip) else '0.0')

# ── End card clip (4 s) ───────────────────────────────────────────────────────
END_DUR = 20.0
_ec_img = f'{WORK_DIR}/end_card.png'
_ec_clip = f'{CLIP_DIR}/clip_end.mp4'
if os.path.exists(_ec_img) and not os.path.exists(_ec_clip):
    _r=subprocess.run([
        'ffmpeg','-y','-loop','1','-i',_ec_img,
        '-f','lavfi','-i','anullsrc=r=44100:cl=stereo',
        '-t',str(END_DUR),
        '-vf',f'scale=1920:1080,fade=t=in:st=0:d=0.5:color=white,fade=t=out:st={END_DUR-0.7:.1f}:d=0.7:color=black',
        '-c:v','libx264','-crf','17','-preset','fast','-profile:v','high','-level:v','4.0',
        '-g','60','-keyint_min','30',
        '-c:a','aac','-b:a','192k','-ac','2','-pix_fmt','yuv420p',_ec_clip,
    ],capture_output=True,text=True)
    if _r.returncode==0: print(f'End card clip: {END_DUR}s OK')
    else: print(f'End clip error: {_r.stderr[-200:]}')

_ed_f = f'{WORK_DIR}/end_dur.txt'
with open(_ed_f,'w') as _f:
    _f.write(str(END_DUR) if os.path.exists(_ec_clip) else '0.0')

print(f'\\n{_n} scene clips + title/end cards done. Run Cell 6.')
""")

# ── CELL 7: Karplus-Strong Music v6 (+ echo reverb) ───────────────────────────

CELL_MUSIC = code("""\
# ── CELL 6: Music v6 — chunk-KS + echo reverb, 16-bar + melody ───────────────
import numpy as np, wave, os, subprocess, json

if 'WORK_DIR'  not in dir(): WORK_DIR  = '/content/unlearned'
if 'SCENE_DATA' not in dir():
    with open(f'{WORK_DIR}/scene_data.json') as _f: SCENE_DATA = json.load(_f)

_td_f = f'{WORK_DIR}/title_dur.txt'
_ed_f = f'{WORK_DIR}/end_dur.txt'
_title_d = float(open(_td_f).read().strip()) if os.path.exists(_td_f) else 0.0
_end_d   = float(open(_ed_f).read().strip()) if os.path.exists(_ed_f) else 0.0
_total_dur = sum(s['duration'] for s in SCENE_DATA) + _title_d + _end_d
_music_dur = _total_dur + 12.0
SR         = 44100
BPM        = 112.0
BEAT       = 60.0/BPM
HALF_BEAT  = BEAT/2
LOOP_BARS  = 16
LOOP_SAMP  = int(SR * LOOP_BARS * 4 * BEAT)

np.random.seed(42)

def _ks(freq, dur_sec, damping=0.9965):
    n      = int(SR * dur_sec)
    period = max(int(round(SR / freq)), 1)
    buf    = np.random.uniform(-0.5, 0.5, period).astype(np.float32)
    n_cks  = n // period + 2
    chunks = []
    for _ in range(n_cks):
        chunks.append(buf.copy())
        buf = damping * 0.5 * (buf + np.roll(buf, -1))
    return np.concatenate(chunks)[:n]

CHORDS_A = [
    [261.63,329.63,392.00],
    [196.00,246.94,293.66],
    [220.00,261.63,329.63],
    [174.61,220.00,261.63],
]*2
CHORDS_B = [
    [220.00,261.63,329.63],
    [174.61,220.00,261.63],
    [261.63,329.63,392.00],
    [196.00,246.94,293.66],
]*2

ARP_A=[(0,0.34),(1,0.27),(2,0.24),(0,0.19)]
ARP_B=[(2,0.30),(1,0.26),(0,0.22),(2,0.18)]

PENTA_A=[523.25,587.33,659.25,783.99,880.00,783.99,659.25,587.33]
PENTA_B=[880.00,783.99,659.25,587.33,523.25,587.33,659.25,783.99]
MELODY_VOL=0.09

print(f'Generating 16-bar KS loop + echo reverb...')
mix = np.zeros(LOOP_SAMP, dtype=np.float32)

for bar_idx in range(LOOP_BARS):
    is_b    = bar_idx >= LOOP_BARS//2
    chord   = CHORDS_B[bar_idx-LOOP_BARS//2] if is_b else CHORDS_A[bar_idx]
    arp     = ARP_B if is_b else ARP_A
    melody  = PENTA_B if is_b else PENTA_A
    root,third,fifth = chord

    for beat_idx,(ni,vol) in enumerate(arp):
        freq = [root,third,fifth][ni]
        samp_st = int((bar_idx*4+beat_idx)*BEAT*SR)
        note    = _ks(freq, BEAT*0.88)*vol
        end     = min(samp_st+len(note), LOOP_SAMP)
        mix[samp_st:end] += note[:end-samp_st]

    bvol = 0.20 if is_b else 0.22
    bass = _ks(root/2, BEAT*1.6, damping=0.999)*bvol
    bst  = int(bar_idx*4*BEAT*SR)
    end  = min(bst+len(bass), LOOP_SAMP)
    mix[bst:end] += bass[:end-bst]

    for ni,mel_freq in enumerate(melody):
        samp_st=int((bar_idx*8+ni)*HALF_BEAT*SR)
        note=_ks(mel_freq, HALF_BEAT*0.76, damping=0.9945)*MELODY_VOL
        end=min(samp_st+len(note), LOOP_SAMP)
        mix[samp_st:end] += note[:end-samp_st]

print('KS loop done.')

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
    '-af',f'afade=t=in:st=0:d=2,aecho=0.85:0.90:40:0.35,afade=t=out:st={_fade_st:.1f}:d=7',
    '-q:a','4',MUSIC_MP3,
], capture_output=True, check=True)
os.remove(_loop_wav)

print(f'Music: 16-bar KS + echo reverb  {_music_dur:.0f}s  ({MUSIC_MP3})')
print('Run Cell 7.')
""")

# ── CELL 8: Assemble (with title/end card clips) ───────────────────────────────

CELL_ASSEMBLE = code("""\
# ── CELL 7: Assemble — title card + scene clips + end card ────────────────────
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
                   if fn.startswith('clip_') and fn.endswith('.mp4')
                   and 'title' not in fn and 'end' not in fn])

_tc_clip = f'{CLIP_DIR}/clip_title.mp4'
_ec_clip = f'{CLIP_DIR}/clip_end.mp4'
_all_clips = []
if os.path.exists(_tc_clip): _all_clips.append(_tc_clip)
_all_clips.extend(_clips)
if os.path.exists(_ec_clip): _all_clips.append(_ec_clip)

_list=f'{WORK_DIR}/clip_list.txt'
with open(_list,'w') as _f:
    for _c in _all_clips: _f.write(f"file '{_c}'\\n")

RAW_VIDEO=f'{WORK_DIR}/video_raw.mp4'
_extras = (1 if os.path.exists(_tc_clip) else 0) + (1 if os.path.exists(_ec_clip) else 0)
print(f'Concatenating {len(_all_clips)} clips ({len(_clips)} scenes + {_extras} cards)...')
_r=subprocess.run(['ffmpeg','-y','-f','concat','-safe','0',
                   '-i',_list,'-c','copy',RAW_VIDEO],
                  capture_output=True, text=True)
if _r.returncode!=0:
    print(_r.stderr[-600:]); raise RuntimeError('Concat failed')

_mb=os.path.getsize(RAW_VIDEO)/1_048_576
_total=sum(s['duration'] for s in SCENE_DATA)
print(f'Raw video: {_total:.0f}s scenes  {_mb:.1f} MB')
print('Run Cell 8.')
""")

# ── CELL 9: ASS Captions (with title card timing offset) ──────────────────────

CELL_CAPTIONS = code("""\
# ── CELL 8: Yellow ASS captions — 4-word phrases + title card offset ──────────
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

# Read title card offset so captions start after the title card
_td_f = f'{WORK_DIR}/title_dur.txt'
_title_off = float(open(_td_f).read().strip()) if os.path.exists(_td_f) else 0.0

_all=[]; _offset=_title_off
for _sc in SCENE_DATA:
    _entries=_parse_vtt(_sc.get('vtt',''), _offset)
    if _entries:
        _avg=sum(len(e[2].split()) for e in _entries)/len(_entries)
        if _avg<=2.5:
            _entries=_group_words(_entries, n=4)
        _all.extend(_entries)
    else:
        _all.append((_offset, _offset+_sc['duration'], _sc['text']))
    _offset+=_sc['duration']

ASS_HEADER='''[Script Info]
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,42,&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3.5,0,2,10,10,48,1

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

print(f'Captions: {len(_all)} entries (offset={_title_off:.1f}s, font-42, yellow, 1080p)')

_ass_esc=_ass_path.replace('\\\\','/').replace(':','\\\\:')
CAPTIONED_VIDEO=f'{WORK_DIR}/video_captioned.mp4'

_r=subprocess.run([
    'ffmpeg','-y','-i',RAW_VIDEO,
    '-vf',f"ass='{_ass_esc}'",
    '-c:a','copy','-c:v','libx264','-crf','17','-preset','fast','-profile:v','high','-level:v','4.0',
    '-g','60','-keyint_min','30',
    CAPTIONED_VIDEO,
], capture_output=True, text=True)

if _r.returncode!=0:
    print('ASS burn failed — trying SRT subtitles filter...')
    _srt_esc=_srt_path.replace('\\\\','/').replace(':','\\\\:')
    _style="FontName=Arial,FontSize=42,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=3.5,Bold=1,Alignment=2,MarginV=48"
    _r2=subprocess.run([
        'ffmpeg','-y','-i',RAW_VIDEO,
        '-vf',f"subtitles='{_srt_esc}':force_style='{_style}'",
        '-c:a','copy','-c:v','libx264','-crf','17','-preset','fast','-profile:v','high','-level:v','4.0',
        '-g','60','-keyint_min','30',
        CAPTIONED_VIDEO,
    ], capture_output=True, text=True)
    if _r2.returncode!=0:
        print('Both sub filters failed — copying without burn.')
        print('Upload captions.srt to YouTube Studio manually.')
        import shutil; shutil.copy2(RAW_VIDEO, CAPTIONED_VIDEO)
    else:
        print('SRT fallback OK.')
else:
    print('Captions burned: yellow / font-42 / 3.5px outline / 1080p.')

print('Run Cell 9.')
""")

# ── CELL 10: Mix ──────────────────────────────────────────────────────────────

CELL_MIX = code("""\
# ── CELL 9: Mix music + loudnorm + white master fade ─────────────────────────
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

_td_f = f'{WORK_DIR}/title_dur.txt'
_ed_f = f'{WORK_DIR}/end_dur.txt'
_title_d = float(open(_td_f).read().strip()) if os.path.exists(_td_f) else 0.0
_end_d   = float(open(_ed_f).read().strip()) if os.path.exists(_ed_f) else 0.0
_total = sum(s['duration'] for s in SCENE_DATA) + _title_d + _end_d
_fo_st = max(0, _total-2.5)
_safe  = re.sub(r'[^\\w\\s-]+','',EPISODE_TITLE).strip().replace(' ','_')
FINAL_VIDEO=f'{WORK_DIR}/UNLEARNED_{_safe}.mp4'

print(f'Total duration: {_total:.1f}s ({_total/60:.1f} min)')
print(f'Mixing: loudnorm -14 LUFS · 192k AAC stereo · music {int(MUSIC_VOL*100)}%')
print(f'Master fade: in 0.8s white | out 2.5s white')

_AF = (f'[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,'
       f'aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo[vo_n];'
       f'[1:a]volume={MUSIC_VOL}[mu];'
       f'[vo_n][mu]amix=inputs=2:duration=first[a_mix];'
       f'[a_mix]afade=t=in:st=0:d=0.8,afade=t=out:st={_fo_st:.1f}:d=2.5[aout]')

_r=subprocess.run([
    'ffmpeg','-y',
    '-i',CAPTIONED_VIDEO,'-i',MUSIC_MP3,
    '-filter_complex',_AF,
    '-map','0:v','-map','[aout]',
    '-vf',f'fade=t=in:st=0:d=0.8:color=white,fade=t=out:st={_fo_st:.1f}:d=2.5:color=white',
    '-c:v','libx264','-crf','17','-preset','fast','-profile:v','high','-level:v','4.0',
    '-g','60','-keyint_min','30',
    '-c:a','aac','-b:a','192k','-ac','2','-shortest',
    FINAL_VIDEO,
], capture_output=True, text=True)

if _r.returncode!=0:
    print('Attempt 1 failed — trying copy video...')
    _AF2 = (f'[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,'
            f'aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo[vo_n];'
            f'[1:a]volume={MUSIC_VOL}[mu];'
            f'[vo_n][mu]amix=inputs=2:duration=first[aout]')
    _r2=subprocess.run([
        'ffmpeg','-y','-i',CAPTIONED_VIDEO,'-i',MUSIC_MP3,
        '-filter_complex',_AF2,
        '-map','0:v','-map','[aout]',
        '-c:v','copy','-c:a','aac','-b:a','192k','-ac','2','-shortest',
        FINAL_VIDEO,
    ], capture_output=True, text=True)
    if _r2.returncode!=0:
        print('Attempt 2 failed — trying simple volume mix...')
        _AF3 = (f'[0:a]volume=2.0,aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo[vo_n];'
                f'[1:a]volume={MUSIC_VOL}[mu];'
                f'[vo_n][mu]amix=inputs=2:duration=first[aout]')
        _r3=subprocess.run([
            'ffmpeg','-y','-i',CAPTIONED_VIDEO,'-i',MUSIC_MP3,
            '-filter_complex',_AF3,
            '-map','0:v','-map','[aout]',
            '-c:v','copy','-c:a','aac','-b:a','128k','-shortest',
            FINAL_VIDEO,
        ], capture_output=True, text=True)
        if _r3.returncode!=0:
            print('Attempt 3 failed — saving video without background music...')
            import shutil as _sh
            _sh.copy2(CAPTIONED_VIDEO, FINAL_VIDEO)
            print('Video saved (no background music — all other features intact)')

_mb=os.path.getsize(FINAL_VIDEO)/1_048_576
print(f'\\nFinal video : {FINAL_VIDEO}')
print(f'Size        : {_mb:.1f} MB  |  Duration: {_total:.0f}s ({_total/60:.1f} min)')
print('Run Cell 10 to download.')
""")

# ── CELL 11: Download (all assets) ────────────────────────────────────────────

CELL_DOWNLOAD = code("""\
# ── CELL 10: Download — video + captions + thumbnail + YT description/chapters
import os, re, json
from google.colab import files as _gcf

if 'WORK_DIR' not in dir(): WORK_DIR='/content/unlearned'
if 'FINAL_VIDEO' not in dir():
    _tp=f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE=open(_tp).read().strip() if os.path.exists(_tp) else 'Episode'
    _safe=re.sub(r'[^\\w\\s-]+','',EPISODE_TITLE).strip().replace(' ','_')
    FINAL_VIDEO=f'{WORK_DIR}/UNLEARNED_{_safe}.mp4'
if 'EPISODE_TITLE' not in dir():
    _tp=f'{WORK_DIR}/episode_title.txt'
    EPISODE_TITLE=open(_tp).read().strip() if os.path.exists(_tp) else 'Episode'
if 'SCENE_DATA' not in dir():
    _jp=f'{WORK_DIR}/scene_data.json'
    if os.path.exists(_jp):
        with open(_jp) as _f: SCENE_DATA=json.load(_f)
    else:
        SCENE_DATA=[]

if not os.path.exists(FINAL_VIDEO):
    raise RuntimeError(f'Video not found: {FINAL_VIDEO}  — run Cell 9 first.')

# ── Video ─────────────────────────────────────────────────────────────────────
_mb=os.path.getsize(FINAL_VIDEO)/1_048_576
print(f'Downloading: {os.path.basename(FINAL_VIDEO)}  ({_mb:.1f} MB)')
_gcf.download(FINAL_VIDEO)

# ── Captions ──────────────────────────────────────────────────────────────────
for _cf in [f'{WORK_DIR}/captions.srt', f'{WORK_DIR}/captions.ass']:
    if os.path.exists(_cf):
        print(f'Downloading: {os.path.basename(_cf)}')
        _gcf.download(_cf)

# ── Thumbnail ─────────────────────────────────────────────────────────────────
_thumb = f'{WORK_DIR}/thumbnail.jpg'
if os.path.exists(_thumb):
    print('Downloading: thumbnail.jpg')
    _gcf.download(_thumb)

# ── YouTube chapters ──────────────────────────────────────────────────────────
_td_f = f'{WORK_DIR}/title_dur.txt'
_title_off = float(open(_td_f).read().strip()) if os.path.exists(_td_f) else 0.0
_chap_path = f'{WORK_DIR}/yt_chapters.txt'
with open(_chap_path,'w',encoding='utf-8') as _cf2:
    _cf2.write('0:00 Introduction\\n')
    _off = _title_off
    for _si, _s in enumerate(SCENE_DATA):
        _ts = int(_off)
        _mm, _ss = _ts//60, _ts%60
        _snip = re.sub(r'[^\\w\\s]','',_s['text'])[:38].strip()
        _cf2.write(f'{_mm}:{_ss:02d} {_snip}\\n')
        _off += _s['duration']
print('Downloading: yt_chapters.txt')
_gcf.download(_chap_path)

# ── YouTube description ───────────────────────────────────────────────────────
_desc_path = f'{WORK_DIR}/yt_description.txt'
_intro = ' '.join(_s['text'] for _s in SCENE_DATA[:2])[:250] if SCENE_DATA else ''
_ch_lines = open(_chap_path,'r',encoding='utf-8').read() if os.path.exists(_chap_path) else ''
with open(_desc_path,'w',encoding='utf-8') as _df:
    _df.write(EPISODE_TITLE + '\\n\\n')
    _df.write(_intro + '\\n\\n')
    _df.write('=' * 48 + '\\n')
    _df.write('UNLEARNED — Psychology, Ancient History, Behavioral Science\\n\\n')
    _df.write('CHAPTERS\\n')
    _df.write(_ch_lines + '\\n')
    _df.write('=' * 48 + '\\n\\n')
    _df.write('#psychology #ancienthistory #behavioralscience #UNLEARNED\\n')
    _df.write('#mindset #history #brainscience #ancientworld #humanpsychology\\n\\n')
    _df.write('SUBSCRIBE for more: @unlearnedchannel\\n')
print('Downloading: yt_description.txt')
_gcf.download(_desc_path)

# ── Summary ───────────────────────────────────────────────────────────────────
if SCENE_DATA:
    _td_e = f'{WORK_DIR}/end_dur.txt'
    _end_d = float(open(_td_e).read().strip()) if os.path.exists(_td_e) else 0.0
    _total = sum(s['duration'] for s in SCENE_DATA) + _title_off + _end_d
    print(f'\\nEpisode  : {EPISODE_TITLE}')
    print(f'Duration : {_total:.0f}s ({_total/60:.1f} min)')
    print(f'Scenes   : {len(SCENE_DATA)}')

print('''
Upload checklist:
  1. UNLEARNED_*.mp4      — main video
  2. thumbnail.jpg        — YouTube thumbnail (upload in Studio)
  3. captions.srt         — YouTube Studio > Subtitles (word-synced)
  4. yt_description.txt   — paste into video description
  5. yt_chapters.txt      — chapters are already in the description
  Done!
''')
""")

# ── CELL 12: Save to Google Drive ─────────────────────────────────────────────

CELL_DRIVE = code("""\
# ── CELL 11: Save all files to Google Drive (for phone users) ─────────────────
from google.colab import drive
import shutil, os, glob

print('Connecting to Google Drive...')
drive.mount('/content/drive')

if 'WORK_DIR' not in dir(): WORK_DIR = '/content/unlearned'

_dest = '/content/drive/MyDrive/UNLEARNED_VIDEO'
os.makedirs(_dest, exist_ok=True)
print(f'Saving to Google Drive → UNLEARNED_VIDEO folder...\\n')

_saved = []
for _f in glob.glob(f'{WORK_DIR}/UNLEARNED_*.mp4'):
    shutil.copy2(_f, _dest)
    _mb = os.path.getsize(_f) / 1_048_576
    print(f'  VIDEO   : {os.path.basename(_f)}  ({_mb:.1f} MB)')
    _saved.append(_f)

for _name in ['thumbnail.jpg','captions.srt','captions.ass',
              'yt_description.txt','yt_chapters.txt']:
    _src = f'{WORK_DIR}/{_name}'
    if os.path.exists(_src):
        shutil.copy2(_src, _dest)
        print(f'  {_name}')
        _saved.append(_src)

print(f'\\nDone! {len(_saved)} files saved.')
print('Open Google Drive app on your phone → UNLEARNED_VIDEO folder to download.')
""")

# ── Assemble notebook ──────────────────────────────────────────────────────────

CELLS = [
    CELL_TITLE, CELL_INSTALL, CELL_SETUP, CELL_VOICE,
    CELL_DOODLE, CELL_MOTION, CELL_MUSIC, CELL_ASSEMBLE,
    CELL_CAPTIONS, CELL_MIX, CELL_DOWNLOAD, CELL_DRIVE,
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
