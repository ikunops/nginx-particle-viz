# -*- coding: utf-8 -*-
"""
Preview the three envelope options side by side, rendered with the REAL
stratum renderer pieces (fibre.py splatting + taper profile), on a synthetic
route shaped like the nginx trunk.

This answers "which of tight-spread-tight / tight-tight-tight / tight-spread-open
looks best" before committing to one in the scene.
"""
import os, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fibre as F

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

W, H = 720, 300
P = [(60.0, 150.0), (300.0, 96.0), (470.0, 208.0), (660.0, 150.0)]

MODES = [
    ("tight  (gather-spread-gather)", lambda t: 0.22 + 0.78 * math.sin(math.pi * t) ** 0.85),
    ("flat   (gather-gather-gather)", lambda t: 1.0),
    ("open   (spread-spread-gather)", lambda t: 0.45 + 0.55 * (1.0 - t)),
]

NSTRANDS = 22
SPREAD = 44.0
WOBBLE = 4.2


def render_panel(env_fn, ssamp=2.0):
    s = ssamp
    Wp, Hp = int(W * s), int(H * s)
    buf = np.zeros((Hp, Wp, 3), np.float32)
    col = (0.22, 0.72, 1.00)

    # --- fibres: 22 strands, lateral offset scaled by the envelope
    for j in range(NSTRANDS):
        u = (j / (NSTRANDS - 1)) * 2 - 1
        ph = (j * 0.37) % 1.0
        pts = []
        for i in range(161):
            t = i / 160
            base = F.bez(P, np.array([t]))[0]
            nxt = F.bez(P, np.array([min(1.0, t + 0.004)]))[0]
            dx, dy = nxt[0] - base[0], nxt[1] - base[1]
            dl = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / dl, dx / dl
            off = (u * SPREAD + WOBBLE * math.sin(2 * math.pi * (1.5 * t + ph))) * env_fn(t)
            pts.append((base[0] + nx * off, base[1] + ny * off))
        for i in range(len(pts) - 1):
            x0, y0 = pts[i][0] * s, pts[i][1] * s
            x1, y1 = pts[i + 1][0] * s, pts[i + 1][1] * s
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) * 1.4))
            for k in range(n + 1):
                f = k / n
                F.line_add(buf, np.array([x0 + (x1 - x0) * f]),
                           np.array([y0 + (y1 - y0) * f]),
                           np.array([0.16], np.float32), col)

    # --- particles with the smooth taper (no hard dot)
    for pidx in range(26):
        v0 = (pidx * 0.6180339887) % 1.0
        lu = ((pidx * 0.37) % 1.0) * 2 - 1
        ext = 0.085                      # particle extent in t
        for q in range(15):
            w = q / 14.0                 # 0=tail .. 1=nose
            t = v0 - ext * (1.0 - w)
            if t < 0 or t > 1:
                continue
            base = F.bez(P, np.array([t]))[0]
            nxt = F.bez(P, np.array([min(1.0, t + 0.004)]))[0]
            dx, dy = nxt[0] - base[0], nxt[1] - base[1]
            dl = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / dl, dx / dl
            off = lu * SPREAD * env_fn(t)
            x = (base[0] + nx * off) * s
            y = (base[1] + ny * off) * s
            a = float(F.taper_alpha(np.array([w]))[0])
            r = float(F.taper_radius(np.array([w]), 1.7, 0.0)[0])
            F.blob_add(buf, x, y, max(1.0, r * s), 1.15 * a, col)

    light = F.bloom(buf, s, scales=(1.6, 5.0, 16.0), weights=(0.42, 0.20, 0.10))
    bg = np.zeros((Hp, Wp, 3), np.float32)
    bg[..., 2] = 0.016
    img = Image.fromarray(F.tonemap(light, gain=2.6, bg=bg), "RGB")
    return img.resize((W, H), Image.LANCZOS)


def main():
    panels = [(name, render_panel(fn)) for name, fn in MODES]
    fb = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 15)
    pad = 12
    sheet = Image.new("RGB", (W + pad * 2, (H + 28) * len(panels) + pad), (6, 8, 13))
    d = ImageDraw.Draw(sheet)
    y = pad
    for name, im in panels:
        d.text((pad, y), name, font=fb, fill=(170, 215, 240))
        sheet.paste(im, (pad, y + 22))
        y += H + 28
    out = os.path.join(OUT, "detail-envelope-options.png")
    sheet.save(out)
    print("wrote", out, sheet.size)


if __name__ == "__main__":
    main()
