import math
def srgb_lin(c):
    c/=255
    return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
def hex_to_oklch(h):
    h=h.lstrip('#'); r,g,b=(srgb_lin(int(h[i:i+2],16)) for i in (0,2,4))
    l=0.4122214708*r+0.5363325363*g+0.0514459929*b
    m=0.2119034982*r+0.6806995451*g+0.1073969566*b
    s=0.0883024619*r+0.2817188376*g+0.6299787005*b
    l_,m_,s_=[x**(1/3) if x>0 else -((-x)**(1/3)) for x in (l,m,s)]
    L=0.2104542553*l_+0.7936177850*m_-0.0040720468*s_
    a=1.9779984951*l_-2.4285922050*m_+0.4505937099*s_
    bb=0.0259040371*l_+0.7827717662*m_-0.8086757660*s_
    C=math.hypot(a,bb); H=math.degrees(math.atan2(bb,a))%360
    return L,C,H
def rel_lum(h):
    h=h.lstrip('#'); r,g,b=(srgb_lin(int(h[i:i+2],16)) for i in (0,2,4))
    return 0.2126*r+0.7152*g+0.0722*b
def wcag(h1,h2):
    a,b=sorted((rel_lum(h1),rel_lum(h2)),reverse=True)
    return (a+0.05)/(b+0.05)

pal=[("cream","#f0e0c0"),("ember","#B96645"),("solar","#D99A52"),("blush","#e8829d"),
     ("purple","#59348a"),("gold","#C5A35A"),("botanical","#64745B"),("orange","#ffaf95"),
     ("white","#ffeae3"),("black","#03141f")]
print(f"{'name':<11}{'hex':<10}{'L':>7}{'C':>7}{'H':>7}   {'on black':>9} {'on white':>9}")
for n,h in pal:
    L,C,H=hex_to_oklch(h)
    print(f"{n:<11}{h:<10}{L:>7.3f}{C:>7.3f}{H:>7.1f}   {wcag(h,'#03141f'):>8.2f}: {wcag(h,'#ffeae3'):>8.2f}:")
print()
print("ground pair contrast  black/white :", round(wcag('#03141f','#ffeae3'),2))
