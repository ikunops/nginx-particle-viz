# -*- coding: utf-8 -*-
"""
nginx edge visualization with in-node request lifecycle.

Rendered twice from the same engine, at two reasoning-effort levels of
authorship, so the two frames can be compared directly:

  HIGH  quick pass - accept and reject only. One hue, straight bundles,
        one bloom scale, minimal labels, no metrics. ~0.5 s/frame.
  MAX   deep pass  - the full edge lifecycle is modelled and drawn:
          distribute   ingress fans out to four egress ports; each port's
                       particle density is proportional to its least_conn share
          cache hit    hairpin inside the node, then an express lane back to
                       the client - never reaches an upstream
          filter       deny rule absorbs the request at the core
          reject       4xx / 429 is turned around toward the client
          retry        a failing upstream hands the request back to the node,
                       which re-dispatches it to another port
          backpressure a small amber queue at the ingress while rate limited
        Per-upstream hue, wobbled fibres, three bloom scales, legend,
        live counters, and an arithmetic that closes:
        12.4k in = 9.73k to pool + 2.48k cache + 236 rejected + 50 denied
"""
import os, sys, time, math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fibre as F

OUT = os.path.join(HERE, "out")
FD = r"C:\Windows\Fonts"
F_MSYH, F_MSYHB = os.path.join(FD, "msyh.ttc"), os.path.join(FD, "msyhbd.ttc")
F_MONO, F_MONOB = os.path.join(FD, "consola.ttf"), os.path.join(FD, "consolab.ttf")
_fc = {}


def font(path, size):
    k = (path, int(max(6, size)))
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path if os.path.exists(path) else F_MSYH, k[1])
    return _fc[k]


# ------------------------------------------------------------------ layout
LW, LH = 1600.0, 900.0
CLIENT = (208.0, 450.0)
NGINX = (768.0, 450.0)
NG_R = 108.0
BOX_L, BOX_W, BOX_H = 1160.0, 250.0, 82.0
BACK_YS = [148.0, 348.0, 548.0, 748.0]

RPS = (3300, 2750, 2380, 1300)
CACHE_RPS, REJ_RPS, DENY_RPS = 2480, 236, 50
TOTAL_RPS = sum(RPS) + CACHE_RPS + REJ_RPS + DENY_RPS

PORT_DEG = (-41.0, -15.0, 15.0, 41.0)


def port(i, rr=None):
    a = math.radians(PORT_DEG[i])
    r = NG_R if rr is None else rr
    return (NGINX[0] + r * math.cos(a), NGINX[1] + r * math.sin(a))


P_CLI = [(64.0, 450.0), (112.0, 412.0), (164.0, 488.0), (CLIENT[0] - 38, 450.0)]
P_EDGE = [(CLIENT[0] + 96, 450.0), (392.0, 380.0), (540.0, 522.0),
          (NGINX[0] - NG_R, 450.0)]

# inside the node: ingress -> egress port (the distribution comb)
def p_comb(i):
    px, py = port(i)
    ix, iy = NGINX[0] - NG_R + 6, NGINX[1]
    return [(ix, iy),
            (ix + 62.0, iy + (py - iy) * 0.42),
            (px - 52.0, py + (iy - py) * 0.18),
            (px - 4.0, py)]


# cache hairpin: enters, bounces off the store, exits upward
P_CACHE = [(NGINX[0] - NG_R + 6, 442.0),
           (NGINX[0] - 8.0, 372.0),
           (NGINX[0] + 62.0, 366.0),
           (NGINX[0] + 58.0, 424.0)]
# ... then the express lane back to the client (upper corridor)
P_RET = [(676.0, 398.0), (560.0, 334.0), (330.0, 330.0), (CLIENT[0] + 8, 396.0)]

# reject: turned around, lower corridor back to the client
P_REJ = [(676.0, 502.0), (560.0, 568.0), (330.0, 572.0), (CLIENT[0] + 8, 504.0)]

