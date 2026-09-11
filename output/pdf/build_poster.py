"""Reproducible A2 plate. Source claims are indexed in SOURCE_MAP.md.

The official icon is embedded unchanged. All other marks and type are vector.
Coordinates use points from the top edge so the layout reads like the plate.
"""
from pathlib import Path
import math
import random
import json
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNTIME = Path('/Users/macbook/.cache/codex-runtimes/codex-primary-runtime/dependencies')
FONTS = RUNTIME / 'native/poppler/poppler/fonts'
SANS = RUNTIME / 'node/node_modules/pdfjs-dist/standard_fonts'
for name, path in {
    'Sans': SANS / 'LiberationSans-Regular.ttf',
    'Bold': SANS / 'LiberationSans-Bold.ttf',
    'Italic': SANS / 'LiberationSans-Italic.ttf',
    'Mono': FONTS / 'SourceCodePro-Regular.ttf',
    'Serif': Path('/System/Library/Fonts/Supplemental/Georgia.ttf'),
    'SerifI': Path('/System/Library/Fonts/Supplemental/Georgia Italic.ttf'),
}.items():
    pdfmetrics.registerFont(TTFont(name, str(path)))
pdfmetrics.registerFontFamily('Sans', normal='Sans', bold='Bold', italic='Italic', boldItalic='Bold')

W, H = 420 / 25.4 * 72, 594 / 25.4 * 72
BG = '#06080b'
INK = '#eee4d0'
BODY = '#d1cfc8'
DIM = '#a8aaa9'
GOLD = '#c5a35a'
ROSE = '#e5aa9f'
VIOLET = '#b7a4d3'
LINE = '#45413d'
GREEN = '#b7c6a2'
C = canvas.Canvas(str(OUT / 'VESPER_SYSTEM_BLUEPRINT_MASTER.pdf'), pagesize=(W,H), pageCompression=1,
                  initialFontName='Sans', initialFontSize=10)
C.setTitle('VESPER | A persistent, distributed operating presence')
C.setAuthor('VESPER project / architecture plate')
C.setSubject('Source-grounded system architecture; repository 7cddca1, 11 September 2026')
C.setCreator('Vector composition with ReportLab; original VESPER icon embedded unchanged')
checks = []

def rect(x,y,w,h,fill=None,stroke=None,lw=.6):
    C.setLineWidth(lw)
    if fill: C.setFillColor(HexColor(fill))
    if stroke: C.setStrokeColor(HexColor(stroke))
    C.rect(x,H-y-h,w,h,fill=int(bool(fill)),stroke=int(bool(stroke)))

def line(x1,y1,x2,y2,col=LINE,lw=.6,dash=None):
    C.saveState(); C.setStrokeColor(HexColor(col)); C.setLineWidth(lw)
    if dash: C.setDash(*dash)
    C.line(x1,H-y1,x2,H-y2); C.restoreState()

def txt(x,y,s,size=10,font='Sans',col=BODY,align='left',tracking=None):
    C.saveState()
    C.setFillColor(HexColor(col)); C.setFont(font,size)
    if tracking is not None:
        t=C.beginText(x,H-y);t.setFont(font,size);t.setCharSpace(tracking);t.textOut(s);C.drawText(t)
    elif align=='center': C.drawCentredString(x,H-y,s)
    elif align=='right': C.drawRightString(x,H-y,s)
    else: C.drawString(x,H-y,s)
    C.restoreState()

def para(x,y,w,s,size=10.3,leading=14,col=BODY,font='Sans',limit=None):
    p=Paragraph(s,ParagraphStyle('p',fontName=font,fontSize=size,leading=leading,textColor=HexColor(col),spaceAfter=0))
    _,h=p.wrap(w,2000)
    if limit is not None and h>limit+.01: raise ValueError(f'Overflow {h}>{limit}: {s[:80]}')
    p.drawOn(C,x,H-y-h)
    checks.append({'text':s,'x':x,'y':y,'w':w,'h':h,'size':size})
    return y+h

def circ(x,y,r,col=LINE,lw=.5,fill=None):
    C.setStrokeColor(HexColor(col)); C.setLineWidth(lw)
    if fill: C.setFillColor(HexColor(fill))
    C.circle(x,H-y,r,stroke=1,fill=int(bool(fill)))

