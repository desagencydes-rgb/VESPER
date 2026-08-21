import json, math
P=json.load(open("palettes.json")); LS=json.load(open("lightsrc.json"))
PAL={"cream":"#f0e0c0","ember":"#B96645","solar":"#D99A52","blush":"#e8829d","purple":"#59348a",
     "gold":"#C5A35A","botanical":"#64745B","orange":"#ffaf95"}
def lin(c): c/=255; return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
def lum(h): h=h.lstrip('#'); r,g,b=(lin(int(h[i:i+2],16)) for i in (0,2,4)); return .2126*r+.7152*g+.0722*b
def cr(a,b):
    x,y=sorted((lum(a),lum(b)),reverse=True); return (x+.05)/(y+.05)
def mix(a,b,t):
    a=a.lstrip('#'); b=b.lstrip('#')
    return '#%02x%02x%02x'%tuple(round(int(a[i:i+2],16)*(1-t)+int(b[i:i+2],16)*t) for i in (0,2,4))

# accent per mode. "measured" = straight from the light-source hue.
# "curated" = the light source carried no usable hue, or averaged away the thing that gives
#             the frame its character, and a decision was made instead. Both are recorded.
ACC={
 "hall":     ("gold",     "measured", "Warm lamplight off limestone — 84°, straight to gold."),
 "ember":    ("solar",    "curated",  "The brightest thing is the galaxy, but the frame is about the one ember on the horizon. Took the ember."),
 "light":    ("purple",   "measured", "Violet sky at 283°. The lighthouse beam is the only other light and it is white."),
 "vein":     ("purple",   "measured", "Bioluminescence at 260°; purple is the nearest of the ten to that cyan."),
 "violet":   ("blush",    "measured", "Peach horizon under a violet field — 18°."),
 "gold":     ("gold",     "measured", "The gold band over the Alps, 78°. Unambiguous."),
 "wave":     ("solar",    "measured", "Peach sky above cold water, 66°."),
 "sepia":    ("solar",    "measured", "One hue family throughout, 77°."),
 "matte":    ("ember",    "curated",  "Chroma 0.006 — no hue signal at all. Ember chosen because it is the one colour legible on both grounds (4.49 / 3.59), and the frame's only colour is an orange reflector."),
 "leaf":     ("botanical","curated",  "Light source is the cream wall, but the subject is the foliage. Took the subject."),
 "arch":     ("blush",    "measured", "Magenta arch at 330°."),
}
WHEN={"Home":"The workspace at rest, with you in it.","Idle":"Nothing asked. One light left on.",
 "Watch":"A trigger is armed and waiting — an alarm, a deadline.","Listening":"Microphone open, or the input has focus.",
 "Thinking":"Reasoning. The panel up-left is filling.","Working":"A long task is running and holding.",
 "Flow":"Work going well; nothing needed from you.","Speaking":"Answering — aloud, or in text.",
 "Alert":"Something needs you. Everything else drops out.","Rest":"Quiet hours, or the host is under pressure.",
 "Milestone":"Something finished that mattered."}
IMG={"hall":"HALL","ember":"EMBER","light":"LIGHT","vein":"VEIN","violet":"VIOLET","gold":"GOLD",
     "wave":"WAVE","sepia":"SEPIA","matte":"MATTE","leaf":"LEAF","arch":"ARCH"}
ORDER=["hall","ember","light","vein","violet","gold","wave","sepia","matte","leaf","arch"]

out=[]
for k in ORDER:
    d=P[k]; cl=d["clusters"]; light = d["meanL"]>0.55 or k=="leaf"   # leaf: foliage mass drags mean L down; the frame is plainly daylight
    if light:
        base=max(cl,key=lambda c:c["L"])["hex"]; ground=mix(base,"#ffeae3",.55); g2=mix(base,"#ffeae3",.30); ink="#1b2530"; ink2="#4c5c66"
    else:
        base=min(cl,key=lambda c:c["L"])["hex"]; ground=mix(base,"#03141f",.55); g2=mix(base,"#03141f",.25); ink="#ffeae3"; ink2="#c3cdd4"
    an,prov,why = ACC[k]; accent=PAL[an]
    t=0.0                                            # legibility is not negotiable: step until it clears
    while cr(accent,ground) < 3.05 and t < 0.9:
        t += 0.06; accent = mix(PAL[an], "#03141f" if light else "#ffeae3", t)
    out.append({"key":k,"img":IMG[k],"mode":d["mode"],"when":WHEN[d["mode"]],"light":light,
      "ground":ground,"ground2":g2,"ink":ink,"ink2":ink2,"accent":accent,"accentName":an,
      "prov":prov,"why":why,"hue":round(LS[k]["H"]),"chroma":round(LS[k]["C"],3),
      "dots":[c["hex"] for c in cl[:5]],"contrast":round(cr(accent,ground),2)})
    print(f'{d["mode"]:<10} {"light" if light else "dark ":<6} ground {ground}  accent {accent} {an:<10} {cr(accent,ground):>5.2f}:1  [{prov}]')
json.dump(out,open("modes.json","w"),indent=1)
print("\nmeasured:",sum(1 for o in out if o["prov"]=="measured"),"  curated:",sum(1 for o in out if o["prov"]=="curated"))
