# -*- coding: utf-8 -*-
"""
Render the four particle grammars side by side, on the same route, so the
template catalogue has a visual index.

These are style choices, not correctness choices. Any of them may be right for a
future scene; "pulse" happens to suit nginx because a link is long-lived and the
interesting event is data moving through it.
"""
import os, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fibre as F

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

W, H = 860, 560
P = [(70.0, 90.0), (300.0, 40.0), (540.0, 140.0), (790.0, 90.0)]

STYLES = [
    ("pulse   —  fibre lights up, width-exact", "pulse",   (0.30, 0.90, 1.00)),
    ("missile —  head + long tail, strong direction", "missile", (0.42, 0.78, 1.00)),
    ("clump   —  dense soft blobs (NN activations)", "clump",   (0.62, 0.86, 1.00)),
    ("bead    —  small discrete dots (control traffic)", "bead", (0.50, 0.95, 0.86)),
]


def render(ssamp=2.0):
    s = ssamp
    Wp, Hp = int(W * s), int(H * s)
    buf = np.zeros((Hp, Wp, 3), np.float32)

    for i, (label, style, col) in enumerate(STYLES):
        y0 = 90.0 + i * 120.0
        route = [(p[0], p[1] + (y0 - 90.0)) for p in P]
        F.route_styled(buf, s, route, col, phase=0.42 + i * 0.11,
                       rng=np.random.default_rng(11 + i),
                       style=style,
                       nfib=9, spread=17.0, fib_amp=0.055,
                       wob=1.9, freq=1.4, grow=1.2, steps=520,
                       packets=2, packet_w=0.07, env="tight")

    light = F.bloom(buf, s, scales=(1.7, 5.2, 16.0), weights=(0.42, 0.20, 0.10))
    bg = np.zeros((Hp, Wp, 3), np.float32)
    bg[..., 2] = 0.014
    img = Image.fromarray(F.tonemap(light, gain=2.2, bg=bg), "RGB")
    img = img.resize((W, H), Image.LANCZOS)

    d = ImageDraw.Draw(img)
    fb = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 13)
    fs = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 11)
    d.text((14, 10), "PARTICLE GRAMMAR TEMPLATES  (fibre.py STYLE_PRESETS)", font=fb, fill=(190, 225, 245))
    d.text((14, 29), "用 fibre.route_styled(..., style=\"pulse|missile|clump|bead\") 一行切换",
           font=fs, fill=(120, 152, 172))
    for i, (label, _s, _c) in enumerate(STYLES):
        d.text((16, 74 + i * 120), label, font=fb, fill=(175, 205, 225))
    return img


if __name__ == "__main__":
    im = render()
    p = os.path.join(OUT, "detail-style-templates.png")
    im.save(p)
    print("wrote", p, im.size)
