# -*- coding: utf-8 -*-
"""
nginx edge visualization, MAX variant -- full request lifecycle.

Clients are NOT abstracted into one anonymous entry point. Four real client
groups converge on a single edge ingress, because the per-key policy (rate
limiting, deny rules, cache keys) only makes sense per group:

    browsers      5,180 r/s   h2 + TCP, keepalive 64
    mobile        4,120 r/s   h2, high RTT, TLS resumption
    api partners  2,460 r/s   HTTP/1.1, signed requests
    scrapers        640 r/s   abusive key -> hit by limit_req

Lifecycle modelled and drawn inside / around the node:

    distribute    ingress fans to four egress ports; particle density follows
                  each upstream's least_conn share
    token bucket  limit_req zone=api burst=200 nodelay on the ingress trunk;
                  when the bucket drains the excess is diverted to 429
    cache hit     proxy_cache hairpin, then an express lane back to the client
    filter        map/geo deny rule absorbs the request at the core
    reject        upstream 4xx turned around toward the client
    retry         proxy_next_upstream hands it back, node re-dispatches
    health check  passive: max_fails=3 fail_timeout=30s. app-03 crosses the
                  threshold, gets ejected, its share is redistributed, then
                  re-enters under a slow start
    long conns    app-01 keeps gRPC / WebSocket streams: persistent steady
                  filaments with no per-request packets, unlike every other
                  route which is drawn as discrete photon bursts
"""
import os, sys, time, math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fibre as F
import edge_conf as EC

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
CLIENT_X = 104.0
NGINX = (800.0, 450.0)
NG_R = 102.0
INGRESS = (NGINX[0] - NG_R, 450.0)
TRUNK_X0 = 312.0
BUCKET = (438.0, 450.0)
BOX_L, BOX_W, BOX_H = 1288.0, 250.0, 82.0
BACK_YS = [148.0, 348.0, 548.0, 748.0]
PORT_DEG = (-41.0, -15.0, 15.0, 41.0)

# (label, spec, rps, y, tint)
GROUPS = [
    ("browsers", "h2 / keepalive 64", 5180, 216.0, (0.52, 0.80, 1.00)),
    ("mobile", "h2 / tls resume", 4120, 344.0, (0.44, 0.74, 1.00)),
    ("api partners", "http/1.1 / signed", 2460, 472.0, (0.38, 0.68, 1.00)),
    ("scrapers", "no token / 640 r/s", 640, 600.0, (1.00, 0.52, 0.42)),
]
TOTAL_IN = sum(g[2] for g in GROUPS)          # 12,400
CACHE_RPS, DENY_RPS, REJ_RPS, LIM_RPS = 2480, 50, 236, 520


def port(i, rr=None):
    a = math.radians(PORT_DEG[i])
    r = NG_R if rr is None else rr
    return (NGINX[0] + r * math.cos(a), NGINX[1] + r * math.sin(a))


def p_group(i):
    _, _, _, gy, _ = GROUPS[i]
    x0 = CLIENT_X + 34.0
    return [(x0, gy),
            (x0 + 62.0, gy + (450.0 - gy) * 0.34),
            (TRUNK_X0 - 70.0, 450.0 + (gy - 450.0) * 0.16),
            (TRUNK_X0, 450.0)]


P_TRUNK = [(TRUNK_X0, 450.0), (400.0, 436.0), (560.0, 462.0), INGRESS]

# Client groups are drawn as a ring of radius 34. Every return lane must land ON
# that ring, otherwise the particle appears to vanish into empty space. (Both
# p_limited and p_rej used to stop at (330, 676), which is 207px short of the
# scrapers node -- that was the "line dies in nowhere" bug.)
RING_R = 34.0


def g_y(i):
    return GROUPS[i][3]


def ring_pt(i, sign):
    """A point on client-group i's ring; sign=+1 below centre, -1 above."""
    a = math.radians(40.0)
    gy = g_y(i)
    return (CLIENT_X + RING_R * math.cos(a),
            gy + sign * RING_R * math.sin(a))


# trunk -> 429 corridor (only when the bucket overflows)
def p_limited(i=3):
    """429 spur: bucket overflow -> arcs down -> lands back on the client group"""
    cy = g_y(i)
    return [(BUCKET[0] + 26.0, 462.0),
            (492.0, 556.0),
            (300.0, cy + 96.0),
            ring_pt(i, +1)]


# 429 corridor back toward the client column


# cache hairpin inside the disc, then express lane back over the top
# cache hairpin: ingress -> up and over -> lands ON the cache-store glyph
P_CACHE = [(INGRESS[0], NGINX[1]),
           (NGINX[0] - 52.0, NGINX[1] - 74.0),
           (NGINX[0] + 52.0, NGINX[1] - 80.0),
           (NGINX[0] + 20.0, NGINX[1] - 34.0)]
# Return lanes are DERIVED from the client-group rows, never pinned to a pixel.
def p_ret(i=0):
    """cache express lane: node -> the client group that hit the cache"""
    cy = g_y(i)
    return [(NGINX[0] + 20.0, NGINX[1] - 34.0),
            (664.0, 236.0),
            (320.0, cy - 92.0),
            ring_pt(i, -1)]


def p_rej(i=3):
    """reject lane: node -> the client group that got the 4xx / 429"""
    cy = g_y(i)
    return [(INGRESS[0] - 4.0, 468.0),
            (596.0, 636.0),
            (300.0, cy + 96.0),
            ring_pt(i, +1)]

# deny stub, dies inside the ring
# deny stub: leaves the ingress and is absorbed AT the node core, so
# "filtered" reads as absorbed rather than as a line that stops in mid-air.
# Denied requests are absorbed at the ingress -- they never enter the
# distribution spine. The path used to run all the way to the centre, crossing
# the fan-out and making it unreadable.
P_DENY = [(INGRESS[0], NGINX[1]),
          (INGRESS[0] + 26.0, NGINX[1] + 26.0),
          (INGRESS[0] + 52.0, NGINX[1] + 34.0),
          (INGRESS[0] + 74.0, NGINX[1] + 30.0)]


