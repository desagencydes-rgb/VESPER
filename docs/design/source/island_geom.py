"""Measure the island out of the owner's UI reference set, rather than eyeballing it.

The references in `docs/design/ui-refs/` are composites, not screenshots of this
display: they were authored ~1915 px wide standing in for a 1728 pt logical screen.
Every number is therefore reported in logical points, with the scale that produced it
stated rather than assumed, and `manifest.toml` carries the provenance -- original
filename, checksum, original size, crop origin -- so a crop can still be measured in
the coordinate system of the screen it depicts.

Method. The island is the near-black region welded to the bezel. We flood fill it from
a seed on its first dark row and take, per row, the minimum and maximum x of the fill.
An earlier version took the maximal *contiguous run* through the centre instead, and
that was wrong: bright text inside the panel splits the run, so glyphs were being
reported as geometry -- a 645 -> 57 px "step" that was a line of type. The fill routes
around glyphs, so the row extents stay the true outer edge.

Everything here is stdlib only, like every other derivation in this directory, so it
runs on a bare interpreter the way `profile_node.py` does.
"""
import zlib, struct, sys, json, os

try:
    import tomllib
    def load_toml(p): return tomllib.load(open(p, "rb"))
except ModuleNotFoundError:
    # The system python3 on this machine is 3.9. Every other derivation here runs on a
    # bare interpreter, and a manifest reader is not worth breaking that for, so the
    # flat key = value subset this file uses is parsed directly.
    def load_toml(p):
        out, cur = {}, None
        for ln in open(p):
            ln = ln.split("#")[0].strip()
            if not ln: continue
            if ln.startswith("[") and ln.endswith("]"):
                cur = out
                for part in ln[1:-1].split("."): cur = cur.setdefault(part, {})
            elif "=" in ln and cur is not None:
                k, v = (s.strip() for s in ln.split("=", 1))
                if v.startswith('"'): cur[k] = v.strip('"')
                elif v.startswith("["): cur[k] = [int(x) for x in v[1:-1].split(",")]
                else: cur[k] = float(v) if "." in v else int(v)
        return out
from collections import Counter

LOGICAL_W, LOGICAL_H = 1728, 1117    # measured on this display, DESIGN-FOUNDATION §10
NOTCH_X = (771.0, 956.0)             # the camera, same source
SAFE_TOP = 32.0                      # safe-area top inset
DARK = 46                            # a pixel is shell if every channel is below this
HERE = os.path.dirname(os.path.abspath(__file__))
UI_REFS = os.path.join(HERE, "..", "ui-refs")