# deny: absorbed at the core - short stub that dies inside the ring
P_DENY = [(664.0, 466.0),
          (700.0, 502.0),
          (726.0, 524.0),
          (740.0, 534.0)]


def p_redis(i, j):
    """re-dispatch: leaves port i, swings outside the disc, re-enters port j"""
    p0, p3 = port(i, NG_R * 1.30), port(j, NG_R * 1.30)
    return [p0,
            (NGINX[0] + NG_R * 1.92, p0[1] + (p3[1] - p0[1]) * 0.30),
            (NGINX[0] + NG_R * 1.92, p3[1] - (p3[1] - p0[1]) * 0.30),
            p3]


def p_up(i):
    y = BACK_YS[i]
    px, py = port(i)
    return [(px, py),
            (px + 92.0, py + (y - py) * 0.28),
            (1016.0, y - (y - NGINX[1]) * 0.10),
            (BOX_L - 18.0, y)]


COL_IN = (0.50, 0.74, 1.00)
COL_EDGE = (0.26, 0.84, 1.00)
COL_UP = [(0.28, 1.00, 0.68), (1.00, 0.72, 0.26), (0.62, 0.56, 1.00), (1.00, 0.40, 0.60)]
COL_MONO = (0.34, 0.82, 1.00)
COL_CACHE = (0.62, 1.00, 0.92)
COL_REJ = (1.00, 0.33, 0.25)
COL_DENY = (0.44, 0.52, 0.62)
COL_RETRY = (1.00, 0.70, 0.26)
COL_BACK = (0.96, 0.99, 1.00)


# ------------------------------------------------------------------ backdrop
_BG = {}


def base_bg(W, H):
    if (W, H) in _BG:
        return _BG[(W, H)].copy()
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx, ny = xx / (W - 1), yy / (H - 1)
    g = np.empty((H, W, 3), np.float32)
    g[..., 0] = 0.0085 + 0.0130 * (1 - ny)
    g[..., 1] = 0.0120 + 0.0180 * (1 - ny)
    g[..., 2] = 0.0225 + 0.0290 * (1 - ny)
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
    _BG[(W, H)] = g
    return g.copy()