# The trunk ends at INGRESS with a ~30 px bundle. The branches leave from an
# arc 26 px inside the disc, one per egress port. Without a section spanning
# those two x positions the drawing has a hole exactly where the split happens.
MANIFOLD_IN = INGRESS[0]                 # 698: where the trunk stops
MANIFOLD_OUT = INGRESS[0] + 26.0         # 724: where the branches begin
BRANCH_DY = 15.0                         # vertical spread across four exits
TRUNK_HALF_W = 15.0                      # half the trunk's bundle width


def p_manifold(edge=-1):
    """The throat: full trunk width at one end, four seeded lanes at the other.

    `edge` -1 / +1 selects the top or bottom wall of the wedge, so the shape is
    filled rather than being two hairlines.
    """
    y0 = NGINX[1] + edge * TRUNK_HALF_W
    y1 = NGINX[1] + edge * (BRANCH_DY + 4.0)
    return [(MANIFOLD_IN, y0),
            (MANIFOLD_IN + 9.0, y0 + (y1 - y0) * 0.35),
            (MANIFOLD_IN + 19.0, y0 + (y1 - y0) * 0.78),
            (MANIFOLD_OUT, y1)]


def p_spine(i):
    """Ingress -> port i, the full distribution path inside the disc.

    This replaces p_comb, which only spanned ~175 px and sat under the trunk's
    glow. The whole point is that the split is now visible: one throat at the
    ingress opening into four labelled exits instead of stopping at the rim.
    """
    px, py = port(i, NG_R * 0.99)
    # Each branch leaves from its OWN point on a short arc just inside the
    # ingress, not from a single shared point. Four paths springing from one
    # pixel read as a firework; an arc reads as a manifold taking traffic apart.
    rank = (i - 1.5) / 1.5                    # -1 .. 1 across the four exits
    ix, iy = MANIFOLD_OUT, NGINX[1] + rank * BRANCH_DY
    spread = 0.5 + 0.5 * (py - NGINX[1]) / 70.0      # -1..1 across the exits
    return [(ix, iy),
            (ix + 52.0, iy + (py - iy) * 0.30),
            (NGINX[0] + 34.0, py + (iy - py) * 0.22),
            (px, py)]


def p_throat(cx=0.0):
    """The widening mouth just inside the ingress, where the trunk opens up."""
    ix = INGRESS[0] - 4.0
    return [(ix, NGINX[1]),
            (ix + 54.0, NGINX[1] - 8.0),
            (ix + 74.0, NGINX[1] + 6.0),
            (ix + 66.0, NGINX[1])]


def p_up(i, dy=0.0):
    """port -> card edge: tight at the port, opens mid-flight, gathers at the card."""
    y = BACK_YS[i]
    px, py = port(i)
    return [(px, py + dy),
            (px + 108.0, py + (y - py) * 0.34 + dy * 0.6),
            (1002.0, y - (y - NGINX[1]) * 0.16 + dy * 0.2),
            (BOX_L, y + dy)]


def p_redis(i, j):
    """re-dispatch arc: leaves port i and re-enters port j, both on the rim."""
    p0, p3 = port(i, NG_R * 0.98), port(j, NG_R * 0.98)
    return [p0,
            (NGINX[0] + NG_R * 1.46, p0[1] + (p3[1] - p0[1]) * 0.30),
            (NGINX[0] + NG_R * 1.46, p3[1] - (p3[1] - p0[1]) * 0.30),
            p3]


def p_probe(i, dy=0.0):
    """health probe: parallel to the request lane, landing on the card edge."""
    y = BACK_YS[i] + dy
    px, py = port(i)
    return [(px + 10.0, py + dy),
            (px + 84.0, py + (y - py) * 0.46),
            (1000.0, y - (y - NGINX[1]) * 0.20),
            (BOX_L, y)]


COL_IN = (0.50, 0.76, 1.00)
COL_EDGE = (0.26, 0.84, 1.00)
COL_UP = [(0.30, 1.00, 0.72), (0.68, 1.00, 0.42), (0.66, 0.50, 1.00), (1.00, 0.45, 0.72)]
COL_CACHE = (0.62, 1.00, 0.94)
COL_REJ = (1.00, 0.33, 0.25)
COL_DENY = (0.54, 0.58, 0.64)
COL_RETRY = (1.00, 0.62, 0.15)
COL_GOLD = (1.00, 0.84, 0.34)
COL_WS = (0.78, 0.96, 1.00)
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


# ------------------------------------------------------------------ frames
FRAMES = [
    dict(t="0.00", uptime="steady", bucket=0.84, limited=False,
         health=["ok", "ok", "ok", "ok"], sel=1, ws=True,
         up=[3320, 2760, 2240, 794],
         note="all four upstreams healthy, bucket refilled"),
    dict(t="0.79", uptime="burst + eject", bucket=0.16, limited=True,
         health=["ok", "ok", "fail", "ok"], sel=0, ws=True,
         up=[3900, 3300, 0, 1914],
         note="limit_req 429 on scrapers, app-03 crossed max_fails=3"),
    dict(t="1.58", uptime="recovery", bucket=0.71, limited=False,
         health=["ok", "ok", "slow", "ok"], sel=2, ws=True,
         up=[3500, 2900, 900, 1814],
         note="app-03 back in pool under slow start"),
]


# ------------------------------------------------------------------ render
# ---------------------------------------------------------------- envelope
# Every route gets a "gather -> spread -> gather" breathing envelope, except
# the short hops inside the node where a constant width reads better.
ENVELOPE_MODES = {
    "group": "tight",
    "trunk_a": "tight",
    "trunk_b": "tight",
    "comb": "flat",
    "fan": "tight",
    "ret": "tight",
    "lim": "tight",
    "deny": "flat",
    "ws": "flat",
}