def read_png(p):
    d = open(p, 'rb').read(); assert d[:8] == b'\x89PNG\r\n\x1a\n'
    i = 8; w = h = bitd = ct = None; idat = b''
    while i < len(d):
        ln, typ = struct.unpack('>I4s', d[i:i+8]); body = d[i+8:i+8+ln]; i += 12 + ln
        if typ == b'IHDR': w, h, bitd, ct = struct.unpack('>IIBB', body[:10])
        elif typ == b'IDAT': idat += body
        elif typ == b'IEND': break
    assert bitd == 8, bitd
    nch = {0:1, 2:3, 3:1, 4:2, 6:4}[ct]
    raw = zlib.decompress(idat); stride = w * nch; prev = bytearray(stride); o = 0; rows = []
    for _ in range(h):
        f = raw[o]; line = bytearray(raw[o+1:o+1+stride]); o += 1 + stride
        for x in range(stride):
            a = line[x-nch] if x >= nch else 0; b = prev[x]; c = prev[x-nch] if x >= nch else 0
            if   f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pp = a + b - c; pa, pb, pc = abs(pp-a), abs(pp-b), abs(pp-c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        rows.append([(line[x*nch], line[x*nch+1], line[x*nch+2]) if nch >= 3
                     else (line[x],)*3 for x in range(w)])
    return w, h, rows


def write_png(path, w, h, rows):
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    raw = b''.join(b'\x00' + bytes(v for px in r for v in px) for r in rows)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def is_dark(px): return px[0] < DARK and px[1] < DARK and px[2] < DARK


def top_offset(w, h, rows):
    """First row whose centre pixel is shell. The Shoulders export carries a white band
    above the island; treating its y=0 as the bezel would shift every number down."""
    cx = w // 2
    for y in range(min(h, 60)):
        if is_dark(rows[y][cx]): return y
    return None


def island_mask(w, h, rows, seed_y, cap=4_000_000):
    seen = bytearray(w * h); stack = [(w // 2, seed_y)]; n = 0; rmin = {}; rmax = {}
    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= w or y >= h: continue
        i = y * w + x
        if seen[i] or not is_dark(rows[y][x]): continue
        seen[i] = 1; n += 1
        if n > cap: raise RuntimeError("flood fill ran away -- island not isolated from the frame")
        if y not in rmin or x < rmin[y]: rmin[y] = x
        if y not in rmax or x > rmax[y]: rmax[y] = x
        stack += [(x+1, y), (x-1, y), (x, y+1), (x, y-1)]
    return rmin, rmax, n


def measure(path, scale, crop_x):
    """All island numbers, in logical points. `scale` and `crop_x` come from the manifest,
    so a cropped reference still reports x in screen coordinates."""
    w, h, rows = read_png(path)
    off = top_offset(w, h, rows)
    if off is None: return None
    rmin, rmax, npx = island_mask(w, h, rows, off)
    ys = sorted(rmin); last = off
    for y in ys:                       # contiguous from the bezel only
        if y > last + 1: break
        last = y
    ys = [y for y in ys if y <= last]
    wd = {y: rmax[y] - rmin[y] + 1 for y in ys}
    pt = lambda v: round(v / scale, 1)
    hgt = last - off + 1
    plateau = Counter(wd[y] for y in ys if y < off + hgt * 0.8).most_common(1)[0][0]
    corner_y = next((y for y in ys if y > off + hgt * 0.5 and wd[y] < plateau - 2), None)

    ink = [y for y in ys if sum(1 for x in range(rmin[y], rmax[y]+1) if max(rows[y][x]) > 90) > 3]
    collide = 0
    for y in ink:
        if (y - off) / scale > SAFE_TOP: break
        for x in range(rmin[y], rmax[y] + 1):
            if NOTCH_X[0] <= (x + crop_x) / scale <= NOTCH_X[1] and max(rows[y][x]) > 90: collide += 1

    tones = Counter()
    for y in range(off + int(30 * scale), last, 2):
        for x in range(rmin[y] + 6, rmax[y] - 6, 2):
            p = rows[y][x]
            if 4 <= max(p) <= 70: tones[p] += 1

    return {
        "height_pt": pt(hgt),
        "width_bezel_pt": pt(wd[off]), "width_body_pt": pt(plateau),
        "fillet_pt": pt((wd[off] - plateau) / 2),
        "width_over_notch": round(wd[off] / scale / 185.0, 3),
        "corner_rx_pt": pt((plateau - wd[last]) / 2) if corner_y else 0.0,
        "corner_ry_pt": pt(last - corner_y + 1) if corner_y else 0.0,
        "x_left_pt": pt(rmin[off] + crop_x), "x_right_pt": pt(rmax[off] + crop_x),
        "centre_offset_pt": pt((rmin[off] + rmax[off]) / 2 + crop_x - LOGICAL_W * scale / 2),
        "first_ink_pt": pt(ink[0] - off) if ink else None,
        "notch_collision_px": collide,
        "interior_tone": (lambda t: {"rgb": list(t[0][0]), "hex": '#%02x%02x%02x' % t[0][0],
                                     "px": t[0][1]} if t else None)(tones.most_common(1)),
        "mask_px": npx,
    }


def crop_island(src, dst, pad=24):
    """Cut the island out of a full-frame reference, with air for the weld and the shadow.
    The wallpaper behind these composites is not the reference and does not compress:
    three full frames cost more than the entire repository."""
    w, h, rows = read_png(src)
    off = top_offset(w, h, rows)
    if off is None: raise SystemExit(f"{src}: no island found")
    rmin, rmax, _ = island_mask(w, h, rows, off)
    ys = sorted(rmin); last = off
    for y in ys:
        if y > last + 1: break
        last = y
    ys = [y for y in ys if y <= last]
    x0 = max(0, min(rmin[y] for y in ys) - pad); x1 = min(w, max(rmax[y] for y in ys) + pad)
    y1 = min(h, last + pad)
    write_png(dst, x1 - x0, y1, [r[x0:x1] for r in rows[0:y1]])
    return {"crop_x": x0, "crop_h": y1, "src_w": w, "src_h": h}


if __name__ == "__main__":
    man = load_toml(os.path.join(UI_REFS, "manifest.toml"))
    out = {}
    for name, m in man["reference"].items():
        # the face and the context frame are references too, but they are not islands
        if not m["file"].endswith(".png"): continue
        r = measure(os.path.join(UI_REFS, m["file"]), m["scale"], m["crop_x"])
        if not r: print(f"{name}: island not found"); continue
        out[name] = r
        print(f"\n=== {name}   ({m['file']}, scale {m['scale']})")
        print(f"  height          {r['height_pt']:>7} pt")
        print(f"  width at bezel  {r['width_bezel_pt']:>7} pt   = {r['width_over_notch']} x the notch")
        print(f"  width of body   {r['width_body_pt']:>7} pt   (bezel fillet {r['fillet_pt']} pt/side)")
        print(f"  bottom corner   rx {r['corner_rx_pt']} pt, ry {r['corner_ry_pt']} pt")
        print(f"  x span          {r['x_left_pt']} -> {r['x_right_pt']} pt, centre {r['centre_offset_pt']:+} pt")
        print(f"  first ink at    {r['first_ink_pt']} pt")
        print(f"  interior tone   {r['interior_tone']['hex']} ({r['interior_tone']['px']} px sampled)")
        v = r['notch_collision_px']
        print(f"  camera          {'CLEARS' if v == 0 else f'COLLIDES -- {v} px of ink under the housing'}")
    json.dump(out, open(os.path.join(HERE, "island_geom.json"), "w"), indent=1)
    print("\n-> island_geom.json")
