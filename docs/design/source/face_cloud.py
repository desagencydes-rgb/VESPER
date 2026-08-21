"""Turn the owner's face reference into a 3D point cloud the island can rotate.

THE PROBLEM THIS SOLVES. The reference is a flat image of a point-cloud head. The
island needs a head that turns -- eyes leading by 80 ms, yaw +/-18, pitch +/-12 --
and a flat sprite cannot turn. Faking it with parallax reads as a photograph on a
turntable the moment it moves off axis.

THE METHOD. Sample the reference's own lit points for (x, y) and their intensity,
so head-on the cloud IS the reference rather than a resemblance of it. Then give
each point a z from a head-shaped depth field, so that turning it produces a
plausible head instead of a flat card. The silhouette goes to z ~ 0 and the centre
comes forward; the nose bridge gets an extra push because an ellipsoid alone gives
a face with no profile, which reads as a mask.

WHAT THIS IS NOT. It is not a scan and does not claim to be. It is a depth
heuristic over real (x, y) data, and DESIGN-FOUNDATION §8's decided motion
numbers -- not this file -- govern how it moves.

Stdlib only. JPEG is not decodable from the stdlib, so the committed .jpg is
converted to PNG with `sips` first; the decoder here is the same one every other
derivation in this directory uses.
"""

import math, os, random, struct, subprocess, sys, zlib

random.seed(11)   # reproducible: the same reference must yield the same cloud

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "ui-refs", "face-and-hologram-panels.jpg")
OUT = os.path.join(HERE, "..", "..", "..", "app", "island-macos", "face.bin")


def read_png(p):
    d = open(p, 'rb').read(); assert d[:8] == b'\x89PNG\r\n\x1a\n'
    i = 8; w = h = bitd = ct = None; idat = b''
    while i < len(d):
        ln, typ = struct.unpack('>I4s', d[i:i+8]); body = d[i+8:i+8+ln]; i += 12 + ln
        if typ == b'IHDR': w, h, bitd, ct = struct.unpack('>IIBB', body[:10])
        elif typ == b'IDAT': idat += body
        elif typ == b'IEND': break
    nch = {0:1, 2:3, 3:1, 4:2, 6:4}[ct]
    raw = zlib.decompress(idat); stride = w*nch; prev = bytearray(stride); o = 0; rows = []
    for _ in range(h):
        f = raw[o]; line = bytearray(raw[o+1:o+1+stride]); o += 1+stride
        for x in range(stride):
            a = line[x-nch] if x >= nch else 0; b = prev[x]; c = prev[x-nch] if x >= nch else 0
            if   f == 1: line[x] = (line[x]+a) & 255
            elif f == 2: line[x] = (line[x]+b) & 255
            elif f == 3: line[x] = (line[x]+(a+b)//2) & 255
            elif f == 4:
                pp = a+b-c; pa, pb, pc = abs(pp-a), abs(pp-b), abs(pp-c)
                line[x] = (line[x]+(a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        rows.append([(line[x*nch], line[x*nch+1], line[x*nch+2]) if nch >= 3 else (line[x],)*3
                     for x in range(w)])
    return w, h, rows


# The head sits centre frame; the hologram panels live at the edges and are NOT
# part of the face. These bounds cut the panels off rather than trying to
# classify them -- a threshold that tried would take the brightest panel text too.
CROP = (0.235, 0.055, 0.780, 0.900)   # x0, y0, x1, y1 as fractions


def depth(u, v, lum):
    """z for a point at normalised (u, v), origin at the head's centre.

    An ellipsoid gives the head its roundness. On its own it produces a face with
    no profile -- correct at the silhouette, flat where a nose should be -- so the
    central band gets a raised-cosine push forward, strongest on the vertical
    midline and fading out by the cheeks.
    """
    q = (u / 0.68) ** 2 + (v / 1.02) ** 2
    if q >= 1.0:
        return 0.0
    z = math.sqrt(1.0 - q)
    # profile: nose and brow ridge, centred on the midline, mid-face vertically
    prof = math.exp(-(u / 0.15) ** 2) * math.exp(-((v + 0.05) / 0.46) ** 2)
    return z * 0.78 + prof * 0.34


def main() -> int:
    stride = int(sys.argv[sys.argv.index("--stride") + 1]) if "--stride" in sys.argv else 3
    thresh = int(sys.argv[sys.argv.index("--threshold") + 1]) if "--threshold" in sys.argv else 46

    png = "/tmp/face-src.png"
    subprocess.run(["sips", "-s", "format", "png", SRC, "--out", png],
                   capture_output=True, check=True)
    w, h, rows = read_png(png)
    x0, y0, x1, y1 = (int(CROP[0]*w), int(CROP[1]*h), int(CROP[2]*w), int(CROP[3]*h))
    cw, ch = x1 - x0, y1 - y0

    # SAMPLED PROBABILISTICALLY, NOT ON A GRID. Taking every Nth pixel puts the
    # points on a regular lattice, and that lattice beats against the display's
    # pixel grid: the first build rendered a face drowned in concentric moiré
    # rings. Keeping each lit pixel with probability 1/stride^2, and jittering
    # inside its cell, gives the same density with no lattice to interfere --
    # which is also what the reference's own dot pattern looks like up close.
    keep = 1.0 / (stride * stride)
    pts = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = rows[y][x]
            lum = max(r, g, b)
            if lum < thresh:
                continue
            # Brighter pixels are likelier to survive, so structure is preserved
            # while flat areas thin out.
            if random.random() > keep * (0.55 + 1.35 * (lum / 255.0)):
                continue
            # Normalise BOTH axes by the crop HEIGHT, not each by its own extent.
            # Per-axis normalisation stretches the head to a square: it looked
            # right head-on, which is exactly why it would have survived review,
            # and turned into a wide mask the moment it yawed.
            jx = x + random.uniform(-0.5, 0.5) * stride
            jy = y + random.uniform(-0.5, 0.5) * stride
            u = ((jx - x0) - cw / 2) / (ch / 2)
            v = ((jy - y0) - ch / 2) / (ch / 2)
            z = depth(u, v, lum)
            if z <= 0.0:
                continue
            pts.append((u, -v, z, lum / 255.0))   # -v: screen y is down, model y is up

    # x, y, z, intensity as float32 -- 16 bytes a point, mmap-friendly, no parser.
    with open(OUT, "wb") as f:
        f.write(struct.pack("<I", len(pts)))
        for p in pts:
            f.write(struct.pack("<4f", *p))

    zs = [p[2] for p in pts]
    print(f"source      {w}x{h}, head crop {cw}x{ch}")
    print(f"stride {stride}, threshold {thresh}")
    print(f"points      {len(pts):,}  ({os.path.getsize(OUT)/1024:.0f} KB)")
    print(f"z range     {min(zs):.3f} .. {max(zs):.3f}")
    print(f"-> {os.path.relpath(OUT, os.path.join(HERE, '..', '..', '..'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
