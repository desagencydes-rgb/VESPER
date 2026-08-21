import base64, json, os, mimetypes
R="refs/"
IMG={"ICON":R+"icon.png","FACE":R+"face.jpg","HALL":R+"hall.jpg","EMBER":R+"ember.jpg",
     "LIGHT":R+"light.jpg","VEIN":R+"vein.jpg","VIOLET":R+"violet.jpg","GOLD":R+"gold.jpg",
     "WAVE":R+"wave.jpg","SEPIA":R+"sepia.jpg","MATTE":R+"matte.jpg","LEAF":R+"leaf.jpg",
     "ARCH":R+"arch.jpg"}
uri={}
for k,p in IMG.items():
    mt = "image/png" if p.endswith(".png") else "image/jpeg"
    uri[k]="data:%s;base64,%s"%(mt, base64.b64encode(open(p,'rb').read()).decode())

html = "".join(open(f).read() for f in
       ["head.html","css2.html","body1.html","body2.html","body3.html","body4.html","js1.html","js2.html"])
html = html.replace("__MODES__", json.dumps(json.load(open("modes.json")), separators=(",",":")))
html = html.replace("__IMGMAP__", json.dumps({k:uri[k] for k in
       ["HALL","EMBER","LIGHT","VEIN","VIOLET","GOLD","WAVE","SEPIA","MATTE","LEAF","ARCH"]},
       separators=(",",":")))
for k,v in uri.items():
    html = html.replace("__%s__"%k, v)
assert "__" not in html.replace("__","",0) or True
left=[t for t in ["__ICON__","__FACE__","__MODES__","__IMGMAP__"] if t in html]
open("vesper-design-foundation.html","w").write(html)
print("unsubstituted tokens:", left or "none")
print("size: %.2f MB"%(len(html.encode())/1024/1024))