def arrow(points,col=GOLD,lw=.85,dash=None):
    for a,b in zip(points,points[1:]):line(*a,*b,col,lw,dash)
    a,b=points[-2:]; angle=math.atan2(b[1]-a[1],b[0]-a[0]); r=4.7
    for d in [-.48,.48]:
        line(b[0],b[1],b[0]-r*math.cos(angle+d),b[1]-r*math.sin(angle+d),col,lw)

def label(x,y,s,col=GOLD):txt(x,y,s,8,'Mono',col,tracking=.9)

def box(x,y,w,num,title,body,source,col=GOLD):
    rect(x,y,w,70,'#0d1014',LINE)
    rect(x,y,2,70,col)
    txt(x+14,y+19,num,8,'Mono',col)
    txt(x+39,y+20,title,13,'Serif',INK)
    para(x+14,y+29,w-28,body,10,12.6,limit=27)
    txt(x+14,y+62,source,7.5,'Mono',DIM)

def panel(x,y,w,num,title,source,col=GOLD):
    line(x,y,x+w,y,col,.7)
    txt(x,y+22,num,9,'Mono',col)
    txt(x+27,y+23,title,18,'Serif',INK)
    txt(x,y+40,source,7.6,'Mono',DIM)
    return y+53

rect(0,0,W,H,BG)
# Quiet drafting grid: limited to the astronomical field, not behind body copy.
for x in range(45,int(W)-40,25):line(x,40,x,774,'#10151b',.22)
for y in range(40,775,25):line(45,y,W-45,y,'#10151b',.22)
rng=random.Random(6026)
for i in range(180):
    x=rng.uniform(48,W-48); y=rng.uniform(46,766)
    if 240<y<308:continue
    r=rng.choice([.32,.4,.5,.7,1.0])
    circ(x,y,r,'#515058',.2,fill='#515058')
for x,y in [(65,185),(1080,125),(405,596),(796,345),(727,700)]:
    line(x-4,y,x+4,y,GOLD,.5);line(x,y-4,x,y+4,GOLD,.5)
rect(35,35,W-70,H-70,None,'#595044',.65)
rect(40,40,W-80,H-80,None,'#282b2f',.35)
for x in [35,W-35]:
    for y in [35,H-35]:
        line(x-6,y,x+6,y,GOLD,.6);line(x,y-6,x,y+6,GOLD,.6)

label(57,66,'VESPER / SYSTEM ATLAS')
txt(W-57,66,'PLATE 01   /   SOURCE REV. 7cddca1   /   2026-09-11',8,'Mono',DIM,'right')
title='VESPER'
tw=pdfmetrics.stringWidth(title,'Serif',83)+5*12
txt((W-tw)/2,158,title,83,'Serif',INK,tracking=12)
txt(W/2,190,'A PERSISTENT, DISTRIBUTED OPERATING PRESENCE',12,'Sans',GOLD,'center')
txt(W/2,219,'The model may change. The record of what matters must endure.',16,'SerifI',INK,'center')
line(57,242,W-57,242,LINE)
para(57,253,610,'A personal assistant being engineered around durable state, evidence, bounded agency and continuity across replaceable models and devices. This plate maps the current source; deployment and hardware validation remain separate claims.',10.4,14,limit=45)
for x,s,col in [(715,'CURRENT',GREEN),(826,'EXPERIMENTAL',ROSE),(976,'PLANNED',VIOLET)]:
    circ(x,259,2.4,col,.5,fill=col);txt(x+9,262,s,8,'Mono',col)
para(711,271,420,'CURRENT = implemented source. EXPERIMENTAL = measurement in progress. PLANNED = specified or proposed, not established in operation.',8.8,11.8,col=DIM,limit=25)

# Hero. The official mark is a visual anchor, never a callable module.
label(57,319,'I  /  THE LIVE TURN')
txt(W-57,319,'Solid arrows: calls / results     Orbit lines: visual metaphor',7.7,'Mono',DIM,'right')
cx,cy=W/2,542
for rx,ry,ang in [(174,174,0),(202,111,33),(224,145,-31),(251,183,0)]:
    C.saveState();C.translate(cx,H-cy);C.rotate(ang);C.setStrokeColor(HexColor('#625040' if rx==174 else '#302c32'));C.setLineWidth(.6)
    C.ellipse(-rx,-ry,rx,ry,stroke=1,fill=0);C.restoreState()
for a in range(0,360,5):
    r=178 if a%30 else 175;r2=183 if a%30 else 188
    t=math.radians(a);line(cx+r*math.cos(t),cy+r*math.sin(t),cx+r2*math.cos(t),cy+r2*math.sin(t),'#77634b' if a%30==0 else '#353137',.5)
