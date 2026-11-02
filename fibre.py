# -*- coding: utf-8 -*-
"""
Strand renderer: a route is a bundle of *distinct* thin fibres, each carrying
travelling bright beads. Fibres are laid first (so they stay separate), beads
second (so they read as photons riding the fibre).
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def bez(P, t):
    P = np.asarray(P, np.float64)
    t = np.asarray(t, np.float64).reshape(-1, 1)
    mt = 1.0 - t
    return ((mt ** 3) * P[0] + (3 * mt * mt * t) * P[1]
            + (3 * mt * t * t) * P[2] + (t ** 3) * P[3])


def bez_d(P, t):
    P = np.asarray(P, np.float64)
    t = np.asarray(t, np.float64).reshape(-1, 1)
    mt = 1.0 - t
    return 3 * mt * mt * (P[1] - P[0]) + 6 * mt * t * (P[2] - P[1]) + 3 * t * t * (P[3] - P[2])


def arclen(P, n=1200):
    """(u, pts, normals) uniformly spaced by arc length; u in 0..1."""
    t = np.linspace(0.0, 1.0, n)
    pts = bez(P, t)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    cum /= cum[-1]
    u = np.linspace(0.0, 1.0, n)
    tt = np.interp(u, cum, t)
    pp = bez(P, tt)
    d = bez_d(P, tt)
    nrm = np.stack([-d[:, 1], d[:, 0]], -1)
    nrm /= (np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9)
    return u, pp, nrm


def line_add(buf, xs, ys, ws, col):
    """Bilinear additive polyline-ish scatter (thin, continuous)."""
    if len(xs) < 2:
        return
    H, W = buf.shape[:2]
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    fx = (xs - x0).astype(np.float32)
    fy = (ys - y0).astype(np.float32)
    flat = buf.reshape(-1, 3)
    c = np.asarray(col, np.float32)
    for dy, wy in ((0, 1.0 - fy), (1, fy)):
        yi = y0 + dy
        my = (yi >= 0) & (yi < H)
        for dx, wx in ((0, 1.0 - fx), (1, fx)):
            xi = x0 + dx
            m = my & (xi >= 0) & (xi < W)
            if not m.any():
                continue
            w = ws * wy * wx
            ok = m & (w > 1e-4)
            if not ok.any():
                continue
            np.add.at(flat, yi[ok] * W + xi[ok], w[ok][:, None] * c[None, :])


def blob_add(buf, x, y, r, amp, col):
    """Small gaussian dot sprite."""
    rr = max(1, int(round(r)))
    ax = np.arange(-rr, rr + 1, dtype=np.float32)
    k = np.exp(-(ax[:, None] ** 2 + ax[None, :] ** 2) / (rr * rr * 0.42)).astype(np.float32)
    H, W = buf.shape[:2]
    xi, yi = int(round(x)), int(round(y))
    x0, y0 = xi - rr, yi - rr
    x1, y1 = x0 + k.shape[1], y0 + k.shape[0]
    if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H:
        return
    kx0, ky0 = max(0, -x0), max(0, -y0)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(W, x1), min(H, y1)
    sub = k[ky0:ky0 + (sy1 - sy0), kx0:kx0 + (sx1 - sx0)] * amp
    for c in range(3):
        buf[sy0:sy1, sx0:sx1, c] += sub * col[c]


def route(buf, s, P, col, phase, rng, nfib=10, spread=26.0, fibw=1.0,
          fib_amp=0.30, wob=3.0, freq=1.4, grow=1.4, steps=900,
          beads=0, bead_amp=3.0, bead_len=0.09, bead_r=1.6,
          packets=0, packet_w=0.05, back=False, taper=0.10,
          env=None, soft=False,
          pulse=0, pulse_len=0.075, pulse_amp=6.0, pulse_w=1.0):
    """
    nfib distinct fibres with slight per-fibre wobble; beads ride them.

    fib_amp   brightness of the fibre itself
    bead_amp  brightness of a bead head
    bead_len  bead tail length in arc fraction
    packets   number of travelling brightness packets (0 = uniform fibre)
    """
    u, base, nrm = arclen(P, steps)
    gw = (0.36 + 0.64 * u ** grow)[:, None]
    edge = np.clip(np.minimum(u, 1 - u) / max(taper, 1e-4), 0.0, 1.0) ** 0.55

    lanes = []
    lo = -(nfib - 1) / 2.0
    den = abs(lo) if nfib > 1 else 1.0
    for j in range(nfib):
        f = (lo + j) / den
        off = f * spread
        wa = wob * rng.uniform(0.35, 1.15)
        wp = rng.uniform(0.0, 1.0)
        wf = freq * rng.uniform(0.8, 1.35)
        pts = base + nrm * (off + wa * np.sin(2 * np.pi * (wf * u + wp)))[:, None] * gw
        lanes.append(pts)

    # ---- fibres
    for pts in lanes:
        a = fib_amp * edge
        if packets > 0:
            mod = np.zeros_like(u)
            for q in range(packets):
                c = (phase + q / packets) % 1.0
                dd = np.abs(u - c)
                dd = np.minimum(dd, 1.0 - dd)
                mod += np.exp(-(dd ** 2) / (2 * packet_w ** 2))
            a = a * (0.55 + 1.5 * np.clip(mod, 0, 2.0))
        line_add(buf, pts[:, 0] * s, pts[:, 1] * s, a, col)

    # ---- travelling bright segments (the line itself lighting up)
    # Drawn with the same line_add + same width as the fibre above, so a lit
    # segment is EXACTLY as thick as the thread -- no blob, no bulge.
    if pulse > 0:
        for pi in range(int(pulse)):
            pts = lanes[int(rng.integers(0, len(lanes)))]
            head = (phase + pi / float(pulse)) % 1.0
            if back:
                head = 1.0 - head
            span = max(0.012, pulse_len)
            # t: 0 at the tail of the segment, 1 at its head
            rel = (u - (head - span)) / span
            prof = np.where((rel >= 0.0) & (rel <= 1.0),
                            np.sin(np.pi * np.clip(rel, 0.0, 1.0)) ** 0.75, 0.0)
            # fade the pulse away near both ends of the route so it never
            # appears or vanishes on a hard edge
            prof = prof * np.clip(np.minimum(u, 1.0 - u) / 0.03, 0.0, 1.0)
            if prof.max() > 1e-3:
                line_add(buf, pts[:, 0] * s, pts[:, 1] * s,
                         prof.astype(np.float32) * pulse_amp * (pulse_w ** 0.5), col)

    # ---- beads
    if beads <= 0:
        return

    if soft:
        # 无极渐变: one particle = one tapered streak. Brightness and radius
        # both reach exactly 0 at the tail and at the nose, so the head is not a
        # dot and the tail is not a stub -- it dissolves into the thread.
        for _ in range(beads):
            v0 = (rng.random() + phase * rng.uniform(0.85, 1.15)) % 1.0
            pts_lane = lanes[int(rng.integers(0, len(lanes)))]
            extent = max(bead_len, 0.012) * rng.uniform(0.85, 1.15)
            n = 16
            for i in range(n):
                uu = i / (n - 1.0)
                t = (v0 - extent * (1.0 - uu)) if not back else (v0 + extent * uu)
                if t < 0.0 or t > 1.0:
                    continue
                a = float(taper_alpha(np.array([uu]))[0]) * bead_amp * 6.0
                if a <= 1e-3:
                    continue
                r = float(taper_radius(np.array([uu]), bead_r, 0.0)[0])
                # follow the same lateral lane as the fibre it rides
                t_idx = int(round(t * (len(u) - 1)))
                t_idx = max(0, min(len(pts_lane) - 1, t_idx))
                p = pts_lane[t_idx]
                blob_add(buf, p[0] * s, p[1] * s, max(0.75, r * s), a, col)
        return

    for _ in range(beads):
        v0 = (rng.random() + phase * rng.uniform(0.85, 1.15)) % 1.0
        pts = lanes[int(rng.integers(0, len(lanes)))]
        if back:
            rel = (u - v0) % 1.0
            rel = np.where(rel > 0.5, rel - 1.0, rel)
            rel = -rel
        else:
            rel = v0 - u
        ln = bead_len * rng.uniform(0.6, 1.5)
        prof = np.where(rel >= 0.0, np.exp(-rel / (ln * 0.40)), 0.0)
        prof = prof * (rel <= ln * 1.8)
        prof = prof * edge * bead_amp
        line_add(buf, pts[:, 0] * s, pts[:, 1] * s, prof, col)
        i0 = int(np.argmin(np.abs(u - v0)))
        if min(u[i0], 1 - u[i0]) > taper * 1.2:
            blob_add(buf, pts[i0, 0] * s, pts[i0, 1] * s, bead_r * s,
                     bead_amp * 1.15, (1.0, 1.0, 1.0))


def bloom(buf, s, scales=(2.0, 7.0), weights=(0.55, 0.30)):
    a8 = Image.fromarray((np.clip(buf / 6.0, 0, 1) * 255).astype(np.uint8))
    out = np.asarray(a8, np.float32) / 255.0 * 6.0
    for sc, wt in zip(scales, weights):
        if wt <= 0:
            continue
        b = np.asarray(a8.filter(ImageFilter.GaussianBlur(max(0.8, sc * s))),
                       np.float32) / 255.0 * 6.0
        out = out + b * wt
    return out


def tonemap(light, gain=1.6, bg=None):
    L = 1.0 - np.exp(-np.clip(light * gain, 0, 40))
    if bg is None:
        return (np.clip(L, 0, 1) * 255).astype(np.uint8)
    return (np.clip(bg + L * (1.0 - bg), 0, 1) * 255).astype(np.uint8)

# ---------------------------------------------------------------- envelope
# Width multiplier along the route. `mode` picks the shape:
#   "tight"  (default) gather -> spread -> gather
#   "flat"   constant (used for short hops inside the node)
#   "open"   spread -> spread -> gather (fan-out that collapses at the sink)
ENV_SHAPES = {
    "tight": lambda t: 0.30 + 0.70 * (math.sin(math.pi * t) ** 0.85),
    "flat":  lambda t: 1.0,
    "open":  lambda t: 0.55 + 0.45 * (1.0 - t),
}


def envelope(t, mode="tight"):
    """0.30..1.0 multiplier: narrow at both ends, widest in the middle."""
    f = ENV_SHAPES.get(mode or "tight", ENV_SHAPES["tight"])
    if isinstance(t, (int, float)):
        return f(t)
    return np.array([f(float(v)) for v in t], dtype=np.float32)

# ---------------------------------------------------------------- taper
# One particle is a short streak whose thickness and brightness both go to
# EXACTLY zero at each end, so there is no hard dot and no visible cap -- the
# head and tail dissolve into the thread (无极丝滑变细).
#
#   u = 0    tail   thickness 0, brightness 0
#   u = PEAK head   thickness max, brightness max
#   u = 1    nose   thickness 0, brightness 0
TAPER_PEAK = 0.80


def taper_alpha(u, peak=None, rise_pow=0.70, fall_pow=0.75):
    """Brightness along one particle's extent; 0 at both ends."""
    p = TAPER_PEAK if peak is None else peak
    u = np.clip(np.asarray(u, dtype=np.float32), 0.0, 1.0)
    up = np.clip(u / p, 0.0, 1.0)
    dn = np.clip((u - p) / max(1.0 - p, 1e-4), 0.0, 1.0)
    a = (np.power(up, rise_pow) * np.power(1.0 - dn, fall_pow)).astype(np.float32)
    # force exact zeros at the two ends (float32 pow(0,0.7) can leave 1e-8 dust)
    a[u <= 0.0] = 0.0
    a[u >= 1.0] = 0.0
    return a


