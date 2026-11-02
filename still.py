# -*- coding: utf-8 -*-
"""
still.py — one static frame of the nginx photon-flow field.

Deliberately NOT an animation and deliberately NOT tuned for taste: it exists so
the lines and the nebula can be looked at before anyone argues about motion.

Built strictly on the reference modules:
    fibre.py    route()  -> multi-fibre bundles, travelling pulses, tone curve
    galaxy.py   gas / nucleus / stars -> the disc, as a density field
so the amplitudes are scene3.py's amplitudes and the tone curve is the one the
old renderer actually used.

    python still.py [out.png] [t]
"""
import os
import sys
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILL = r"C:\Users\31807\opencode-dotfiles\skills\photon-flow-viz\scripts"
sys.path.insert(0, _SKILL)

import fibre as F          # noqa: E402
import galaxy as G         # noqa: E402

# ------------------------------------------------------------------ layout
LW, LH = 1600.0, 900.0
CX, CY = LW * 0.5, LH * 0.5
R = 150.0
TILT = 0.84
CLIENT_X = 110.0
CARD_X = LW - 300.0
CARD_W, CARD_H = 240.0, 62.0
ROW_TOP = 26.0 + CARD_H / 2
ROW_BOT = LH - 26.0 - CARD_H / 2
ENTER_SPREAD = 1.5          # rad of left arc the four clients enter through
PORT_DEG = (-41.0, -15.0, 15.0, 41.0)
DISSOLVE_IN, DISSOLVE_OUT = 0.55, 0.95   # radial mask on the line buffer

CLIENTS = [("browsers", "h2 / keepalive 64", 5180, (96, 186, 240)),
           ("mobile", "h2 / tls resume", 4120, (92, 214, 184)),
           ("api partners", "http/1.1 / signed", 2460, (118, 158, 236)),
           ("scrapers", "no token / 640 r/s", 640, (232, 132, 112))]
UPSTREAMS = [("app-01", "10.0.0.11:8081", 0.34, (74, 226, 172)),
             ("app-02", "10.0.0.12:8082", 0.28, (224, 178, 66)),
             ("app-03", "10.0.0.13:8083", 0.24, (150, 136, 242)),
             ("app-04", "10.0.0.14:8084", 0.14, (228, 114, 162))]

FD = r"C:\Windows\Fonts"
_fc = {}


def font(name, size):
    key = (name, int(max(6, size)))
    if key not in _fc:
        p = os.path.join(FD, name)
        _fc[key] = ImageFont.truetype(p if os.path.exists(p) else "msyh.ttc", key[1])
    return _fc[key]


def rows(n):
    if n == 1:
        return [CY]
    return [ROW_TOP + (i / (n - 1.0)) * (ROW_BOT - ROW_TOP) for i in range(n)]


CLIENT_Y = rows(len(CLIENTS))
UP_Y = rows(len(UPSTREAMS))
TOT_IN = float(sum(c[2] for c in CLIENTS))


def port(i):
    a = math.radians(PORT_DEG[i])
    return (CX + R * math.cos(a), CY + R * math.sin(a) * TILT)


def p_in(i):
    """client chip -> a point 0.70R inside the disc on the entry bearing."""
    y = CLIENT_Y[i]
    entA = math.pi + ((i - (len(CLIENTS) - 1) / 2.0) / max(1, len(CLIENTS) - 1)) * ENTER_SPREAD
    ex = CX + 0.70 * R * math.cos(entA)
    ey = CY + 0.70 * R * math.sin(entA) * TILT
    return [(CLIENT_X + 24.0, y),
            (CLIENT_X + 200.0, y + (CY - y) * 0.42),
            (CX - R * 2.02, CY + (y - CY) * 0.20),
            (ex, ey)]


