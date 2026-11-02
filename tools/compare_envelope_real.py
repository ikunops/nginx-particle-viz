# -*- coding: utf-8 -*-
"""
Compare the three envelope modes on the REAL scene, not a synthetic path.

Renders the same frame (life-01: burst + eject state) three times, changing only
ENVELOPE_MODES for the trunk, then crops the trunk corridor from each so the
difference is visible at 1:1.

This is the check I owed from last round: the earlier envelope sheet was drawn
on a made-up route, which cannot tell you how it behaves with 18 fibres packed
into the real 54px-wide trunk.
"""
import os, sys, io
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene3 as S

OUT = os.path.join(HERE, "out")

MODES = [
    ("tight  gather-spread-gather", {"trunk_a": "tight", "trunk_b": "tight"}),
    ("flat   constant width",       {"trunk_a": "flat",  "trunk_b": "flat"}),
    ("open   spread then gather",   {"trunk_a": "open",  "trunk_b": "open"}),
]

# the trunk runs from x=312 to x=698 at y~450; crop generously
CROP = (250, 380, 760, 520)


def render_with(overrides, out_w=1600):
    saved = dict(S.ENVELOPE_MODES)
    try:
        S.ENVELOPE_MODES.update(overrides)
        st = dict(S.FRAMES[1])          # burst + eject: busiest trunk
        return S.render(st, out_w=out_w)
    finally:
        S.ENVELOPE_MODES.clear()
        S.ENVELOPE_MODES.update(saved)


def main():
    panels = []
    for label, ov in MODES:
        img = render_with(ov)
        crop = img.crop(CROP)
        # 2x for inspection
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        panels.append((label, crop))
        print("rendered", label)

    fb = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 17)
    fs = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 13)
    pad = 14
    w = panels[0][1].width
    h = panels[0][1].height
    sheet = Image.new("RGB", (w + pad * 2, (h + 52) * len(panels) + pad), (6, 8, 13))
    d = ImageDraw.Draw(sheet)
    y = pad
    for label, im in panels:
        d.text((pad, y), label, font=fb, fill=(165, 215, 240))
        d.text((pad, y + 20), "real scene, trunk corridor, 2x", font=fs, fill=(110, 140, 158))
        sheet.paste(im, (pad, y + 40))
        y += h + 52
    p = os.path.join(OUT, "detail-envelope-real.png")
    sheet.save(p)
    print("wrote", p, sheet.size)


if __name__ == "__main__":
    main()