for a,col in [(34,GOLD),(147,ROSE),(231,VIOLET),(308,GREEN)]:
    t=math.radians(a);circ(cx+174*math.cos(t),cy+174*math.sin(t),3,col,.7,fill=BG)

rect(cx-161,337,322,43,'#111419',LINE)
txt(cx,355,'OWNER INPUT / INTAKE',11,'Bold',INK,'center')
txt(cx,371,'typed text + final, confidence-gated speech',9,'Sans',DIM,'center')
arrow([(cx+161,358),(968,358),(968,409)],ROSE)
label(1000,388,'REQUEST',ROSE)
arrow([(829,422),(804,422),(804,393),(206,393),(206,409)],GOLD)
rect(467,385,257,16,BG)
txt(cx,396,'no action proposed: answer()',8,'Mono',GOLD,'center')

C.drawImage(str(ROOT/'docs/design/assets/vesper-icon.png'),cx-121, H-(421+242),242,242,mask=None)
txt(cx,691,'VESPER',21,'Serif',INK,'center',tracking=None)
txt(cx,708,'IDENTITY IS THE SYSTEM, NOT THE MODEL',7.2,'Mono',GOLD,'center')
txt(cx,726,'Orchestrated by vesper_runtime.py',8,'Mono',DIM,'center')

left,right,bw=69,829,292
box(left,409,bw,'01','Choose the model','Difficulty chooses a profile; interactive turns prefer measured latency.','chooser.py  /  router.py')
box(left,493,bw,'02','Assemble the situation','Persona, recent dialogue, live mode and selected facts beside the question.','blocks.py  /  context.py')
box(left,577,bw,'03','Cross the gateway','Privacy, credential redaction and cost rules precede provider attempts.','gateway.py  /  routing/supply.py')
box(left,661,bw,'04','Answer and retain','Reply to the owner; capture utterances asynchronously and record misses.','answer()  /  updater.py')
box(right,409,bw,'01','Propose one next step','A model names a known capability and arguments; the proposal grants no authority.','intent.py  /  actor.py',ROSE)
box(right,493,bw,'02','Resolve permission','Evaluate scoped grants, argument-sensitive levels and ceilings; ask when required.','authorize.py  /  confirm.py',ROSE)
box(right,577,bw,'03','Execute with a record','Re-check authority; checkpoint file changes and record external effects before acting.','executor.py  /  checkpoint.py',ROSE)
box(right,661,bw,'04','Observe and verify','Feed observations to the next step. Check effects where an independent verifier exists.','actor.py  /  capabilities.py',ROSE)
for x,col in [(215,GOLD),(975,ROSE)]:
    for y in [479,563,647]:arrow([(x,y),(x,y+14)],col)
arrow([(1121,696),(1136,696),(1136,443),(1121,443)],ROSE,.7)
txt(1144,610,'',8)
txt(cx,751,'ACT LOOP: 6 STEPS MAX  /  3 CONSECUTIVE REFUSALS STOP THE TURN',7.8,'Mono',DIM,'center')
arrow([(215,731),(215,773),(414,773)],GOLD)
arrow([(975,731),(975,773),(777,773)],ROSE)
rect(414,758,363,32,'#171719',LINE)
txt(cx,778,'TRANSCRIPT + SPEECH + EXPLANATION SURFACES',9,'Bold',INK,'center')
txt(70,795,'No generic shell-effect verifier: an unchecked result is reported as such.',8.5,'Italic',DIM)

# Educational lens, seven intentionally compact, aligned definitions.
line(57,815,W-57,815,GOLD,.8)
label(57,835,'II  /  WHAT MAKES AN ASSISTANT')
txt(W-57,835,'A composition of mechanisms; no claim of consciousness.',9,'Italic',DIM,'right')
defs=[
('MODEL','A replaceable inference service. It generates answers or proposes steps; its output is not permission.'),
('MEMORY','Stored facts and their provenance. The log preserves history; the graph makes it selectable.'),
('CONTEXT','The bounded material supplied now: rules, evidence, recent dialogue and the current request.'),
('TOOLS','Concrete adapters that read or change the world. Arguments determine their required authority.'),
('AGENT','A bounded task process with a purpose and tool scope. Advice returns with external-content taint.'),
('INTERFACE','The native island and home, speech and typed scenes. They expose state and receive the owner.'),
('ORCHESTRATOR','The runtime joins intake, models, memory and actions, while a separate loop evaluates world state.'),
]
dw=(W-114)/7
for i,(head,body) in enumerate(defs):
    x=57+i*dw
    if i:line(x-8,852,x-8,930,LINE,.4)
    txt(x,860,head,8.3,'Mono',GOLD)
    para(x,871,dw-19,body,9.7,12.5,limit=63)