def _plate(d, x, y, text, fnt, s, pad=5.0, alpha=132):
    """Draw a dark rounded plate behind small text.

    Small type over a bloomed field has no separation from the glow, which the
    eye reads as soft focus even though the glyphs are as sharp as the DOM
    panel's. The plate restores contrast without dimming the picture.
    """
    try:
        bb = d.textbbox((x, y), text, font=fnt)
    except Exception:
        return
    d.rounded_rectangle(
        [bb[0] - pad * s, bb[1] - pad * 0.55 * s,
         bb[2] + pad * s, bb[3] + pad * 0.55 * s],
        radius=int(4 * s), fill=(4, 9, 14, alpha))


def render(st, out_w=1600, seed=7):
    rng = np.random.default_rng(seed)
    s = (out_w / LW) * 2.0
    W, H = int(round(LW * s)), int(round(LH * s))
    NB = len(BACK_YS)
    # `t` runs 0 -> 18 across the cycle and route() takes phase % 1.0, so
    # driving phase from t made every segment sweep 18 times per loop -- far
    # too fast to read as flow. Drive it from u (one sweep per loop) instead.
    u = float(st.get("u", 0.0))
    phase = u

    def fph(rate, off=0.0):
        """Phase for one route. `rate` scales its speed, so faster routes
        visibly move faster -- speed carries volume, as it should."""
        return u * rate + off

    tot_up = float(sum(st["up"]))
    wgt = [v / tot_up if tot_up else 0.0 for v in st["up"]]
    max_wgt = max(wgt) if wgt else 1.0

    buf = np.zeros((H, W, 3), np.float32)

    # ---- node halos
    add_blob(buf, NGINX[0], NGINX[1], 198.0, 0.20, (0.12, 0.38, 0.56), s)
    for i, gy in enumerate([g[3] for g in GROUPS]):
        add_blob(buf, CLIENT_X, gy, 74.0, 0.075, tuple(0.5 * v for v in GROUPS[i][4]), s)
    for i, y in enumerate(BACK_YS):
        lit = 0.09 if st["health"][i] == "ok" else 0.045
        add_blob(buf, BOX_L + 112.0, y, 96.0, lit, tuple(0.5 * v for v in COL_UP[i]), s)

    # ---- client groups -> trunk
    for gi, g in enumerate(GROUPS):
        label, spec, rps, gy, tint = g
        share = rps / TOTAL_IN
        lim = st["limited"] and label == "scrapers"
        col = COL_REJ if lim else COL_IN
        F.route(buf, s, p_group(gi), col, fph(0.55 + 1.10 * (rps / TOTAL_IN), 0.11 * gi), rng,
                nfib=max(2, int(round(3 + 5 * share * 5))), spread=11.0,
                fib_amp=0.30, pulse=max(2, min(5, int(round(2 + 6 * share)))),
                wob=1.6, freq=1.25, grow=0.9, steps=620,
                packets=2 if not lim else 1, packet_w=0.085, taper=0.11, env=ENVELOPE_MODES["group"])

    # ---- trunk (rate limited zone)
    trunk_amp = 0.46 if not st["limited"] else 0.26
    F.route(buf, s, P_TRUNK, COL_EDGE, fph(1.35), rng,
            nfib=18, spread=30.0, fib_amp=trunk_amp,
            pulse=6 if not st["limited"] else 34, pulse_amp=6.4,
            pulse_len=0.075, wob=3.0, freq=1.4, grow=1.5, steps=900,
            # taper=0 at the tail: the trunk hands over to the spine at
            # INGRESS, and two fade-outs meeting at one point leave a gap
            packets=3, packet_w=0.070, taper=0.0, env=ENVELOPE_MODES["trunk_a"])

    # ---- token bucket overflow -> 429
    if st["limited"]:
        F.route(buf, s, p_limited(3), COL_REJ, fph(0.9, 0.2), rng,
                nfib=9, spread=14.0, fib_amp=0.52,
                pulse=3, pulse_amp=7.9, pulse_len=0.075, wob=1.6, freq=1.7, grow=1.0, steps=460,
                packets=3, packet_w=0.085, taper=0.09, env=ENVELOPE_MODES["lim"])

    # ---- distribution comb
    for i in range(NB):
        if st["health"][i] != "ok" and st["up"][i] == 0:
            continue
        # The manifold is drawn per-branch as its own wall so the wedge fills
        # in: two hairlines would read as an outline, not as a solid throat.
        wall = 1.0 if i < 2 else -1.0
        F.route(buf, s, p_manifold(wall), COL_EDGE,
                fph(1.25), rng, nfib=6, spread=7.0, fib_amp=0.46,
                pulse=3, pulse_amp=5.0, pulse_len=0.075, wob=0.5, freq=2.0,
                grow=0.0, steps=260, packets=2, packet_w=0.09,
                taper=0.0, env=None)

        F.route(buf, s, p_spine(i), COL_EDGE, fph(0.62 + 0.55 * wgt[i] / (max_wgt or 1.0), 0.05 * i), rng,
                # thick enough to read as the distribution half of the edge,
                # not as a stray fibre under the trunk: width follows share too
                nfib=max(4, int(round(14 * wgt[i] / (max_wgt or 1.0)))),
                spread=9.0,
                fib_amp=0.52,
                pulse=max(2, min(5, int(round(2 + 6 * wgt[i])))),
                pulse_amp=5.4, pulse_len=0.075,
                wob=1.1, freq=1.5, grow=1.2, steps=440,
                # taper=0 at the head: it starts exactly where the trunk ends
                packets=2, packet_w=0.085, taper=0.0, env=ENVELOPE_MODES["fan"])

    # ---- cache hit + express return
    F.route(buf, s, P_CACHE, COL_CACHE, fph(0.70, 0.10), rng,
            nfib=5, spread=7.0, fib_amp=0.38,
            pulse=2, pulse_amp=5.6, pulse_len=0.075, wob=1.2, freq=1.7, grow=1.0, steps=440,
            packets=1, packet_w=0.09, taper=0.10, env=ENVELOPE_MODES["comb"])
    F.route(buf, s, p_ret(0), COL_CACHE, fph(0.70, 0.40), rng,
            nfib=7, spread=10.0, fib_amp=0.36,
            pulse=2, pulse_amp=5.6, pulse_len=0.075, wob=1.6, freq=1.4, grow=1.0, steps=700,
            packets=2, packet_w=0.075, taper=0.09, env=ENVELOPE_MODES["ret"])

    # ---- deny stub
    F.route(buf, s, P_DENY, COL_DENY, fph(0.40, 0.72), rng,
            nfib=5, spread=6.0, fib_amp=0.30,
            pulse=2, pulse_amp=2.5, pulse_len=0.075, wob=0.8, freq=1.9, grow=1.0, steps=300,
            packets=1, packet_w=0.12, taper=0.07, env=ENVELOPE_MODES["deny"])

    # ---- rejected traffic corridor
    F.route(buf, s, p_rej(3), COL_REJ, fph(0.85, 0.5), rng,
            nfib=8, spread=11.0, fib_amp=0.46,
            pulse=2, pulse_amp=7.1, pulse_len=0.075, wob=1.2, freq=1.9, grow=1.0, steps=620,
            packets=2, packet_w=0.095, taper=0.09, env=ENVELOPE_MODES["ret"])

    # ---- retry + re-dispatch (only while an upstream is failing/slow)
    for i in range(NB):
        if st["health"][i] not in ("fail", "slow"):
            continue
        tgt = 0 if i != 0 else 1
        F.route(buf, s, p_up(i), COL_RETRY, fph(0.55, 0.30), rng,
                nfib=3, spread=6.0, fib_amp=0.20,
                pulse=2, pulse_amp=3.4, pulse_len=0.075, wob=0.8, freq=1.6, grow=1.0, steps=640,
                packets=0, packet_w=0.1, taper=0.13, back=True, env=ENVELOPE_MODES["fan"])
        F.route(buf, s, p_redis(i, tgt), COL_RETRY, fph(0.55, 0.58), rng,
                nfib=3, spread=5.0, fib_amp=0.22,
                pulse=2, pulse_amp=4.1, pulse_len=0.075, wob=0.6, freq=1.8, grow=1.0, steps=380,
                packets=0, packet_w=0.1, taper=0.10, env=ENVELOPE_MODES["comb"])

    # ---- egress fans
    for i in range(NB):
        if st["up"][i] <= 0:
            continue
        F.route(buf, s, p_up(i), COL_UP[i],
                fph(0.45 + 1.15 * (wgt[i] / max_wgt if max_wgt else 0.0), 0.23 * i), rng,
                nfib=max(3, int(round(16 * wgt[i] * 1.6))),
                spread=26.0 * (0.45 + wgt[i]) * (0.72 if i == 0 else 1.0),
                fib_amp=0.32,
                pulse=max(2, min(6, int(round(2 + 8 * wgt[i])))),
                wob=2.8, freq=1.35, grow=1.7, steps=940,
                # starts on the port marker: no fade-in, or the spine and the
                # egress lane leave a dark ring at the rim
                packets=2, packet_w=0.075, taper=0.0, env=ENVELOPE_MODES["fan"])
        # Returns ride the same corridor, nudged off-axis so the two directions
        # are distinguishable, at low intensity. A second full-brightness line
        # would double the apparent weight of a link that is really one link.
        F.route(buf, s, p_up(i, dy=-7.0), COL_BACK,
                fph(0.45 + 1.15 * (wgt[i] / max_wgt if max_wgt else 0.0), 0.56 + 0.15 * i), rng,
                # dimmer than the request lane but still carrying visible
                # segments: at pulse_amp=1.3 this read as a dead cable
                nfib=3, spread=7.0, fib_amp=0.16,
                pulse=2, pulse_amp=3.2, pulse_len=0.075, wob=1.0, freq=1.25, grow=1.0, steps=800,
                packets=1, packet_w=0.09, taper=0.12, back=True, env=ENVELOPE_MODES["fan"])

    # ---- gRPC / WebSocket long-lived streams on app-01
    if st["ws"]:
        # A persistent stream is drawn differently from request traffic: two
        # steady rails with no per-request packets. It leaves port 0, rides
        # above the request fan, and lands on the app-01 card edge.
        # routed through genuinely empty space: up from the port, then a flat
        # run above app-01's card so it never crosses the request fan
        # WS/gRPC corridor: leaves port0 upward, arcs over the disc, and lands
        # on app-01's TOP-LEFT CORNER -- it used to end at y=84, which is 23px
        # ABOVE the card (card top = y=107), so the stream flew past its target.
        # WS/gRPC corridor: leaves port0 upward, arcs over the disc, lands on
        # app-01's top-left corner. It used to end at y=84 -- 23px ABOVE the
        # card top (y=107) -- so the stream flew past its own destination.
        # WS/gRPC corridor: leaves port0, arcs over the disc, and PLUGS INTO
        # app-01's accent bar (x = BOX_L + 6) at the card's vertical centre.
        # It used to stop at y=108, one pixel above the card, which read as
        # "hovers outside and connects to nothing".
        WS_TARGET = (BOX_L + 6.0, BACK_YS[0])
        # start ON port 0 so the corridor has a visible origin
        P_WS = [(port(0)[0], port(0)[1]),
                (900.0, 250.0),
                (1010.0, 128.0),
                WS_TARGET]
        # One rail, not two. Two rails x 4 fibres packed into 10px rendered as
        # a striped cable -- the heaviest mark on the canvas, for the least
        # important traffic.
        F.route(buf, s, P_WS, COL_WS, 0.0, rng,
                nfib=3, spread=3.0, fib_amp=0.44,
                wob=0.5, freq=1.1, grow=0.0, steps=1000,
                packets=0, packet_w=0.1, taper=0.04)
        # tiny bidirectional frames trickling along the rails
        for k in range(18):
            rr = -2.2 if k % 2 else 2.2
            F.route(buf, s, [(x, y + rr) for x, y in P_WS], COL_WS,
                    fph(1.6, k * 0.0555), rng,
                    nfib=2, spread=1.4, fib_amp=0.32,
                    pulse=2, pulse_amp=3.4, pulse_len=0.075, wob=0.3, freq=1.5, grow=0.0, steps=820,
                    packets=0, packet_w=0.1, taper=0.05,
                    back=(k % 2 == 0))

    # (removed) ingress backpressure droplets: four gold blobs parked 74px
    # below the trunk, anchored to nothing and labelled by nothing. They were
    # meant to read as pressure piling up at the ingress when the edge
    # saturates, but detached fuzzy dots read as stray light, not as
    # backpressure. Dropped rather than moved: the form itself was the problem.

    # ---- bloom + tone
    light = F.bloom(buf, s, scales=(2.0, 6.5, 20.0), weights=(0.52, 0.26, 0.15))
    img = Image.fromarray(F.tonemap(light, gain=1.95, bg=base_bg(W, H)), "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    lab = lambda z: font(F_MONO, z * s)
    stroke = dict(stroke_width=max(2, int(2.6 * s)), stroke_fill=(5, 9, 15, 240))

    # ---- dashed guides
    def guide(P, colr, dash=16, wdt=1.1):
        # Continuous, not dashed. With the frame supersampled, a 16-sample gap
        # is ~32 device px, so a dashed guide reads as scattered debris -- most
        # visibly where a guide crosses the edge disc.
        pts = F.bez(P, np.linspace(0, 1, 360))
        for i in range(len(pts) - 1):
            d.line([(pts[i, 0] * s, pts[i, 1] * s),
                    (pts[i + 1, 0] * s, pts[i + 1, 1] * s)],
                   fill=colr, width=max(1, int(wdt * s)))

    # alphas halved: a solid line covers twice what the dashed version did
    for gi in range(len(GROUPS)):
        guide(p_group(gi), (56, 94, 118, 15))
    guide(P_TRUNK, (58, 98, 122, 19))
    guide(p_ret(0), (56, 116, 112, 15))
    guide(p_rej(3), (128, 58, 50, 24))
    for i in range(NB):
        if st["up"][i] > 0:
            guide(p_up(i), (56, 94, 118, 16))

    # ---- client group chips
    for gi, g in enumerate(GROUPS):
        label, spec, rps, gy, tint = g
        lim = st["limited"] and label == "scrapers"
        cc = tuple(int(min(255, v * 255)) for v in tint)
        cx, cy = CLIENT_X, gy
        for rr, aa in ((34, 16), (24, 30)):
            d.arc([(cx - rr) * s, (cy - rr) * s, (cx + rr) * s, (cy + rr) * s],
                  200 + phase * 70 + gi * 22, 340 + phase * 70 + gi * 22,
                  fill=(cc[0], cc[1], cc[2], aa), width=max(1, int(1.5 * s)))
        d.ellipse([(cx - 12) * s, (cy - 12) * s, (cx + 12) * s, (cy + 12) * s],
                  outline=(cc[0], cc[1], cc[2], 150), width=max(1, int(1.6 * s)))
        d.text(((cx + 44) * s, (cy - 15) * s), label, font=lab(12.5),
               fill=(cc[0], cc[1], cc[2]), anchor="la", **stroke)
        d.text(((cx + 44) * s, (cy + 2) * s),
               "%d r/s  %s" % (rps, spec), font=lab(10.5),
               fill=(120, 152, 172), anchor="la")
        if lim:
            d.text(((cx + 44) * s, (cy + 18) * s), "→ limit_req 429",
                   font=lab(10.5), fill=(255, 110, 92), anchor="la", **stroke)

    # ---- token bucket glyph
    bx, by = BUCKET
    bw, bh = 22.0, 30.0
    fill = st["bucket"]
    rim = COL_REJ if st["limited"] else COL_GOLD
    ri = tuple(int(min(255, v * 255)) for v in rim)
    d.rounded_rectangle([(bx - bw / 2) * s, (by - bh / 2) * s,
                         (bx + bw / 2) * s, (by + bh / 2) * s],
                        radius=int(5 * s), outline=(ri[0], ri[1], ri[2], 210),
                        width=max(1, int(1.7 * s)))
    fy0 = (by + bh / 2 - 3.0 - (bh - 6.0) * fill) * s
    fy1 = (by + bh / 2 - 3.0) * s
    d.rectangle([(bx - bw / 2 + 3) * s, fy0, (bx + bw / 2 - 3) * s, fy1],
                fill=(ri[0], ri[1], ri[2], 200))
    for t in range(1, 5):
        yy = (by - bh / 2 + bh * t / 5.0) * s
        d.line([(bx - bw / 2 - 2) * s, yy, (bx - bw / 2) * s, yy],
               fill=(120, 104, 60, 150), width=max(1, int(1.0 * s)))
    d.text(((bx + 24) * s, (by - 44) * s), "token bucket", font=lab(10.5),
           fill=(ri[0], ri[1], ri[2]), anchor="la", **stroke)
    d.text(((bx + 24) * s, (by - 29) * s),
           "%s  ·  %.0f%%" % (EC.label_burst(), fill * 100),
           font=lab(10.5), fill=(140, 126, 92), anchor="la")

    # ---- nginx disc
    cx, cy = NGINX
    # 1.12R sat too close to the bright 1.00R outline and read as a doubled
    # rim; the two wider rings alone still give the disc depth.
    for rr, aa in ((1.60, 13), (1.32, 30)):
        d.arc([(cx - NG_R * rr) * s, (cy - NG_R * rr) * s,
               (cx + NG_R * rr) * s, (cy + NG_R * rr) * s],
              0, 360, fill=(74, 190, 230, aa), width=max(1, int(1.2 * s)))
    d.ellipse([(cx - NG_R) * s, (cy - NG_R) * s, (cx + NG_R) * s, (cy + NG_R) * s],
              outline=(140, 238, 255, 158), width=max(1, int(2.2 * s)))
    # Opaque enough to quiet the burst of overlapping lane tails at the ingress.
    # At 116 the 14 converging tapers showed through as radial shards, which
    # read as debris inside the node.
    d.ellipse([(cx - NG_R * 0.88) * s, (cy - NG_R * 0.88) * s,
               (cx + NG_R * 0.88) * s, (cy + NG_R * 0.88) * s],
              fill=(7, 30, 46, 182), outline=(66, 158, 192, 92),
              width=max(1, int(1.2 * s)))

    sel = st["sel"]
    for i in range(NB):
        a = PORT_DEG[i]
        px, py = port(i, NG_R * 0.97)
        cc = tuple(int(min(255, v * 255)) for v in COL_UP[i])
        dead = st["health"][i] == "fail"
        hot = 1.0 if (i == sel and not dead) else 0.0
        base_g = 0.22 if dead else 0.55
        d.arc([(cx - NG_R * 1.02) * s, (cy - NG_R * 1.02) * s,
               (cx + NG_R * 1.02) * s, (cy + NG_R * 1.02) * s],
              a - 7.0, a + 7.0,
              fill=(min(255, int(cc[0] * base_g + 130 * hot)),
                    min(255, int(cc[1] * base_g + 130 * hot)),
                    min(255, int(cc[2] * base_g + 130 * hot)), 238),
              width=max(2, int(5.0 * s)))
        r = (2.2 + 5.0 * wgt[i] * 3 + (2.2 if hot else 0.0)) * s
        d.ellipse([px * s - r, py * s - r, px * s + r, py * s + r],
                  fill=(min(255, cc[0] + 70), min(255, cc[1] + 70),
                        min(255, cc[2] + 70), 235 if not dead else 90))

    # (removed) cache store glyph: an empty rounded rectangle with no
    # iconography, so it never read as "cache". It was also misplaced from the
    # day it was written -- the 24/30 offsets were scaled but the centre was
    # not, putting it in the top-left quadrant; corrected, it collided with the
    # "nginx" title instead. The legend already carries "cache hit -> client".
    # worker ticks
    for k in range(8):
        a = math.radians(k * 45.0 + 12.0)
        r0, r1 = NG_R * 0.60, NG_R * 0.70
        d.line([(cx + r0 * math.cos(a)) * s, (cy + r0 * math.sin(a)) * s,
                (cx + r1 * math.cos(a)) * s, (cy + r1 * math.sin(a)) * s],
               fill=(120, 190, 214, 100), width=max(1, int(1.4 * s)))
    d.arc([(cx - NG_R * 1.04) * s, (cy - NG_R * 1.04) * s,
           (cx + NG_R * 1.04) * s, (cy + NG_R * 1.04) * s],
          -10.0, 10.0, fill=(150, 235, 255, 235), width=max(2, int(5.0 * s)))

    a0 = (phase * 360 + 16) % 360
    for off, spn, wd in ((0, 56, 3), (150, 36, 2), (250, 22, 2)):
        d.arc([(cx - NG_R * 1.14) * s, (cy - NG_R * 1.14) * s,
               (cx + NG_R * 1.14) * s, (cy + NG_R * 1.14) * s],
              a0 + off, a0 + off + spn, fill=(180, 248, 255, 165),
              width=max(1, int(wd * s)))

    d.text((cx * s, (cy - 30) * s), "nginx", font=font(F_MSYHB, 22 * s),
           fill=(228, 253, 255), anchor="mm", **stroke)
    d.text((cx * s, (cy - 8) * s), "edge", font=lab(11.0),
           fill=(124, 206, 232), anchor="mm", **stroke)
    d.text((cx * s, (cy + 9) * s), "workers %d" % EC.CONF["workers"], font=lab(10.5),
           fill=(140, 178, 198), anchor="mm", **stroke)
    d.text((cx * s, (cy - NG_R * 1.56) * s), EC.label_tls(),
           font=lab(11.0), fill=(106, 152, 174), anchor="mm", **stroke)
    d.text((cx * s, (cy + NG_R * 1.58) * s), EC.label_upstream(),
           font=lab(11.0), fill=(106, 152, 174), anchor="mm", **stroke)

    # ---- health probes (dashed, no glow: these are checks, not traffic)
    for i in range(NB):
        h = st["health"][i]
        pc = COL_REJ if h == "fail" else (COL_GOLD if h == "slow" else (0.42, 0.86, 0.72))
        pci = tuple(int(min(255, v * 255)) for v in pc)
        # Continuous hairline with a distance fade. The old version drew
        # 9-sample dashes, which supersample into ~18 device px blocks and read
        # as a broken line; and an unhealthy probe stopped dead at 42%.
        pts = F.bez(p_probe(i), np.linspace(0, 1, 300))
        reach = 1.0 if h == "ok" else 0.42
        n = int(len(pts) * reach)
        for k in range(n - 1):
            # fade over the final third so a truncated probe dissolves
            f = k / float(max(1, n - 1))
            fade = min(1.0, (1.0 - f) / 0.34)
            a = int(120 * fade) if reach >= 1.0 else int(150 * fade)
            if a < 4:
                continue
            d.line([(pts[k, 0] * s, pts[k, 1] * s),
                    (pts[k + 1, 0] * s, pts[k + 1, 1] * s)],
                   fill=(pci[0], pci[1], pci[2], a),
                   width=max(1, int(1.0 * s)))
        if h == "fail":
            kx, ky = pts[n - 1]
            d.line([(kx - 5) * s, (ky - 5) * s, (kx + 5) * s, (ky + 5) * s],
                   fill=(255, 90, 74, 230), width=max(2, int(2.0 * s)))
            d.line([(kx - 5) * s, (ky + 5) * s, (kx + 5) * s, (ky - 5) * s],
                   fill=(255, 90, 74, 230), width=max(2, int(2.0 * s)))

    # ---- upstream cards
    for i, y in enumerate(BACK_YS):
        h = st["health"][i]
        cc = tuple(int(min(255, v * 255)) for v in COL_UP[i])
        dim = h == "fail"
        box = [BOX_L * s, (y - BOX_H / 2) * s, (BOX_L + BOX_W) * s, (y + BOX_H / 2) * s]
        edge_c = (255, 78, 64) if dim else ((255, 196, 90) if h == "slow"
                                            else (cc[0] // 3, cc[1] // 3, cc[2] // 3))
        d.rounded_rectangle(box, radius=int(12 * s),
                            fill=(5, 9, 15, 200) if dim else (6, 11, 19, 158),
                            outline=(edge_c[0], edge_c[1], edge_c[2], 205),
                            width=max(1, int(1.6 * s)))
        d.rounded_rectangle([box[0], box[1], box[0] + 4.5 * s, box[3]],
                            radius=int(3 * s),
                            fill=(cc[0] // 2, cc[1] // 2, cc[2] // 2, 150) if dim
                            else (cc[0], cc[1], cc[2], 178))
        d.ellipse([(BOX_L - 8) * s, (y - 4.5) * s, (BOX_L + 1) * s, (y + 4.5) * s],
                  fill=(70, 70, 78, 200) if dim else (cc[0], cc[1], cc[2], 210))
        name_col = (110, 118, 130) if dim else (238, 248, 254)
        d.text(((BOX_L + 17) * s, (y - 26) * s), "app-0%d" % (i + 1),
               font=font(F_MONOB, 16.5 * s), fill=name_col, anchor="la")
        d.text(((BOX_L + 17) * s, (y - 6) * s), "10.0.0.1%d:808%d" % (i + 1, i + 1),
               font=font(F_MONO, 12.5 * s), fill=(96, 106, 118) if dim else (132, 164, 182),
               anchor="la")
        bw = (BOX_W - 38) * s
        rps = st["up"][i]
        share = wgt[i]
        if h == "fail":
            d.text(((BOX_L + 17) * s, (y + 13) * s),
                   "EJECTED  fail_timeout 22s", font=lab(11.5),
                   fill=(255, 108, 92), anchor="la", **stroke)
            d.line([(BOX_L + 17) * s, (y + 20) * s,
                    (BOX_L + 17 + 150) * s, (y + 20) * s],
                   fill=(255, 96, 80, 150), width=max(1, int(1.4 * s)))
        else:
            tag = "  slow start" if h == "slow" else ""
            d.text(((BOX_L + 17) * s, (y + 13) * s),
                   "%d req/s   %.0f%%%s" % (rps, share * 100, tag),
                   font=lab(11.5),
                   fill=(255, 196, 90) if h == "slow" else (104, 136, 154),
                   anchor="la")
            # Track = the box's inner width. Fill = share of the pool, clamped
            # to 1.0 so a 43% share cannot draw 129% and spill out of the card.
            # (This used to be `share * 3.0`, a leftover from an older scale.)
            frac = max(0.0, min(1.0, share))
            d.rectangle([(BOX_L + 17) * s, (y + 28) * s,
                         (BOX_L + 17) * s + bw, (y + 32) * s], fill=(20, 32, 44, 235))
            d.rectangle([(BOX_L + 17) * s, (y + 28) * s,
                         (BOX_L + 17) * s + bw * frac, (y + 32) * s],
                        fill=(255, 196, 90, 190) if h == "slow" else (cc[0], cc[1], cc[2], 180))

    # WS badge on app-01
    if st["ws"]:
        bxx, byy = 872.0, 250.0
        d.rounded_rectangle([bxx * s, byy * s, (bxx + 116) * s, (byy + 20) * s],
                            radius=int(6 * s), fill=(9, 26, 34, 210),
                            outline=(180, 240, 255, 150), width=max(1, int(1.2 * s)))
        d.text(((bxx + 8) * s, (byy + 3) * s), "WS/gRPC 3,412 conns",
               font=lab(10.0), fill=(190, 240, 252), anchor="la")

        # ---- connection terminal: makes the landing point unmistakable
        tcx, tcy = WS_TARGET
        d.arc([(tcx - 7) * s, (tcy - 7) * s, (tcx + 7) * s, (tcy + 7) * s],
              0, 360, fill=(199, 245, 255, 235), width=max(1, int(1.6 * s)))
        d.arc([(tcx - 3.2) * s, (tcy - 3.2) * s,
               (tcx + 3.2) * s, (tcy + 3.2) * s],
              0, 360, fill=(230, 253, 255, 255), width=max(1, int(1.4 * s)))
        d.ellipse([(tcx - 1.6) * s, (tcy - 1.6) * s,
                   (tcx + 1.6) * s, (tcy + 1.6) * s],
                  fill=(255, 255, 255, 255))


    # ---- callouts: removed
    # There were six leader-line annotations here (cache hit, 429 turned
    # around, filter/deny absorbed, bucket drained, 3 fails ejected, WS stream).
    # Every one of them restated something already on screen: the legend at the
    # bottom carries all six categories, and st[note] bottom-right carries the
    # two dynamic ones. Six stems plus six dots added clutter and, because
    # several anchors sat on top of the lines they pointed at, the pointing read
    # as arbitrary rather than as a reference.

    # ---- header / legend / footer
    d.text((46 * s, 40 * s), "NGINX  /  PHOTON FLOW",
           font=font(F_MSYHB, 25 * s), fill=(242, 251, 255), anchor="la")
    d.text((46 * s, 72 * s),
           "4 client groups → 1 edge ingress → 4 upstreams", font=lab(12.5),
           fill=(118, 168, 192), anchor="la")

    leg = [("accepted → upstream", COL_EDGE),
           ("cache hit → client", COL_CACHE),
           ("429 rate limited", COL_REJ),
           ("filtered / denied", COL_DENY),
           ("upstream retry", COL_RETRY),
           ("WS / gRPC stream", COL_WS)]
    x, y = 46.0, 788.0
    for name, c in leg:
        ci = tuple(int(min(255, v * 255)) for v in c)
        d.ellipse([x * s, (y - 4) * s, (x + 8) * s, (y + 4) * s],
                  fill=(ci[0], ci[1], ci[2], 230))
        d.text(((x + 15) * s, y * s), name, font=lab(11.5),
               fill=(158, 190, 208), anchor="lm")
        x += 22 + len(name) * 6.4

    pool = sum(st["up"])
    # Live arithmetic, not constants: during the surge these numbers move, and
    # a fixed "12,400 in" would contradict the panel two inches away.
    d.text((46 * s, 818 * s),
           "%s in   =   %s upstream   +   %s cache   +   %s 4xx   +   %s limited   +   %s denied"
           % (format(st["demand"], ","), format(pool, ","),
              format(st["cache"], ","), format(st["fourxx"], ","),
              format(st["limited"], ","), format(st["deny"], ",")),
           font=lab(11.5), fill=(126, 164, 184), anchor="la")
    d.text((46 * s, 848 * s),
           "scenario t=%ss   ·   long-exposure photons, no arrow glyphs"
           % st["t"],
           font=lab(11.5), fill=(84, 114, 132), anchor="la")

    # The status sentence used to appear here AND bottom-right ("uptime" and
    # "note" were the same string). The telemetry panel owns it now.
    # "variant MAX" and the duplicate clock were development leftovers: removed.

    # ---- event log: the transitions that explain the picture ----------
    # This is what used to be missing when app-03 ejected: the diagram changed
    # and nothing said why.
    evs = st.get("events") or []
    # The left column is occupied all the way down by the client stack, so
    # the log goes in the band under the core instead.
    ex_, ey_ = 640.0, 642.0
    d.text((ex_ * s, ey_ * s), "RECENT EVENTS", font=lab(10.0),
           fill=(92, 128, 148), anchor="la")
    if not evs:
        d.text((ex_ * s, (ey_ + 24) * s), "no state changes", font=lab(11.0),
               fill=(64, 90, 106), anchor="la")
    else:
        for k, e in enumerate(evs[:4]):
            yy = ey_ + 24.0 + k * 21.0
            age = "now" if e["age"] == 0 else "%.1fs ago" % (e["age"] * 0.5)
            d.text((ex_ * s, yy * s), age, font=lab(10.0),
                   fill=(104, 140, 162), anchor="la")
            d.text(((ex_ + 72) * s, yy * s),
                   "%s  %s" % (e["who"], e["text"]), font=lab(11.0),
                   fill=(214, 178, 132), anchor="la")

    d.rectangle([0, 0, W - 1, H - 1], outline=(26, 44, 58, 255), width=max(1, int(2 * s)))
    ow = int(out_w)
    return img.resize((ow, int(round(ow * LH / LW))), Image.LANCZOS)


# ------------------------------------------------------------------ output
def label_strip(items, path, title, width=None):
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
    sub = os.path.join(OUT, "max-lifecycle")
    os.makedirs(sub, exist_ok=True)
    paths = []
    for i, st in enumerate(FRAMES):
        t1 = time.time()
        im = render(st, 1600)
        p = os.path.join(sub, "life-%02d.png" % i)
        im.save(p)
        paths.append((p, "frame %d  t=%ss  ·  %s" % (i + 1, st["t"], st["uptime"])))
        print("wrote", p, "%.2fs" % (time.time() - t1))

    label_strip([(lb, Image.open(p)) for p, lb in paths],
                os.path.join(OUT, "contact-max-lifecycle.png"),
                "VARIANT MAX  -  edge lifecycle: limit_req / cache / deny / reject / retry / health check / gRPC-WS",
                width=3400)

    im0 = Image.open(paths[0][0])
    im1 = Image.open(paths[1][0])

    # detail: ingress + token bucket + 4 client groups
    label_strip([("ingress: 4 client groups → token bucket → edge",
                  im0.crop((20, 150, 700, 760)).resize((1088, 976), Image.LANCZOS))],
                os.path.join(OUT, "detail-ingress.png"),
                "CLIENT GROUPS ARE PER-KEY: that is where limit_req actually lives")

    # detail: health check ejection
    label_strip([("steady: app-03 healthy",
                  im0.crop((600, 330, 1420, 640)).resize((1148, 434), Image.LANCZOS)),
                 ("burst: 3 fails → ejected, share redistributed",
                  im1.crop((600, 330, 1420, 640)).resize((1148, 434), Image.LANCZOS))],
                os.path.join(OUT, "detail-healthcheck.png"),
                "PASSIVE HEALTH CHECK: max_fails=3 fail_timeout=30s", width=2600)

    # detail: WS / gRPC long-lived stream
    label_strip([("app-01: steady band = WS/gRPC, bursts = requests",
                  im0.crop((620, 90, 1420, 330)).resize((1200, 360), Image.LANCZOS))],
                os.path.join(OUT, "detail-ws.png"),
                "LONG-LIVED CONNECTIONS: continuous, not per-request photons")
    print("done")


def make_gif(N=18, out_w=1100):
    frames = []
    for i in range(N):
        st = dict(FRAMES[0])
        ph = i / float(N) * 1.6
        st["t"] = "%.2f" % ph
        # cycle through the narrative so the animation tells the same story
        seg = (i / float(N)) * 3.0
        idx = int(seg) % 3
        base = FRAMES[idx]
        st = dict(base)
        st["t"] = "%.2f" % ph
        im = render(st, out_w)
        frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=224))
    p = os.path.join(OUT, "flow-max-lifecycle.gif")
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=110,
                   loop=0, optimize=True)
    print("wrote", p, os.path.getsize(p) // 1024, "KB")


if __name__ == "__main__":
    if "--gif" in sys.argv:
        make_gif()
    else:
        main()