def taper_radius(u, r_max=1.55, r_min=0.0, peak=None):
    """Thickness along one particle's extent; r_min at both ends."""
    a = taper_alpha(u, peak)
    return (r_min + (r_max - r_min) * a).astype(np.float32)


def taper_width_scale(t, mode="tight"):
    """Bundle-width multiplier along a whole route (gather/spread/gather)."""
    f = ENV_SHAPES.get(mode or "tight", ENV_SHAPES["tight"])
    if isinstance(t, (int, float)):
        return f(float(t))
    return np.array([f(float(v)) for v in t], dtype=np.float32)

# ---------------------------------------------------------------- link states
# A route is in one of three visual states, driven by how recently it carried
# traffic. These thresholds are in phase units (one loop = 1.0).
WARM = 0.18          # still "solid" if used within this
SEG_LEN = 0.085      # length of the travelling bright segment, in arc fraction


def link_state(age):
    """0 = faint(idle), 1 = solid(warm), 2 = bright(active)."""
    if age <= 0.0:
        return 2
    if age <= WARM:
        return 1
    return 0


def pulse_segment(buf, s, P, arc_u, head_t, col, amp, seg_len=None,
                  width=None, steps=26):
    """
    Light a fixed-length segment of the route whose HEAD sits at `head_t`.

    Brightness follows a raised-cosine along the segment and reaches 0 at both
    ends, so the lit patch has no visible start/stop edge -- it looks like light
    travelling through the fibre rather than a bar sliding over it.
    """
    if amp <= 1e-3:
        return
    L = SEG_LEN if seg_len is None else seg_len
    w = width if width is not None else 1.6
    lo = head_t - L
    if lo < 0.0:
        lo = 0.0
    if head_t <= 0.0:
        return

    for i in range(steps):
        f0 = i / float(steps)
        f1 = (i + 1) / float(steps)
        u = lo + (head_t - lo) * (0.5 * (f0 + f1))
        if u < 0.0 or u > 1.0:
            continue
        # position + normal
        p = bez(P, np.array([u]))[0]
        pn = bez(P, np.array([min(1.0, u + 0.004)]))[0]
        t = (u - lo) / max(head_t - lo, 1e-6)          # 0 at tail, 1 at head
        shape = np.sin(np.pi * np.clip((t + 0.02) / 1.04, 0.0, 1.0)) ** 0.7
        a = amp * float(shape)
        if a <= 1e-3:
            continue
        blob_add(buf, p[0] * s, p[1] * s, max(0.9, w * s), a, col)


