"""Accent = the LIGHT SOURCE, not the mean. The mean of a night photograph is the night."""
import json, math
# extract.py's script body now sits under a __main__ guard, so this is a plain
# import. It used to be `open(...).read().split("MODE={")[0]` and an exec -- a
# string split against another file's source, which broke the moment that file
# gained a line above the marker. Reusing a decoder should not be textual.
from extract import read_png, to_oklab, to_rgb

PAL={"cream":"#f0e0c0","ember":"#B96645","solar":"#D99A52","blush":"#e8829d","purple":"#59348a",
     "gold":"#C5A35A","botanical":"#64745B","orange":"#ffaf95"}
def lin(c): c/=255; return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
def lum(h): h=h.lstrip('#'); r,g,b=(lin(int(h[i:i+2],16)) for i in (0,2,4)); return .2126*r+.7152*g+.0722*b
def cr(a,b):
    x,y=sorted((lum(a),lum(b)),reverse=True); return (x+.05)/(y+.05)
def hx2lab(h): return to_oklab(tuple(int(h.lstrip('#')[i:i+2],16) for i in (0,2,4)))
PLAB={n:hx2lab(h) for n,h in PAL.items()}
def hue(l): return math.degrees(math.atan2(l[2],l[1]))%360
def dh(a,b): d=abs(a-b)%360; return min(d,360-d)

P=json.load(open("palettes.json"))
ORDER=["hall","ember","light","vein","violet","gold","wave","sepia","matte","leaf","arch"]
print(f"{'mode':<11}{'light-source hue':>17}{'C':>7}   nearest three")
lightsrc={}
for key in ORDER:
    px=read_png(f"refs/tiny/{key}.png"); labs=[to_oklab(p) for p in px]
    # "glow" score: bright AND chromatic. Top 4% are the light sources in the frame.
    sc=sorted(labs,key=lambda l:-(l[0]*(1+3*math.hypot(l[1],l[2]))))
    top=sc[:max(6,len(sc)*4//100)]
    a=sum(l[1] for l in top)/len(top); b=sum(l[2] for l in top)/len(top)
    L=sum(l[0] for l in top)/len(top); C=math.hypot(a,b); H=math.degrees(math.atan2(b,a))%360
    near=sorted(PAL,key=lambda n:dh(hue(PLAB[n]),H))[:3]
    lightsrc[key]={"H":H,"C":C,"L":L,"near":near,"hex":to_rgb(L,a,b)}
    print(f'{P[key]["mode"]:<11}{H:>14.0f}°{C:>7.3f}   {", ".join(near)}   {to_rgb(L,a,b)}')
json.dump(lightsrc, open("lightsrc.json","w"), indent=1)