def p_out(i):
    """0.55R on the egress bearing -> outward along that radius -> card edge."""
    u = UPSTREAMS[i]
    y = UP_Y[i]
    a = math.radians(PORT_DEG[i])
    def rp(f):
        return (CX + R * f * math.cos(a), CY + R * f * math.sin(a) * TILT)
    x1, y1 = rp(0.55)
    x2, y2 = rp(0.92)
    px, py = port(i)
    return [(x1, y1), (x2, y2),
            (px + 130.0, py + (y - py) * 0.44),
            (CARD_X - 2.0, y)]


# ------------------------------------------------------------------ backdrop
def base_bg(W, H):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx, ny = xx / (W - 1), yy / (H - 1)
    g = np.empty((H, W, 3), np.float32)
    g[..., 0] = 0.0080 + 0.0125 * (1 - ny)
    g[..., 1] = 0.0115 + 0.0175 * (1 - ny)
    g[..., 2] = 0.0220 + 0.0285 * (1 - ny)
    d2 = ((nx - 0.47) * 1.05) ** 2 + ((ny - 0.51) * 0.58) ** 2
    g += np.exp(-d2 / 0.17).astype(np.float32)[..., None] * np.array([0.020, 0.033, 0.056], np.float32)
    vx, vy = (nx - 0.5) * 2.0, (ny - 0.5) * 2.0
    g *= np.clip(1.0 - 0.60 * (vx * vx * 0.40 + vy * vy * 0.90), 0.14, 1.0)[..., None]
    step = max(8, int(38 * (W / 1600.0)))
    m = np.zeros((H, W), np.float32)
    m[::step, ::step] = 1.0
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(max(1.0, step * 0.13))), np.float32) / 255.0
    g += m[..., None] * np.array([0.030, 0.044, 0.062], np.float32)
    return g


from PIL import ImageFilter  # noqa: E402  (used above)