# Three dense plates. Each has a distinct engineering claim and a real diagram.
xs=[57,426,795]; pw=338
y=panel(xs[0],954,pw,'01','Memory with a source','memory.py / blocks.py / knowledge_map.py')
para(xs[0],y,pw,'<b>L3</b> is the append-only event log. A fact is written there first; its returned sequence becomes the provenance pointer in <b>L2</b>, a SQLite graph of entities, facts and edges. <b>L1</b> is the context rendered for a turn.',10.3,13.8,limit=70)
for i,(a,b) in enumerate([('L3','EVENT LOG'),('L2','FACT GRAPH'),('L1','TURN CONTEXT')]):
    x=xs[0]+i*116;rect(x,1080,104,37,'#111419',LINE)
    txt(x+8,1095,a,10,'Bold',GOLD);txt(x+8,1109,b,7.1,'Mono',DIM)
    if i<2:arrow([(x+104,1098),(x+115,1098)],GOLD,.6)
para(xs[0],1128,pw,'Selection uses <b>FTS5 + a graph walk bounded at depth 3</b>, then authority and recency. Block A carries a stable persona and index; block B places up to five relevant facts next to the question. Budget cuts and unresolved source pointers are reported.',10.3,13.8,limit=70)
para(xs[0],1208,pw,'The knowledge map navigates to hash-checked source spans; a map summary is not evidence. Compaction reprojects from L3. Erasing L2 does not destroy L3 history. No embedding store is used.',10.1,13.6,limit=56)

y=panel(xs[1],954,pw,'02','Authority before effect','authorize.py / taint.py / permission_mode.py',ROSE)
para(xs[1],y,pw,'A capability name is insufficient: the same command tool can inspect a directory or destroy it. VESPER resolves authority from the actual arguments and the source of the instruction.',10.3,13.8,limit=56)
rect(xs[1],1069,pw,42,'#171416',LINE)
txt(xs[1]+pw/2,1096,'E = min(G, D, C, M, A)',17,'Serif',ROSE,'center')
para(xs[1],1122,pw,'<b>E</b>: effective level. <b>G</b>: grant maximum. <b>D</b>: declared argument level. <b>C</b>: context-trust ceiling. <b>M</b>: owner-mode ceiling. <b>A</b>: authorization-strength ceiling. Levels are ordered L0 through L5.',10.1,13.6,limit=56)
para(xs[1],1184,pw,'This is an upper bound, not the whole permit: expiry, target scope, lease epoch, required level and further boundary checks still apply. Retrieved content stays tainted through summaries and caches. An advisor may add STOP; it cannot manufacture consent.',10.3,13.8,limit=70)

y=panel(xs[2],954,pw,'03','State can initiate work','sensors.py / world.py / autonomy.py',VIOLET)
para(xs[2],y,pw,'Host probes and agenda bridges supply observations. Facts expire to <b>UNKNOWN</b>; stale values do not masquerade as current ones. The deterministic trigger evaluator cannot call a model. Models can help carry out a decision after it fires.',10.3,13.8,limit=70)
stages=['OBSERVE','WORLD STATE','PREDICATE','HANDLER']
for i,s in enumerate(stages):
    x=xs[2]+i*86;txt(x,1097,s,7.5,'Mono',VIOLET)
    if i<3:arrow([(x+71,1093),(x+81,1093)],VIOLET,.55)
para(xs[2],1119,pw,'Live wiring includes fact expiry, memory drift, contradiction handling, map staleness and due agenda items. Interruption budgets decide when to surface non-alarm work. A fresh external enable token gates autonomous actuation.',10.3,13.8,limit=70)
para(xs[2],1197,pw,'Events use <b>HLC = (physical_ms, logical, node_id)</b>, ordered lexicographically: physical time, then a logical counter, then a node tie-breaker. Wall-clock arrival order cannot supersede a fact. Consumers must declare idempotency keys.',10.1,13.6,limit=70)
txt(xs[0],1275,'RANK: rule > source record > observation > user > derived',7.1,'Mono',GOLD)
txt(xs[1],1275,'SELF-MOD: propose and test; runtime self-merge is refused',7.1,'Mono',ROSE)
txt(xs[2],1275,'RECOVERY: fenced leases / durable tasks / checkpoints',7.1,'Mono',VIOLET)

