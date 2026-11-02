# -*- coding: utf-8 -*-
"""
Visual proof of the three link states + travelling bright segment.

Three identical routes, top to bottom:
    faint (idle, dashed)   /  solid (warm)  /  bright (active, pulse segment)

Plus a fourth showing request (cyan, left->right) and response (amber,
right->left) pulses on the SAME line at once -- the bidirectional exchange the
user asked for.
"""
import os, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fibre as F

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

W, H = 900, 460
ROUTES = [
    (0, "faint  -  idle, dashed",      (0.42, 0.60, 0.70)),
    (1, "solid  -  warm, continuous",  (0.30, 0.78, 1.00)),
    (2, "bright -  active, pulse seg", (0.35, 0.95, 1.00)),
]


def pill(y):
    return [(90.0, y), (330.0, y - 26.0), (560.0, y + 26.0), (800.0, y)]


def render(ssamp=2.0):
    s = ssamp
    Wp, Hp = int(W * s), int(H * s)
    buf = np.zeros((Hp, Wp, 3), np.float32)

    for idx, (state, _label, col) in enumerate(ROUTES):
        y = 90.0 + idx * 100.0
        F.draw_link(buf, s, pill(y), col, state, phase=0.55,
                    base_amp=0.075 if state else 0.045,
                    bright_amp=1.25, width=1.7,
                    nfib=7, spread=20.0, wob=2.2)

    # bidirectional exchange on one route
    y = 90.0 + 3 * 100.0
    P = pill(y)
    F.draw_link(buf, s, P, (0.30, 0.72, 1.00), 1, phase=0.0,
                base_amp=0.070, width=1.6, nfib=7, spread=20.0, wob=2.2)
    F.pulse_segment(buf, s, P, None, 0.62, (0.35, 0.95, 1.00), 1.30, width=1.8)
    F.pulse_segment(buf, s, P, None, 0.30, (1.00, 0.74, 0.26), 1.20, width=1.8)

    light = F.bloom(buf, s, scales=(1.6, 5.0, 16.0), weights=(0.40, 0.18, 0.09))
    bg = np.zeros((Hp, Wp, 3), np.float32)
    bg[..., 2] = 0.014
    img = Image.fromarray(F.tonemap(light, gain=2.3, bg=bg), "RGB")
    img = img.resize((W, H), Image.LANCZOS)

    d = ImageDraw.Draw(img)
    fb = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 14)
    labels = [r[1] for r in ROUTES] + ["request + response on one line"]
    for idx, lab in enumerate(labels):
        d.text((16, 74 + idx * 100), lab, font=fb, fill=(170, 205, 225))
    return img


def main():
    im = render()
    out = os.path.join(OUT, "detail-link-states.png")
    im.save(out)
    print("wrote", out, im.size)


if __name__ == "__main__":
    main()