def render(t=3.0, out_w=1600, seed=7):
    rng = np.random.default_rng(seed)
    s = (out_w / LW) * 2.0
    W, H = int(round(LW * s)), int(round(LH * s))
    buf = np.zeros((H, W, 3), np.float32)

    # ---------------- nebula: the disc is a galaxy, not a ring ----------
    # amplitude chosen so the *unlit* disc already fills the frame; the light
    # front and the core sit on top of it.
    G.gas_layer(buf, s, CX, CY, R, phase=0.0, arms=2, reach=1.22,
                intensity=0.62, seed=11, tilt_cos=TILT)
    G.dust_layer(buf, s, CX, CY, R, phase=0.0, strength=0.55, seed=11,
                 tilt_cos=TILT)
    G.star_layer(buf, s, CX, CY, R, phase=0.0, count=5200, seed=11,
                 reach=1.18, tilt_cos=TILT)
    G.nucleus_layer(buf, s, CX, CY, R, phase=0.0, intensity=0.70, seed=11,
                    tilt_cos=TILT)

    # ---------------- flow: scene3's amplitudes --------------------------
    for i, (label, spec, rps, col) in enumerate(CLIENTS):
        share = rps / TOT_IN
        F.route(buf, s, p_in(i), tuple(v / 255.0 for v in col),
                (t * 0.22 + 0.11 * i) % 1.0, rng,
                nfib=max(2, int(round(3 + 5 * share * 5))),
                spread=11.0, fib_amp=0.30,
                pulse=max(2, min(5, int(round(2 + 6 * share)))),
                wob=1.6, freq=1.25, grow=0.9, steps=700,
                packets=2, packet_w=0.085, taper=0.11, env="tight")

    for i, (name, host, wgt, col) in enumerate(UPSTREAMS):
        F.route(buf, s, p_out(i), tuple(v / 255.0 for v in col),
                (t * 0.26 + 0.23 * i) % 1.0, rng,
                nfib=max(3, int(round(16 * wgt * 1.6))),
                spread=26.0 * (0.45 + wgt) * (0.72 if i == 0 else 1.0),
                fib_amp=0.32,
                pulse=max(2, min(6, int(round(2 + 8 * wgt)))),
                wob=2.8, freq=1.35, grow=1.7, steps=940,
                packets=2, packet_w=0.075, taper=0.11, env="open")

    # ---------------- dissolve the lanes into the disc ------------------
    # One radial mask over the whole line field: 0 by 0.55R, full by 0.95R.
    # Nothing may stop at a visible edge, so the lanes end *inside* gas that is
    # already brighter than they are.
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    rr = np.hypot((xx / s - CX), (yy / s - CY) / TILT) / R
    m = np.clip((rr - DISSOLVE_IN) / (DISSOLVE_OUT - DISSOLVE_IN), 0.0, 1.0)
    m = (m * m * (3 - 2 * m)).astype(np.float32)
    buf *= m[..., None]

    # ---------------- bloom + tone (exactly scene3's chain) -------------
    light = F.bloom(buf, s, scales=(2.0, 6.5, 20.0), weights=(0.52, 0.26, 0.15))
    img = Image.fromarray(F.tonemap(light, gain=1.95, bg=base_bg(W, H)), "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    lab = lambda z: font("consola.ttf", z * s)
    labb = lambda z: font("consolab.ttf", z * s)
    stroke = dict(stroke_width=max(2, int(2.4 * s)), stroke_fill=(5, 9, 15, 235))

    # ---------------- chrome --------------------------------------------
    for i, (label, spec, rps, col) in enumerate(CLIENTS):
        y = CLIENT_Y[i]
        d.arc([(CLIENT_X - 15) * s, (y - 15) * s, (CLIENT_X + 15) * s, (y + 15) * s],
              200, 340, fill=(col[0], col[1], col[2], 190), width=max(1, int(1.6 * s)))
        d.ellipse([(CLIENT_X - 5) * s, (y - 5) * s, (CLIENT_X + 5) * s, (y + 5) * s],
                  fill=(col[0], col[1], col[2], 220))
        d.text(((CLIENT_X + 26) * s, (y - 16) * s), label, font=labb(12.5),
               fill=col, anchor="la", **stroke)
        d.text(((CLIENT_X + 26) * s, (y + 2) * s), "%d r/s  %s" % (rps, spec),
               font=lab(10.5), fill=(126, 158, 178), anchor="la")

    for i, (name, host, wgt, col) in enumerate(UPSTREAMS):
        y = UP_Y[i]
        d.rounded_rectangle([CARD_X * s, (y - CARD_H / 2) * s,
                             (CARD_X + CARD_W) * s, (y + CARD_H / 2) * s],
                            radius=int(8 * s), fill=(6, 11, 19, 120),
                            outline=(col[0], col[1], col[2], 150),
                            width=max(1, int(1.3 * s)))
        d.line([CARD_X * s, (y - 9) * s, CARD_X * s, (y + 9) * s],
               fill=(col[0], col[1], col[2], 240), width=max(2, int(3 * s)))
        d.text(((CARD_X + 14) * s, (y - 17) * s), name, font=labb(13),
               fill=col, anchor="la", **stroke)
        d.text(((CARD_X + 14) * s, (y + 2) * s), host, font=lab(10.5),
               fill=(126, 158, 178), anchor="la")
        d.text(((CARD_X + 14) * s, (y + 16) * s), "%.0f%%  %d r/s" % (wgt * 100, round(wgt * 8320)),
               font=lab(10), fill=(96, 124, 142), anchor="la")

    d.text((28 * s, 20 * s), "NGINX  ·  photon flow", font=font("msyhbd.ttc", 22 * s),
           fill=(236, 246, 252), anchor="la")
    d.text((30 * s, 52 * s), "static frame  ·  t=%.2fs  ·  4 clients → edge → 4 upstreams"
           % t, font=font("msyh.ttc", 12 * s), fill=(112, 140, 158), anchor="la")

    return img.resize((out_w, int(round(out_w * LH / LW))), Image.LANCZOS)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "out", "still.png")
    t = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    im = render(t=t)
    im.save(out)
    print("wrote", out, im.size)