def draw_link(buf, s, P, col, state, phase, rng=None,
              base_amp=0.055, bright_amp=1.05, width=1.5,
              nfib=6, spread=18.0, wob=2.0):
    """
    Draw one route in the given state (0 faint / 1 solid / 2 bright).

    faint  : dim, broken into dashes
    solid  : continuous, dim
    bright : continuous + a travelling pulse segment
    """
    strands = nfib
    for j in range(strands):
        u_lane = (j / max(strands - 1, 1)) * 2 - 1
        ph = (j * 0.37) % 1.0
        amp = base_amp * (1.0 if state > 0 else 0.55)
        steps = 90
        for i in range(steps):
            t = i / float(steps)
            # idle routes are dashed: skip alternate run lengths
            if state == 0 and (i // 6) % 2 == 1:
                continue
            p = bez(P, np.array([t]))[0]
            pn = bez(P, np.array([min(1.0, t + 0.004)]))[0]
            dx, dy = pn[0] - p[0], pn[1] - p[1]
            dl = np.hypot(dx, dy) or 1.0
            nx, ny = -dy / dl, dx / dl
            off = (u_lane * spread + wob * np.sin(2 * np.pi * (1.4 * t + ph))) * 0.5
            blob_add(buf, (p[0] + nx * off) * s, (p[1] + ny * off) * s,
                     max(0.8, width * s * 0.55), amp, col)

    if state == 2:
        pulse_segment(buf, s, P, None, phase % 1.0, col, bright_amp, width=width)

# ---------------------------------------------------------------- styles
# Presets for the particle grammar. Add a new style here and every route can
# use it by name; nothing else needs to change.
STYLE_PRESETS = {
    # travelling lit SEGMENT: the thread itself brightens. Width == fibre width.
    # Best for: showing data actually flowing along an established link.
    "pulse": dict(pulse=4, pulse_len=0.075, pulse_amp=6.0, beads=0),

    # bright head + long exponential tail. Strong direction, reads like tracer
    # fire. Best for: request paths, packet traces, "something is heading there".
    "missile": dict(beads=22, bead_amp=3.2, bead_len=0.055, bead_r=1.7, soft=True),

    # dense soft clumps: many overlapping blobs form comet clusters.
    # Best for: neural-network activations, memory traffic, particle fields.
    "clump": dict(beads=60, bead_amp=1.5, bead_len=0.030, bead_r=2.4, soft=False),

    # small discrete beads, evenly spaced: countable events.
    # Best for: low-rate control traffic, health checks, discrete RPCs.
    "bead": dict(beads=18, bead_amp=2.2, bead_len=0.020, bead_r=1.2, soft=False),
}


def style_kwargs(name):
    """Merge a style preset into kwargs. Unknown name -> pulse."""
    return dict(STYLE_PRESETS.get(name, STYLE_PRESETS["pulse"]))


def route_styled(buf, s, P, col, phase, rng, style="pulse", **kw):
    """Convenience wrapper: route() with a named particle grammar."""
    merged = style_kwargs(style)
    merged.update(kw)
    return route(buf, s, P, col, phase, rng, **merged)