def add_blob(buf, gx, gy, gr, ga, col, s):
    H, W = buf.shape[:2]
    cx, cy = gx * s, gy * s
    rad = int(gr * s * 2.4) + 2
    xs = np.arange(int(cx) - rad, int(cx) + rad + 1, dtype=np.float32)
    ys = np.arange(int(cy) - rad, int(cy) + rad + 1, dtype=np.float32)
    gx_ = np.exp(-((xs - cx) / (gr * s)) ** 2 * 2.0)
    gy_ = np.exp(-((ys - cy) / (gr * s)) ** 2 * 2.0)
    g = np.outer(gy_, gx_) * ga
    x0, x1 = max(0, int(xs[0])), min(W, int(xs[-1]) + 1)
    y0, y1 = max(0, int(ys[0])), min(H, int(ys[-1]) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    sub = g[(y0 - int(ys[0])):(y1 - int(ys[0])), (x0 - int(xs[0])):(x1 - int(xs[0]))]
    for c in range(3):
        buf[y0:y1, x0:x1, c] += sub * col[c]


# ------------------------------------------------------------------ render
def render(variant="max", out_w=1600, phase=0.0, tlabel="0.00", seed=7):
    deep = variant == "max"
    rng = np.random.default_rng(seed)
    s = (out_w / LW) * (2.0 if deep else 1.4)
    W, H = int(round(LW * s)), int(round(LH * s))
    NB = len(BACK_YS)
    up_cols = COL_UP if deep else [COL_MONO] * NB
    wsum = float(sum(RPS))
    wgt = [r / wsum for r in RPS]

    buf = np.zeros((H, W, 3), np.float32)

    add_blob(buf, CLIENT[0], CLIENT[1], 132.0, 0.12, (0.14, 0.40, 0.58), s)
    add_blob(buf, NGINX[0], NGINX[1], 200.0, 0.20 if deep else 0.15, (0.12, 0.38, 0.56), s)
    for i, y in enumerate(BACK_YS):
        add_blob(buf, 1262.0, y, 96.0, 0.09, tuple(0.5 * v for v in up_cols[i]), s)

    # ---- ingress
    F.route(buf, s, P_CLI, COL_IN, phase + 0.26, rng,
            nfib=9 if deep else 4, spread=14.0 if deep else 10.0,
            fib_amp=0.11, beads=32 if deep else 8, bead_amp=6.5,
            bead_len=0.10, bead_r=1.55, wob=2.0 if deep else 0.0,
            freq=1.25, grow=0.9, steps=760,
            packets=2 if deep else 0, packet_w=0.085, taper=0.13)

    F.route(buf, s, P_EDGE, COL_EDGE, phase, rng,
            nfib=18 if deep else 6, spread=32.0 if deep else 16.0,
            fib_amp=0.15 if deep else 0.26,
            beads=64 if deep else 16, bead_amp=9.0 if deep else 6.0,
            bead_len=0.075, bead_r=1.7,
            wob=3.2 if deep else 0.0, freq=1.4, grow=1.5, steps=1000,
            packets=3 if deep else 0, packet_w=0.070, taper=0.11)

    # ---- node interior: distribution comb (density follows share)
    for i in range(NB):
        F.route(buf, s, p_comb(i), COL_EDGE, phase + 0.05 * i, rng,
                nfib=5 if deep else 2, spread=5.5 if deep else 3.0,
                fib_amp=0.10 if deep else 0.15,
                beads=max(2, int(round(10 * wgt[i] * 1.6))) if deep else 2,
                bead_amp=5.5 if deep else 4.0,
                bead_len=0.10, bead_r=1.25,
                wob=0.8 if deep else 0.0, freq=1.6, grow=1.0, steps=380,
                packets=1 if deep else 0, packet_w=0.10, taper=0.10)

    if deep:
        F.route(buf, s, P_CACHE, COL_CACHE, phase + 0.10, rng,
                nfib=5, spread=7.0, fib_amp=0.16,
                beads=9, bead_amp=7.5, bead_len=0.085, bead_r=1.45,
                wob=1.2, freq=1.7, grow=1.0, steps=440,
                packets=1, packet_w=0.09, taper=0.11)
        F.route(buf, s, P_RET, COL_CACHE, phase + 0.40, rng,
                nfib=7, spread=10.0, fib_amp=0.15,
                beads=14, bead_amp=7.5, bead_len=0.070, bead_r=1.5,
                wob=1.6, freq=1.4, grow=1.0, steps=620,
                packets=2, packet_w=0.075, taper=0.10)

        F.route(buf, s, P_DENY, COL_DENY, phase + 0.72, rng,
                nfib=5, spread=7.0, fib_amp=0.11,
                beads=5, bead_amp=3.4, bead_len=0.055, bead_r=1.15,
                wob=0.8, freq=1.9, grow=1.0, steps=300,
                packets=1, packet_w=0.12, taper=0.09)

    # ---- reject: turned around toward the client
    F.route(buf, s, P_REJ, COL_REJ, phase * 1.35 + 0.5, rng,
            nfib=5 if deep else 3, spread=8.0 if deep else 6.0,
            fib_amp=0.10 if deep else 0.16,
            beads=9 if deep else 4, bead_amp=6.2 if deep else 5.0,
            bead_len=0.070 if deep else 0.06, bead_r=1.35,
            wob=1.0 if deep else 0.0, freq=1.9, grow=1.0, steps=520,
            packets=1 if deep else 0, packet_w=0.10, taper=0.10)

    if deep:
        # retry: upstream hands it back, node re-dispatches
        F.route(buf, s, p_up(2), COL_RETRY, phase * 1.15 + 0.30, rng,
                nfib=3, spread=6.0, fib_amp=0.07,
                beads=5, bead_amp=4.6, bead_len=0.065, bead_r=1.3,
                wob=0.8, freq=1.6, grow=1.0, steps=640,
                packets=0, packet_w=0.1, taper=0.13, back=True)
        F.route(buf, s, p_redis(2, 0), COL_RETRY, phase * 1.15 + 0.58, rng,
                nfib=3, spread=5.0, fib_amp=0.08,
                beads=5, bead_amp=5.4, bead_len=0.075, bead_r=1.3,
                wob=0.6, freq=1.8, grow=1.0, steps=360,
                packets=0, packet_w=0.1, taper=0.11)

    # ---- egress fans
    for i in range(NB):
        F.route(buf, s, p_up(i), up_cols[i], phase + 0.23 * i, rng,
                nfib=max(3, int(round(16 * wgt[i] * 1.6))) if deep else 6,
                spread=(26.0 * (0.45 + wgt[i])) if deep else 14.0,
                fib_amp=0.13 if deep else 0.24,
                beads=max(4, int(round(58 * wgt[i] * 1.6))) if deep else 13,
                bead_amp=8.2 if deep else 5.6,
                bead_len=0.072, bead_r=1.65 if deep else 1.6,
                wob=2.8 if deep else 0.0, freq=1.35, grow=1.7, steps=980,
                packets=2 if deep else 0, packet_w=0.075, taper=0.12)

        if deep:
            F.route(buf, s, p_up(i), COL_BACK, phase + 0.56 + 0.15 * i, rng,
                    nfib=5, spread=14.0, fib_amp=0.05,
                    beads=14, bead_amp=2.6, bead_len=0.055, bead_r=1.25,
                    wob=1.6, freq=1.25, grow=1.0, steps=820,
                    packets=1, packet_w=0.09, taper=0.13, back=True)

    # ---- backpressure queue at the ingress
    if deep:
        for k in range(4):
            a = 0.5 + 0.5 * math.sin(2 * math.pi * (phase * 1.2 - k * 0.18))
            add_blob(buf, NGINX[0] - NG_R - 40.0 - k * 13.0,
                     NGINX[1] + 66.0 + math.sin(k * 2.1) * 6.0,
                     5.0 + 2.0 * a, 0.9 * a + 0.1, (1.0, 0.62, 0.24), s)

    # ---- bloom + tone map
    if deep:
        light = F.bloom(buf, s, scales=(2.0, 6.5, 20.0), weights=(0.52, 0.26, 0.15))
    else:
        light = F.bloom(buf, s, scales=(2.2, 7.0), weights=(0.50, 0.0))
    img = Image.fromarray(F.tonemap(light, gain=1.95 if deep else 1.80,
                                    bg=base_bg(W, H)), "RGB")
    d = ImageDraw.Draw(img, "RGBA")

    # ---- structure guides
    def guide(P, colr, dash=16, wdt=1.1):
        pts = F.bez(P, np.linspace(0, 1, 340))
        for i in range(len(pts) - 1):
            if (i // dash) % 2 == 0:
                d.line([(pts[i, 0] * s, pts[i, 1] * s),
                        (pts[i + 1, 0] * s, pts[i + 1, 1] * s)],
                       fill=colr, width=max(1, int(wdt * s)))

    guide(P_CLI, (56, 94, 118, 30))
    guide(P_EDGE, (58, 98, 122, 40))
    for i in range(NB):
        guide(p_up(i), (56, 94, 118, 34))
    if deep:
        guide(P_RET, (56, 116, 112, 30))
        guide(P_REJ, (128, 58, 50, 44))

    # ---- client cluster
    cx0, cy0 = CLIENT
    for rr, aa in ((66, 15), (52, 28), (40, 44)):
        d.arc([(cx0 - rr) * s, (cy0 - rr) * s, (cx0 + rr) * s, (cy0 + rr) * s],
              205 + phase * 80, 335 + phase * 80, fill=(98, 208, 240, aa),
              width=max(1, int(1.6 * s)))
    for (ox, oy, r) in ((-12, 3, 24), (12, -5, 27), (1, 14, 20)):
        d.ellipse([(cx0 + ox - r) * s, (cy0 + oy - r) * s,
                   (cx0 + ox + r) * s, (cy0 + oy + r) * s],
                  outline=(106, 212, 242, 108), width=max(1, int(1.7 * s)))

    # ---- nginx node
    cx, cy = NGINX
    for rr, aa in ((1.62, 14), (1.34, 32), (1.13, 58)):
        d.arc([(cx - NG_R * rr) * s, (cy - NG_R * rr) * s,
               (cx + NG_R * rr) * s, (cy + NG_R * rr) * s],
              0, 360, fill=(74, 190, 230, aa), width=max(1, int(1.2 * s)))
    d.ellipse([(cx - NG_R) * s, (cy - NG_R) * s, (cx + NG_R) * s, (cy + NG_R) * s],
              outline=(140, 238, 255, 158), width=max(1, int(2.2 * s)))
    d.ellipse([(cx - NG_R * 0.88) * s, (cy - NG_R * 0.88) * s,
               (cx + NG_R * 0.88) * s, (cy + NG_R * 0.88) * s],
              fill=(7, 30, 46, 116), outline=(66, 158, 192, 92),
              width=max(1, int(1.2 * s)))

    if deep:
        sel = int((phase * 4.0) % 4)
        for i in range(NB):
            a = PORT_DEG[i]
            px, py = port(i, NG_R * 0.98)
            cc = tuple(int(min(255, v * 255)) for v in COL_UP[i])
            hot = 1.0 if i == sel else 0.0
            d.arc([(cx - NG_R * 1.02) * s, (cy - NG_R * 1.02) * s,
                   (cx + NG_R * 1.02) * s, (cy + NG_R * 1.02) * s],
                  a - 7.0, a + 7.0,
                  fill=(min(255, int(cc[0] * 0.55 + 130 * hot)),
                        min(255, int(cc[1] * 0.55 + 130 * hot)),
                        min(255, int(cc[2] * 0.55 + 130 * hot)), 238),
                  width=max(2, int(5.0 * s)))
            r = (2.6 + 5.0 * wgt[i] * 3 + (2.4 if i == sel else 0.0)) * s
            d.ellipse([px * s - r, py * s - r, px * s + r, py * s + r],
                      fill=(min(255, cc[0] + 80), min(255, cc[1] + 80),
                            min(255, cc[2] + 80), 240))
        # cache store glyph inside the node
        sx, sy = cx + 20 * s, cy - 34 * s
        d.rounded_rectangle([sx - 15 * s, sy - 9 * s, sx + 15 * s, sy + 9 * s],
                            radius=int(4 * s), outline=(150, 255, 235, 150),
                            width=max(1, int(1.5 * s)))
        # worker ticks
        for k in range(8):
            a = math.radians(k * 45.0 + 12.0)
            r0, r1 = NG_R * 0.60, NG_R * 0.70
            d.line([(cx + r0 * math.cos(a)) * s, (cy + r0 * math.sin(a)) * s,
                    (cx + r1 * math.cos(a)) * s, (cy + r1 * math.sin(a)) * s],
                   fill=(120, 190, 214, 100), width=max(1, int(1.4 * s)))
        # ingress marker
        d.arc([(cx - NG_R * 1.04) * s, (cy - NG_R * 1.04) * s,
               (cx + NG_R * 1.04) * s, (cy + NG_R * 1.04) * s],
              -10.0, 10.0, fill=(150, 235, 255, 235), width=max(2, int(5.0 * s)))
    else:
        for i in range(NB):
            px, py = port(i, NG_R * 0.98)
            r = 2.0 * s
            d.ellipse([px * s - r, py * s - r, px * s + r, py * s + r],
                      fill=(150, 220, 245, 195))

    a0 = (phase * 360 + 16) % 360
    for off, spn, wd in ((0, 56, 3), (150, 36, 2), (250, 22, 2)):
        d.arc([(cx - NG_R * 1.14) * s, (cy - NG_R * 1.14) * s,
               (cx + NG_R * 1.14) * s, (cy + NG_R * 1.14) * s],
              a0 + off, a0 + off + spn, fill=(180, 248, 255, 170),
              width=max(1, int(wd * s)))

    # ---- upstream cards
    for i, y in enumerate(BACK_YS):
        cc = tuple(int(min(255, v * 255)) for v in up_cols[i])
        box = [BOX_L * s, (y - BOX_H / 2) * s, (BOX_L + BOX_W) * s, (y + BOX_H / 2) * s]
        d.rounded_rectangle(box, radius=int(12 * s), fill=(6, 11, 19, 158),
                            outline=(cc[0] // 3, cc[1] // 3, cc[2] // 3, 178),
                            width=max(1, int(1.5 * s)))
        d.rounded_rectangle([box[0], box[1], box[0] + 4.5 * s, box[3]],
                            radius=int(3 * s), fill=(cc[0], cc[1], cc[2], 178))
        d.ellipse([(BOX_L - 8) * s, (y - 4.5) * s, (BOX_L + 1) * s, (y + 4.5) * s],
                  fill=(cc[0], cc[1], cc[2], 210))
        d.text(((BOX_L + 17) * s, (y - 26) * s), "app-0%d" % (i + 1),
               font=font(F_MONOB, 16.5 * s), fill=(238, 248, 254), anchor="la")
        d.text(((BOX_L + 17) * s, (y - 6) * s), "10.0.0.1%d:808%d" % (i + 1, i + 1),
               font=font(F_MONO, 12.5 * s), fill=(132, 164, 182), anchor="la")
        if deep:
            bw = (BOX_W - 38) * s
            d.text(((BOX_L + 17) * s, (y + 13) * s),
                   "%d req/s   %.0f%% of pool" % (RPS[i], wgt[i] * 100),
                   font=font(F_MONO, 11.5 * s), fill=(104, 136, 154), anchor="la")
            d.rectangle([(BOX_L + 17) * s, (y + 28) * s,
                         (BOX_L + 17) * s + bw, (y + 32) * s], fill=(20, 32, 44, 235))
            d.rectangle([(BOX_L + 17) * s, (y + 28) * s,
                         (BOX_L + 17) * s + bw * wgt[i] * 3.0, (y + 32) * s],
                        fill=(cc[0], cc[1], cc[2], 180))

    # ---- node callouts (MAX only)
    lab = lambda z: font(F_MONO, z * s)
    stroke = dict(stroke_width=max(2, int(2.6 * s)), stroke_fill=(5, 9, 15, 240)) if deep else {}

    if deep:
        def callout(tx, ty, ax, ay, text, colr, anchor="la"):
            d.line([(tx * s, ty * s), (ax * s, ay * s)], fill=colr,
                   width=max(1, int(1.2 * s)))
            d.ellipse([(ax - 2.4) * s, (ay - 2.4) * s, (ax + 2.4) * s, (ay + 2.4) * s],
                      fill=colr)
            d.text((tx * s, ty * s), text, font=lab(12), fill=colr,
                   anchor=anchor, **stroke)

        cc = tuple(int(min(255, v * 255)) for v in COL_CACHE)
        callout(432.0, 300.0, 616.0, 314.0, "cache hit  \u2192  express back to client", cc)
        rc = tuple(int(min(255, v * 255)) for v in COL_REJ)
        callout(374.0, 616.0, 560.0, 576.0, "reject 4xx / 429  \u2192  turned around", rc)
        dc = tuple(int(min(255, v * 255)) for v in COL_DENY)
        callout(700.0, 566.0, 738.0, 536.0, "filter / deny  \u2192  absorbed", dc, anchor="la")
        tc = tuple(int(min(255, v * 255)) for v in COL_RETRY)
        callout(1006.0, 424.0, 962.0, 424.0, "retry \u2192 re-dispatch", tc, anchor="la")

    # ---- node labels
    d.text((cx * s, (cy - 26) * s), "nginx", font=font(F_MSYHB, 22 * s),
           fill=(228, 253, 255), anchor="mm", **stroke)
    d.text((cx * s, (cy - 4) * s), "edge", font=lab(11.0),
           fill=(124, 206, 232), anchor="mm", **stroke)
    d.text((cx * s, (cy + 13) * s), "cache 20%" if deep else "proxy",
           font=lab(10.0), fill=(150, 226, 214) if deep else (112, 162, 184),
           anchor="mm", **stroke)
    if deep:
        d.text((cx * s, (cy + NG_R * 1.60) * s),
               "least_conn / keepalive 64 / gzip", font=lab(11.5),
               fill=(106, 152, 174), anchor="mm", **stroke)
        d.text((cx * s, (cy - NG_R * 1.58) * s),
               "tls 1.3 / h2", font=lab(11.5), fill=(106, 152, 174),
               anchor="mm", **stroke)

    d.text((cx0 * s, (cy0 + 56) * s), "clients", font=font(F_MSYH, 15.5 * s),
           fill=(204, 240, 250), anchor="mm")
    d.text((cx0 * s, (cy0 + 80) * s),
           "12.4k req/s" if deep else "requests", font=lab(12),
           fill=(110, 188, 210), anchor="mm")

    # ---- header / legend
    d.text((52 * s, 46 * s), "NGINX  /  PHOTON FLOW",
           font=font(F_MSYHB, 26 * s), fill=(242, 251, 255), anchor="la")
    d.text((52 * s, 80 * s),
           "client  \u2192  edge  \u2192  upstream pool" if deep
           else "client \u2192 nginx \u2192 upstream",
           font=lab(13.5 if deep else 12.5), fill=(118, 168, 192), anchor="la")

    if deep:
        leg = [("accepted \u2192 upstream", COL_EDGE),
               ("cache hit \u2192 client", COL_CACHE),
               ("rejected 4xx / 429", COL_REJ),
               ("filtered / denied", COL_DENY),
               ("upstream retry", COL_RETRY)]
        x, y = 52.0, 792.0
        for name, c in leg:
            cc = tuple(int(min(255, v * 255)) for v in c)
            d.ellipse([x * s, (y - 4) * s, (x + 8) * s, (y + 4) * s],
                      fill=(cc[0], cc[1], cc[2], 230))
            d.text(((x + 15) * s, y * s), name, font=lab(11.5),
                   fill=(150, 182, 200), anchor="lm")
            x += 24 + len(name) * 6.6
        d.text((52 * s, 826 * s),
               "12.4k in  =  9.73k upstream  +  2.48k cache  +  236 rejected  +  50 denied",
               font=lab(11.5), fill=(122, 160, 180), anchor="la")
        d.text((52 * s, 858 * s),
               "frame t=%ss / long-exposure photons, no arrow glyphs / variant MAX" % tlabel,
               font=lab(11.5), fill=(84, 114, 132), anchor="la")

    d.text((1548 * s, 46 * s), "variant %s" % variant.upper(), font=lab(13),
           fill=(138, 174, 194), anchor="ra")
    d.text((1548 * s, 70 * s), "t=%ss" % tlabel, font=lab(13),
           fill=(104, 138, 158), anchor="ra")
    if not deep:
        d.text((1548 * s, 858 * s), "quick pass / accept + reject only",
               font=lab(11), fill=(82, 112, 130), anchor="ra")

    d.rectangle([0, 0, W - 1, H - 1], outline=(26, 44, 58, 255), width=max(1, int(2 * s)))
    ow = int(out_w)
    return img.resize((ow, int(round(ow * LH / LW))), Image.LANCZOS)


# ------------------------------------------------------------------ output
def label_strip(items, path, title, width=None):
    """items: [(label, image)] stacked side by side under a title."""
    pad, top, cap = 20, 40, 34
    w, h = items[0][1].size
    sheet = Image.new("RGB", (len(items) * w + (len(items) + 1) * pad,
                              h + top + pad + cap + pad), (6, 8, 13))
    d = ImageDraw.Draw(sheet)
    d.text((pad + 2, 11), title, font=font(F_MONOB, 17), fill=(210, 231, 243))
    for i, (lb, im) in enumerate(items):
        x = pad + i * (w + pad)
        sheet.paste(im, (x, top + pad))
        d.text((x + 2, top + pad + h + 9), lb, font=font(F_MONO, 13.5),
               fill=(158, 187, 202))
    if width:
        sheet = sheet.resize((width, int(sheet.height * width / sheet.width)),
                             Image.LANCZOS)
    sheet.save(path)


def main():
    for sub in ("variant-high", "variant-max"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    stats = {}

    for variant, frames, seed in (("high", (0.00, 0.55), 11),
                                  ("max", (0.00, 0.33, 0.66), 7)):
        for i, ph in enumerate(frames):
            t1 = time.time()
            im = render(variant, 1600, ph, "%.2f" % (ph * 2.4), seed)
            p = os.path.join(OUT, "variant-%s" % variant, "%s-t%02d.png" % (variant, i))
            im.save(p)
            stats.setdefault(variant, []).append(round(time.time() - t1, 2))
            print("wrote", p, "%.2fs" % (time.time() - t1))

    hi = Image.open(os.path.join(OUT, "variant-high", "high-t00.png"))
    mx = Image.open(os.path.join(OUT, "variant-max", "max-t00.png"))
    label_strip(
        [("HIGH   quick pass: accept + reject, one hue, 1 bloom", hi),
         ("MAX    deep pass: distribute / cache / filter / reject / retry", mx)],
        os.path.join(OUT, "compare-effort.png"),
        "SAME ENGINE, TWO REASONING-EFFORT LEVELS OF AUTHORSHIP")

    node = mx.crop((610, 300, 1000, 620)).resize((1170, 960), Image.LANCZOS)
    label_strip([("MAX  /  edge node detail  x3   (comb = distribute, hairpin = cache hit, stub = deny, outside arc = retry)", node)],
                os.path.join(OUT, "node-detail-max.png"),
                "INSIDE THE EDGE: distribute, cache hit, deny, reject, retry")

    contact_max = [("frame 1  t=0.00s", os.path.join(OUT, "variant-max", "max-t00.png")),
                   ("frame 2  t=0.79s", os.path.join(OUT, "variant-max", "max-t01.png")),
                   ("frame 3  t=1.58s", os.path.join(OUT, "variant-max", "max-t02.png"))]
    from PIL import Image as _I
    label_strip([(lb, _I.open(p)) for lb, p in contact_max],
                os.path.join(OUT, "contact-max.png"),
                "VARIANT MAX  -  three frames of the edge lifecycle", width=3200)
    contact_high = [("frame 1  t=0.00s", os.path.join(OUT, "variant-high", "high-t00.png")),
                    ("frame 2  t=1.32s", os.path.join(OUT, "variant-high", "high-t01.png"))]
    label_strip([(lb, _I.open(p)) for lb, p in contact_high],
                os.path.join(OUT, "contact-high.png"),
                "VARIANT HIGH  -  quick pass, accept + reject only", width=2400)
    print("stats", stats)


def make_gif(variant="max", N=22, out_w=1100):
    frames = []
    for i in range(N):
        ph = i / float(N)
        im = render(variant, out_w, ph, "%.2f" % (ph * 2.4), 7 if variant == "max" else 11)
        frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=224))
    p = os.path.join(OUT, "flow-%s.gif" % variant)
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=90,
                   loop=0, optimize=True)
    print("wrote", p, os.path.getsize(p) // 1024, "KB")


if __name__ == "__main__":
    if "--gif" in sys.argv:
        make_gif("high" if "high" in sys.argv else "max")
    else:
        main()