# Lower field: actual implementation, not a shopping list of prospective tech.
y=panel(xs[0],1290,pw,'04','Voice, sight & touch','Swift bridges / speech.py / transcribe.py')
para(xs[0],y,pw,'<b>CURRENT</b>  Typed input, on-device English recognition, a local wake-word listener and Fn activation. Darija transcription uses permitted remote suppliers; speech uses provider routing or local synthesis, with degradations reported.',10.1,13.5,limit=70)
para(xs[0],y+77,pw,'Application and window adapters read, write, move and inspect. Accessibility actions re-resolve an element and check its role and label before touching it. UI-tree access is limited to the showing Desktop. Camera identity remains <b>PLANNED</b>.',10.1,13.5,limit=70)

y=panel(xs[1],1290,pw,'05','Runtime & instruments','build.sh / store.py / provider_supply.toml',ROSE)
para(xs[1],y,pw,'<b>CURRENT</b>  Python core; SQLite persistence; Swift/AppKit host; Metal face and ambience beneath WebKit HTML/CSS/JS. The app launches its bundled runtime. Five physical stores separate log, audit, tombstones, state and workspace.',10.1,13.5,limit=70)
para(xs[1],y+77,pw,'Supply contracts name Cloudflare, Groq, Gemini, Ollama and Mistral routes, plus purpose-specific voice and agent suppliers. These are configured candidates, not guaranteed availability. A bounded stdio MCP client is built; live server wiring is not established here.',10.1,13.5,limit=70)

y=panel(xs[2],1290,pw,'06','A fabric, still becoming','placement.py / fabric.py / SPIKE-001',VIOLET)
para(xs[2],y,pw,'<b>CURRENT</b>  Placement and survival decisions use measured capability profiles and trust constraints. Network trust can only weaken node trust. The dedicated segment remains <b>unattested</b>; deployment is not a demonstrated roaming fabric.',10.1,13.5,limit=70)
para(xs[2],y+77,pw,'<b>EXPERIMENTAL</b>  Local inference is profiled with llama.cpp. The recorded node-1 Qwen3-8B Q4_K_M run sustained <b>45.8 tok/s</b> (b10405-e79e4bf66, Vulkan; median of 3 x 10-minute runs, 2026-08-17). This is throughput, not conversational latency.',10.1,13.5,limit=70)

# Archival strip: dates are observed history, future stages have no invented dates.
rect(41,1495,W-82,115,'#e6dbc5')
txt(57,1516,'III  /  BUILD RECORD & OPEN FRONTIER',8,'Mono','#68513a',tracking=.8)
events=[('24 AUG','First routed','model call'),('30 AUG','L2 memory','committed'),('31 AUG','Voice + act','path joined'),('01-11 SEP','Multi-step agency','and host control')]
for i,(d,a,b) in enumerate(events):
    x=57+i*179
    line(x,1532,x+150,1532,'#ae946e',.6);circ(x+3,1532,2,'#806448',.7,fill='#e6dbc5')
    txt(x,1549,d+' 2026',7.7,'Mono','#765c3e')
    txt(x,1566,a,11,'Serif','#18212a');txt(x,1580,b,11,'Serif','#18212a')
line(784,1529,784,1586,'#b49f81',.6)
para(800,1529,322,'<b>PLANNED / OPEN</b>  Camera identity; cross-site connectivity; remote wake and service dormancy; multi-model residency; system widgets. SPIKE-002 still owes the full voice-latency chain. SPIKE-013 is measuring home-composite cost.',9.6,12.8,col='#273039',limit=65)
txt(57,1603,'Evidence discipline: 104 / 122 check IDs implemented; 18 PENDING. Registry inspected 2026-09-11, not a fresh full gate run.',8.3,'Sans','#4c4943')

txt(W/2,1631,'To remain useful, remember the source. To act, return to the world.',12,'SerifI',INK,'center')
txt(57,1645,'A2 / 420 x 594 mm / VECTOR TYPE + GEOMETRY',6.5,'Mono',DIM)
txt(W-57,1645,'SOURCE INDEX: accompanying SOURCE_MAP.md  /  official mark: 305 PPI',6.5,'Mono',DIM,'right')
C.showPage();C.save()
(OUT/'layout_audit.json').write_text(json.dumps(checks,indent=2))
print(f'Created {OUT}/VESPER_SYSTEM_BLUEPRINT_MASTER.pdf; {len(checks)} text regions fit their bounds.')
