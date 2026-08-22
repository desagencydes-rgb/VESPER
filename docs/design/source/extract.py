"""Pull the actual palette out of each reference image. Stdlib only (PNG = zlib + defilter)."""
import zlib, struct, math, json, random
random.seed(7)

def read_png(p):
    d = open(p,'rb').read(); assert d[:8]==b'\x89PNG\r\n\x1a\n'
    i, idat, w=h=None, b'', 8
    i = 8; w=h=None; bitd=ct=None; idat=b''
    while i < len(d):
        ln, typ = struct.unpack('>I4s', d[i:i+8]); body = d[i+8:i+8+ln]; i += 12+ln
        if typ==b'IHDR': w,h,bitd,ct = struct.unpack('>IIBB', body[:10])
        elif typ==b'IDAT': idat += body
        elif typ==b'IEND': break
    assert bitd==8, bitd
    nch = {0:1,2:3,3:1,4:2,6:4}[ct]
    raw = zlib.decompress(idat); px=[]; stride = w*nch; prev = bytearray(stride); o=0
    for _ in range(h):
        f = raw[o]; line = bytearray(raw[o+1:o+1+stride]); o += 1+stride
        for x in range(stride):
            a = line[x-nch] if x>=nch else 0; b = prev[x]; c = prev[x-nch] if x>=nch else 0
            if   f==1: line[x]=(line[x]+a)&255
            elif f==2: line[x]=(line[x]+b)&255
            elif f==3: line[x]=(line[x]+(a+b)//2)&255
            elif f==4:
                pp=a+b-c; pa,pb,pc=abs(pp-a),abs(pp-b),abs(pp-c)
                line[x]=(line[x]+(a if pa<=pb and pa<=pc else b if pb<=pc else c))&255
        prev=line
        for x in range(w):
            q=line[x*nch:x*nch+nch]
            px.append((q[0],q[1],q[2]) if nch>=3 else (q[0],q[0],q[0]))
    return px

def lin(c): c/=255; return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
def unlin(c): return round(255*(12.92*c if c<=0.0031308 else 1.055*c**(1/2.4)-0.055))
def to_oklab(rgb):
    r,g,b=(lin(v) for v in rgb)
    l=(0.4122214708*r+0.5363325363*g+0.0514459929*b)**(1/3)
    m=(0.2119034982*r+0.6806995451*g+0.1073969566*b)**(1/3)
    s=(0.0883024619*r+0.2817188376*g+0.6299787005*b)**(1/3)
    return (0.2104542553*l+0.7936177850*m-0.0040720468*s,
            1.9779984951*l-2.4285922050*m+0.4505937099*s,
            0.0259040371*l+0.7827717662*m-0.8086757660*s)
def to_rgb(L,a,bb):
    l=(L+0.3963377774*a+0.2158037573*bb)**3
    m=(L-0.1055613458*a-0.0638541728*bb)**3
    s=(L-0.0894841775*a-1.2914855480*bb)**3
    r= 4.0767416621*l-3.3077115913*m+0.2309699292*s
    g=-1.2684380046*l+2.6097574011*m-0.3413193965*s
    b=-0.0041960863*l-0.7034186147*m+1.7076147010*s
    return '#%02x%02x%02x'%tuple(max(0,min(255,unlin(max(0.0,v)))) for v in (r,g,b))

def kmeans(pts,k=5,iters=40):
    cs=random.sample(pts,k)
    for _ in range(iters):
        buckets=[[] for _ in range(k)]
        for p in pts:
            buckets[min(range(k), key=lambda j: sum((p[d]-cs[j][d])**2 for d in range(3)))].append(p)
        new=[]
        for j,b in enumerate(buckets):
            new.append(tuple(sum(x[d] for x in b)/len(b) for d in range(3)) if b else cs[j])
        if new==cs: break
        cs=new
    sizes=[len(b) for b in buckets]
    return sorted(zip(cs,sizes), key=lambda t:-t[1])

PAL={"cream":"#f0e0c0","ember":"#B96645","solar":"#D99A52","blush":"#e8829d","purple":"#59348a",
     "gold":"#C5A35A","botanical":"#64745B","orange":"#ffaf95","white":"#ffeae3","black":"#03141f"}
PAL_LAB={n:to_oklab(tuple(int(h.lstrip('#')[i:i+2],16) for i in (0,2,4))) for n,h in PAL.items()}
def nearest(lab):
    return min(PAL_LAB, key=lambda n: (lab[0]-PAL_LAB[n][0])**2 + 4*((lab[1]-PAL_LAB[n][1])**2+(lab[2]-PAL_LAB[n][2])**2))

# The script body runs under a guard so the decoder and the OKLab helpers can be
# imported by home_wallpapers.py. Importing a module should not read twelve files
# off disk and rewrite palettes.json as a side effect.
if __name__ == "__main__":
    MODE={"hall":"Home","ember":"Idle","light":"Watch","vein":"Listening","violet":"Thinking",
          "gold":"Working","wave":"Flow","sepia":"Speaking","matte":"Alert","leaf":"Rest",
          "arch":"Milestone","face":"(face ref)"}
    out={}
    for key in ["hall","ember","light","vein","violet","gold","wave","sepia","matte","leaf","arch","face"]:
        px=read_png(f"refs/tiny/{key}.png"); labs=[to_oklab(p) for p in px]
        cl=kmeans(labs,5); tot=sum(s for _,s in cl)
        ent=[]
        for lab,s in cl:
            ent.append({"hex":to_rgb(*lab),"share":round(100*s/tot),
                        "L":round(lab[0],3),"C":round(math.hypot(lab[1],lab[2]),3),
                        "near":nearest(lab)})
        meanL=sum(l[0] for l in labs)/len(labs)
        meanC=sum(math.hypot(l[1],l[2]) for l in labs)/len(labs)
        out[key]={"mode":MODE[key],"meanL":round(meanL,3),"meanC":round(meanC,3),"clusters":ent}
        names=" ".join(f"{e['hex']}({e['share']:>2}%→{e['near']})" for e in ent)
        print(f"{MODE[key]:<11} {key:<7} L={meanL:.2f} C={meanC:.3f}  {names}")
    json.dump(out, open("palettes.json","w"), indent=1)
