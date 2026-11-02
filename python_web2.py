# -*- coding: utf-8 -*-
"""
Frame-sequence player built on scene3.py -- the SAME renderer that produced
contact-max-lifecycle.png.

The earlier python_web.py reimplemented the look from scratch and drifted: it
ended up with sparse, dim, hairline strands because I rebuilt the fibre
primitives instead of reusing the ones that already looked right. That was the
mistake. Here the frames come from scene3.render(st), verbatim, so the player is
guaranteed to match the static stills pixel for pixel at the same size.

scene3.render takes a state dict whose "t" drives every animated phase, so a
smooth loop is just a sweep of st["t"] over one period.

The lifecycle state (bucket level, health, which upstream is selected) is also
swept, so the animation tells the same story the three stills told.
"""
import os, sys, io, math, time, base64
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene3 as S

OUT = os.path.join(HERE, "out")

# ------------------------------------------------------------------ state sweep
# 36 frames: a full bucket drain/refill cycle plus an app-03 eject/recover.
# Values interpolate smoothly so nothing jumps between frames.
# ------------------------------------------------------------------ model
# One integrator produces the whole cycle. Everything shown on screen is
# derived from it, so the numbers and the narrative cannot drift apart.

ZONE_RATE = 12000.0     # limit_req zone=api rate, r/s
ZONE_BURST = 18000.0    # limit_req burst, requests (large zone: this is a
                        # 150k r/s edge, so the burst is seconds of headroom)
SEC_PER_FRAME = 0.5     # scenario seconds per frame; 36 frames = 18 s.
                        # Real bursts empty in milliseconds -- compressed so
                        # the gauge is watchable.
MAX_FAILS = 3           # nginx max_fails
FAIL_TIMEOUT = 7        # frames an upstream stays ejected
SLOW_START = 6          # frames of reduced weight after returning

_TIMELINE = {}
_TIMELINE_N = [0]


def _build_timeline(n):
    bucket = ZONE_BURST
    fails = [0, 0, 0, 0]
    was_shedding = False
    eject_at = [-1, -1, -1, -1]      # frame index when the ejection ends
    slow_at = [-1, -1, -1, -1]       # frame index when slow start ends
    events = []
    out = []

    BASE_W = [0.34, 0.28, 0.24, 0.14]

    for i in range(n):
        u = i / float(n)
        t = u * n * SEC_PER_FRAME          # 0 .. 18 s

        # ---- demand: a sustained surge plus a smaller second bump --------
        # surge well above the zone rate, then a trough that lets the burst
        # refill. Without the trough the bucket could never recover and the
        # "relieved" state would never be reachable.
        surge = math.exp(-((u - 0.34) / 0.145) ** 2)
        trough = math.exp(-((u - 0.60) / 0.10) ** 2)
        demand = 11000.0 + 6900.0 * surge - 1900.0 * trough

        # ---- token bucket ------------------------------------------------
        excess = max(0.0, demand - ZONE_RATE)
        spare = max(0.0, ZONE_RATE - demand)
        bucket = bucket - excess * SEC_PER_FRAME + spare * SEC_PER_FRAME
        bucket = max(0.0, min(ZONE_BURST, bucket))
        bfrac = bucket / ZONE_BURST

        # while there is burst left it absorbs the overload; once it is gone
        # the excess is what nginx actually rejects
        rejected = (demand - ZONE_RATE) if (bfrac <= 0.02 and demand > ZONE_RATE) else 0.0
        rejected = max(0.0, rejected)

        # burst transitions are the events worth logging: these are the
        # frames where the diagram visibly changes character
        shedding = rejected > 1.0
        if shedding and not was_shedding:
            events.append((i, "shed", -1,
                           "burst exhausted, shedding %s r/s" % format(int(rejected), ",")))
        elif was_shedding and not shedding:
            events.append((i, "refill", -1, "burst refilling, shedding stopped"))
        was_shedding = shedding

        denied = 50.0
        after_deny = max(0.0, demand - denied - rejected)
        cache_hit = after_deny * 0.215
        four_xx = min(236.0, after_deny * 0.022)
        up_total = max(0.0, after_deny - cache_hit - four_xx)

        # ---- app-03 degrades, and the counter is what ejects it ----------
        # after the surge has passed: app-03 starts responding slowly
        deg = 0.0
        if 0.58 <= u <= 0.82:
            deg = math.sin(math.pi * (u - 0.62) / 0.28)
        lat = [44.0, 51.0, 42.0 + 900.0 * deg, 61.0]
        err = [0.0, 0.0, 55.0 * deg, 0.0]          # percent of requests failing

        health = ["ok"] * 4
        for k in range(4):
            if eject_at[k] >= 0 and i < eject_at[k]:
                health[k] = "fail"
            elif eject_at[k] >= 0 and i >= eject_at[k]:
                # fail_timeout expired: probe it, come back slowly
                eject_at[k] = -1
                slow_at[k] = i + SLOW_START
                health[k] = "slow"
                events.append((i, "up", k, "returned to pool, slow start"))
            elif slow_at[k] >= 0:
                if i < slow_at[k]:
                    health[k] = "slow"
                else:
                    slow_at[k] = -1
                    fails[k] = 0

        # a slow/failing upstream accumulates max_fails
        for k in range(4):
            if health[k] != "fail" and (lat[k] > 500.0 or err[k] > 20.0):
                fails[k] += 1
                if fails[k] >= MAX_FAILS:
                    eject_at[k] = i + FAIL_TIMEOUT
                    fails[k] = 0
                    # mark it failing THIS frame: otherwise the frame that logs
                    # "ejected" still draws the upstream as healthy, and the
                    # panel disagrees with its own event log
                    health[k] = "fail"
                    events.append((i, "eject", k,
                                   "max_fails=%d, ejected for %ds" % (MAX_FAILS, FAIL_TIMEOUT)))
            elif health[k] != "fail":
                fails[k] = 0

        # ---- weights follow health --------------------------------------
        w = []
        for k in range(4):
            if health[k] == "fail":
                w.append(0.0)
            elif health[k] == "slow":
                w.append(BASE_W[k] * 0.35)
            else:
                w.append(BASE_W[k])
        sw = sum(w) or 1.0
        up = [up_total * x / sw for x in w]

        # ---- overall status, most severe wins ---------------------------
        if rejected > 1.0:
            status = "throttled"
        elif any(h == "fail" for h in health):
            status = "degraded"
        elif any(h == "slow" for h in health):
            status = "recovering"
        elif bfrac < 0.35:
            status = "saturated"
        else:
            status = "healthy"

        # highlight the busiest healthy upstream, or the one in trouble
        sel = max(range(4), key=lambda k: (health[k] in ("fail", "slow"), up[k]))

        # ---- note: one sentence describing the dominant fact ------------
        if status == "throttled":
            note = "bucket empty, %s r/s rejected" % format(int(rejected), ",")
        elif status == "degraded":
            k = health.index("fail")
            note = "app-0%d ejected, traffic redistributed" % (k + 1)
        elif status == "recovering":
            k = health.index("slow")
            note = "app-0%d back in pool, slow start" % (k + 1)
        elif status == "saturated":
            note = "burst low, %.0f%% left" % (bfrac * 100)
        else:
            note = "all four upstreams healthy"

        recent = [e for e in events if i - e[0] <= 12][-4:]

        out.append({
            "t": round(t, 2),
            "u": round(u, 4),
            "demand": int(round(demand)),
            "zone_rate": int(ZONE_RATE),
            "zone_burst": int(ZONE_BURST),
            "bucket": round(bfrac, 3),
            "bucket_left": int(round(bucket)),
            "limited": int(round(rejected)),
            "deny": int(round(denied)),
            "cache": int(round(cache_hit)),
            "fourxx": int(round(four_xx)),
            "pool": int(round(up_total)),
            "up": [int(round(v)) for v in up],
            "health": list(health),      # scene3 reads this name
            "up_state": list(health),
            "up_fails": list(fails),
            "uptime": note,             # scene3 footer, kept for compatibility
            "latency": [int(round(v)) for v in lat],
            "sel": int(sel),
            "ws": status not in ("throttled",),
            "status": status,
            "note": note,
            "events": [{"age": i - e[0], "kind": e[1],
                        "who": ("edge" if e[2] < 0 else "app-0%d" % (e[2] + 1)),
                        "text": e[3]} for e in recent],
        })

    return out


def state_for(i, n):
    """Cycle state. Cached because every consumer asks for the same list."""
    if _TIMELINE_N[0] != n or n not in _TIMELINE:
        _TIMELINE[n] = _build_timeline(n)
        _TIMELINE_N[0] = n
    return _TIMELINE[n][i % n]


# ------------------------------------------------------------------ build
def build(n_frames=40, out_w=2560, quality=95):
    t0 = time.time()
    frames = []
    states = []
    for i in range(n_frames):
        st = state_for(i, n_frames)
        img = S.render(st, out_w=out_w, seed=7)      # <- the reference renderer
        b = io.BytesIO()
        img.save(b, format="WEBP", lossless=False, quality=86, method=6)
        frames.append(base64.b64encode(b.getvalue()).decode("ascii"))
        # everything the telemetry panel needs, from this frame's state
        states.append({
            "t": st["t"],
            "demand": st["demand"],
            "zone": st["zone_rate"],
            "burst": st["zone_burst"],
            "pool": st["pool"],
            "cache": st["cache"],
            "fourxx": st["fourxx"],
            "limited": st["limited"],
            "deny": st["deny"],
            "bucket": st["bucket"],
            "bucketLeft": st["bucket_left"],
            "app3": st["health"][2],
            "up": st["up"],
            "upState": st["up_state"],
            "upFails": st["up_fails"],
            "latency": st["latency"],
            "sel": st["sel"],
            "ws": bool(st["ws"]),
            "status": st["status"],
            "note": st["note"],
            "events": st["events"],
        })
        if i % 5 == 0:
            print("  frame %d/%d  %.1fs  (bucket %.0f%%, app-03 %s)" % (
                i + 1, n_frames, time.time() - t0,
                st["bucket"] * 100, st["health"][2]))

    payload = "[" + ",".join('"%s"' % f for f in frames) + "]"
    import json as _json
    state_js = _json.dumps(states, separators=(",", ":"))
    h = int(round(out_w * 900 / 1600))
    import edge_conf as _EC
    _mods = _json.dumps(_EC.modules(), separators=(",", ":"))
    html = (TPL.replace("__W__", str(out_w)).replace("__H__", str(h)).replace(
        "__FRAMES__", payload).replace("__STATES__", state_js).replace("__N__", str(n_frames))
        .replace("__MODULES__", _mods)
        .replace("__WORKERS__", str(_EC.CONF["workers"]))
        .replace("__WSCONN__", format(_EC.CONF["ws_grpc"]["conns"], ",")))
    path = os.path.join(OUT, "photon-flow-python.html")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", path, os.path.getsize(path) // 1024, "KB in %.1fs" % (time.time() - t0))
    return path


TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Photon Flow — Python renderer</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #04070c; overflow: hidden; }
  body { display: flex; flex-direction: column;
         font-family: ui-monospace, Menlo, Consolas, monospace; }
  #main { flex: 1 1 auto; min-height: 0; display: flex; align-items: stretch; }
  #wrap { flex: 1 1 auto; min-width: 0; display: flex;
          align-items: center; justify-content: center; overflow: hidden; }
  canvas { display: block; }

  /* telemetry column: appears only when there is spare width */
  #side {
    flex: 0 0 286px; display: none; flex-direction: column; gap: 8px;
    padding: 12px 12px 12px 4px; overflow-y: auto; overflow-x: hidden;
    font-size: 11.5px; color: #8fb3c7;
  }
  #side.on { display: flex; }
  .card {
    border: 1px solid #172a35; border-radius: 8px; padding: 8px 11px 9px;
    background: rgba(7,13,20,.72);
  }
  .card h4 {
    margin: 0 0 6px; font-size: 10px; font-weight: 600; letter-spacing: .1em;
    color: #5f8499; text-transform: uppercase;
  }
  .row { display: flex; justify-content: space-between; align-items: baseline;
         margin: 2px 0; }
  .row b { color: #cfe6f2; font-weight: 600; font-variant-numeric: tabular-nums; }
  .row.sm { font-size: 10.5px; color: #7d9db0; }
  .row.sm b { color: #b6cedd; font-weight: 500; }

  /* ---- status pill ---- */
  .pill {
    display: inline-block; padding: 3px 9px; border-radius: 999px;
    font-size: 10.5px; font-weight: 700; letter-spacing: .1em;
    text-transform: uppercase; margin-bottom: 6px;
  }
  .pill.healthy    { color: #0a1710; background: #4dffb8; }
  .pill.saturated  { color: #1a1200; background: #ffc23d; }
  .pill.throttled  { color: #1d0703; background: #ff5f4a; }
  .pill.degraded   { color: #1a0d00; background: #ff8a3d; }
  .pill.recovering { color: #04141f; background: #7cc8ff; }
  .reason { font-size: 10.5px; color: #7d9db0; line-height: 1.45; }

  /* ---- demand vs capacity ---- */
  .cap { position: relative; height: 6px; border-radius: 3px;
         background: #16232c; margin: 5px 0 4px; overflow: hidden; }
  .cap i { position: absolute; left: 0; top: 0; bottom: 0; display: block;
           border-radius: 3px; }
  .cap .ok  { background: #3ec6ff; }
  .cap .over{ background: #ff5f4a; }
  .cap u { position: absolute; top: -2px; bottom: -2px; width: 0;
           border-left: 1px dashed #6f8fa3; }

  /* ---- upstream rows ---- */
  .up { display: flex; align-items: center; gap: 5px; margin: 3px 0 0; }
  .up .nm { flex: 0 0 44px; color: #9fbccd; font-size: 10.5px; }
  .up .st { flex: 0 0 44px; text-align: left; font-size: 9px;
            letter-spacing: .05em; }
  .up .vl { flex: 1 1 auto; text-align: right; color: #cfe6f2;
            font-variant-numeric: tabular-nums; font-size: 10.5px; }
  .up .lt { flex: 0 0 42px; text-align: right; font-size: 9.5px;
            font-variant-numeric: tabular-nums; }
  .up .bar { height: 3px; }
  .st-ok   { color: #4dffb8; }
  .st-slow { color: #ffc23d; }
  .st-fail { color: #ff5f4a; }
  .lat-ok  { color: #6f8fa3; }
  .lat-mid { color: #ffc23d; }
  .lat-bad { color: #ff5f4a; }

  .k-accept { color: #3ec6ff; } .k-cache { color: #6affec; }
  .k-429   { color: #ff5f4a; } .k-deny  { color: #8f9aa8; }
  .k-retry { color: #ffae3c; } .k-ws    { color: #bee6ff; }

  /* ---- events ---- */
  .ev { font-size: 10px; color: #7d9db0; margin: 2px 0; white-space: nowrap;
        overflow: hidden; text-overflow: ellipsis; }
  .ev b { color: #ffab6b; font-weight: 600; }

  /* ---- empty state ---- */
  .none { font-size: 10px; color: #4b6a7c; }
  /* configuration modules: a complete list, so "off" is visible too */
  .mods { margin: 2px 0 0; }
  .mods .m { display: flex; justify-content: space-between; align-items: baseline;
             font-size: 10px; line-height: 1.62; }
  .mods .m span { color: #9fbccd; }
  .mods .m b { font-weight: 500; color: #6f8fa3;
               font-variant-numeric: tabular-nums; }
  .mods .m.off span, .mods .m.off b { color: #45606f; }
  .mods .m.off span { text-decoration: line-through; }

  /* ---- control bar ---- */
  #bar {
    flex: 0 0 auto; display: flex; align-items: center; gap: 10px;
    padding: 8px 16px; border-top: 1px solid #12222d;
    background: #060a10; font-size: 11.5px; color: #7f9fb2;
  }
  #bar .sep { width: 1px; height: 16px; background: #16262f; }
  .btn {
    appearance: none; border: 1px solid #1d3542; border-radius: 6px;
    background: #0b141c; color: #a8c8da; padding: 4px 12px;
    font: inherit; font-size: 11.5px; cursor: pointer;
  }
  .btn:hover { border-color: #2c5468; color: #d6ecf7; }
  .hint { color: #6d8ea2; }
  .hint b { color: #cfe6f2; }
  kbd {
    display: inline-block; padding: 1px 5px; margin: 0 1px;
    border: 1px solid #1d3542; border-radius: 4px; background: #0b141c;
    color: #9dbdce; font: inherit; font-size: 10.5px;
  }
  input[type=range] {
    appearance: none; width: 150px; height: 3px; border-radius: 2px;
    background: #16232c; outline: none;
  }
  input[type=range]::-webkit-slider-thumb {
    appearance: none; width: 13px; height: 13px; border-radius: 50%;
    background: #d6f4ff; border: 1px solid #5bd0ff; cursor: pointer;
  }
  #fps { margin-left: auto; color: #62849a; font-variant-numeric: tabular-nums; }
  .tiny { font-size: 10px; color: #6d8ea2; line-height: 1.5; }

  #err { position: fixed; inset: 0; display: none; padding: 34px 40px;
         background: #0b0f14; color: #ff9d8a; font-size: 13px;
         white-space: pre-wrap; overflow: auto; z-index: 99; }
</style>
</head>
<body>
<div id="main">
  <div id="wrap"><canvas id="c"></canvas></div>
  <div id="side">
    <div class="card">
      <span class="pill healthy" id="s-status">healthy</span>
      <div class="reason" id="s-status-sub">&nbsp;</div>
    </div>

    <div class="card">
      <h4>ingress vs capacity</h4>
      <div class="row"><span>demand</span><b id="s-demand">11,000</b></div>
      <div class="cap">
        <i class="ok" id="b-demand-ok" style="width:100%"></i>
        <i class="over" id="b-demand-over" style="width:0%;left:100%"></i>
        <u id="m-zone" style="left:100%"></u>
      </div>
      <div class="row sm"><span>limit_req zone=api</span><b id="s-zone">12,000</b></div>
      <div class="row sm"><span class="k-429">shed by rate limit</span><b id="s-shed">0</b></div>
    </div>

    <div class="card">
      <h4>edge</h4>
      <div class="row"><span>burst remaining</span><b id="s-bucket">18,000</b></div>
      <div class="bar"><i id="b-bucket" style="width:100%;background:#ffd65a"></i></div>
      <div class="row sm"><span>workers</span><b>__WORKERS__</b></div>
      <div id="s-modules" class="mods"></div>
      <div class="row sm" style="margin-top:6px"><span class="k-ws">WS / gRPC conns</span><b id="s-ws">__WSCONN__</b></div>
    </div>

    <div class="card">
      <h4>upstream pool</h4>
      <div id="s-pool-rows"></div>
      <div class="row sm" style="margin-top:7px"><span>least_conn total</span><b id="s-pool">8,361</b></div>
    </div>

    <div class="card">
      <h4>outcomes</h4>
      <div class="row sm"><span class="k-accept">to upstream</span><b id="s-acc">8,361</b></div>
      <div class="row sm"><span class="k-cache">cache hit</span><b id="s-cache">1,800</b></div>
      <div class="row sm"><span class="k-429">429 limited</span><b id="s-lim">0</b></div>
      <div class="row sm"><span class="k-deny">4xx</span><b id="s-4xx">236</b></div>
      <div class="row sm"><span class="k-deny">denied</span><b id="s-deny">50</b></div>
      <div class="row sm"><span>frame</span><b id="s-frame">1/36</b></div>
    </div>
  </div>
</div>
<div id="bar">
  <button class="btn" id="bpause">pause</button>
  <div class="sep"></div>
  <span class="hint">speed</span>
  <input type="range" id="spd" min="0.5" max="3" step="0.05" value="1">
  <b id="spdv" class="hint">1.00x</b>
  <div class="sep"></div>
  <span class="hint"><kbd>space</kbd> pause &nbsp;<kbd>&larr;</kbd><kbd>&rarr;</kbd> speed</span>
  <div id="fps"></div>
</div>
<div id="err"></div>
<script>
var FRAMES = __FRAMES__;
var FRAME_STATE = __STATES__;
window.FRAME_STATE = FRAME_STATE;
var FW = __W__, FH = __H__;
(function () {
  "use strict";
  var errBox = document.getElementById("err");
  function fatal(m) {
    errBox.style.display = "block";
    errBox.textContent = "render failed\\n\\n" + String(m);
  }
  window.addEventListener("error", function (e) {
    fatal((e.message || "unknown") + "\\n" + (e.filename || "") + ":" + (e.lineno || ""));
  });
  try {
    if (!FRAMES || !FRAMES.length) throw new Error("no frames embedded");
    var cv = document.getElementById("c");
    var ctx = cv.getContext("2d", { alpha: false });
    // The backing store must match PHYSICAL pixels. Hard-coding DPR = 1 makes
    // the bitmap cssW wide while the compositor stretches it to
    // cssW * devicePixelRatio -- a 2x magnification through the cheapest
    // filter available, which is what "blurry" actually was.
    var DPR = Math.min(window.devicePixelRatio || 1, 2);
    var sideEl = document.getElementById("side");

    function resize() {
      var main = document.getElementById("main");
      var wrap = document.getElementById("wrap");
      var totalW = window.innerWidth || main.clientWidth;
      var totalH = main.clientHeight || (window.innerHeight - 46);

      // Fit by HEIGHT first so a wider window never shrinks the picture, then
      // reserve room for the telemetry column, then CLAMP to the frame size.
      //
      // The clamp is the important part: a probe showed the canvas being drawn
      // at 1.68x the frame width, which is where the softness came from. The
      // browser cannot invent detail, so we never ask it to.
      var SIDE_W = 286, GAP = 26;
      var ah = Math.max(200, totalH - 10);
      var sc = ah / FH;
      var cssW = Math.round(FW * sc);
      var cssH = Math.round(FH * sc);

      var avail = Math.max(320, totalW - 20);
      var withSide = avail - SIDE_W - GAP;
      var useSide = withSide >= 640;

      if (useSide && cssW > withSide) {
        sc = withSide / FW;
        cssW = Math.round(FW * sc);
        cssH = Math.round(FH * sc);
      } else if (!useSide && cssW > avail) {
        sc = avail / FW;
        cssW = Math.round(FW * sc);
        cssH = Math.round(FH * sc);
      }

      // Hard cap: never display the frame larger than it was rendered.
      var capW = FW / DPR;
      if (cssW > capW) {
        cssW = Math.round(capW);
        cssH = Math.round(FH * (capW / FW));
      }
      sideEl.className = useSide ? "on" : "";

      cv.width = Math.round(cssW * DPR);
      cv.height = Math.round(cssH * DPR);
      cv.style.width = cssW + "px";
      cv.style.height = cssH + "px";
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
    }
    resize();
    window.addEventListener("resize", resize);
    // dragging the window between a 1x and a 2x monitor changes dpr without
    // firing resize, and the canvas would stay at the old density
    if (window.matchMedia) {
      var mq = window.matchMedia("(resolution: " + window.devicePixelRatio + "dppx)");
      var onDpr = function () {
        var nd = Math.min(window.devicePixelRatio || 1, 2);
        if (nd !== DPR) { DPR = nd; resize(); }
      };
      if (mq.addEventListener) mq.addEventListener("change", onDpr);
      else if (mq.addListener) mq.addListener(onDpr);
    }

    var imgs = [], loaded = 0;
    for (var i = 0; i < FRAMES.length; i++) {
      (function (idx) {
        var im = new Image();
        im.onload = function () { if (++loaded === FRAMES.length) start(); };
        im.onerror = function () { fatal("frame " + idx + " failed to decode"); };
        im.src = "data:image/webp;base64," + FRAMES[idx];
        imgs[idx] = im;
      })(i);
    }

    // 0.5x default: at 1.0x the 36-frame loop finished in 1.5 s, which read as
    // flicker rather than flow. 3 s per loop lets a segment be followed.
    var idx = 0, paused = false, speed = 1, last = 0, acc = 0;

    // Deep-link a single frame: #f=14 freezes on frame 14 (1-based). Useful for
    // reviewing an exact state and for taking screenshots without fighting the
    // 24 fps playback.
    var deep = /(?:^|[#&])f=([0-9]+)/.exec(location.hash || "");
    if (deep) {
      idx = Math.max(0, Math.min(FRAMES.length - 1, parseInt(deep[1], 10) - 1));
      paused = true;
    }
    // 12 fps base: 1.0x is meant to read as steady flow, not a flicker.
    // A 36-frame loop takes 3 s at 1.0x; the slider multiplies from there.
    // Configuration modules, injected at build time from edge_conf.py so the
    // panel cannot disagree with the canvas.
    var MODULES = __MODULES__;
    (function () {
      var host = document.getElementById("s-modules");
      if (!host) return;
      var h = "";
      for (var i = 0; i < MODULES.length; i++) {
        var m = MODULES[i];
        h += '<div class="m' + (m[1] ? "" : " off") + '"><span>' + m[0] +
             '</span><b>' + m[2] + '</b></div>';
      }
      host.innerHTML = h;
    })();

    var FPS = 12;
    var bpause = document.getElementById("bpause");
    var spdEl = document.getElementById("spd");
    var spdv = document.getElementById("spdv");
    var fpsEl = document.getElementById("fps");

    function setSpeed(v) {
      speed = Math.max(0.5, Math.min(3, v));
      spdEl.value = speed;
      spdv.textContent = speed.toFixed(2) + "x";
      // fill the track up to the thumb
      var pct = (speed - 0.5) / (3 - 0.5) * 100;
      spdEl.style.background =
        "linear-gradient(to right, #5bd0ff 0%, #5bd0ff " + pct +
        "%, #1c323e " + pct + "%, #1c323e 100%)";
    }
    spdEl.addEventListener("input", function () { setSpeed(parseFloat(spdEl.value)); });
    setSpeed(1);
    bpause.onclick = function () {
      paused = !paused;
      bpause.textContent = paused ? "resume" : "pause";
      bpause.className = "btn" + (paused ? " on" : "");
    };
    window.addEventListener("keydown", function (e) {
      if (e.code === "Space") { bpause.onclick(); e.preventDefault(); }
      else if (e.code === "ArrowRight") { setSpeed(speed + 0.25); }
      else if (e.code === "ArrowLeft") { setSpeed(speed - 0.25); }
    });
    // ---- telemetry: driven by the same state that produced each frame
    var stateRows = document.getElementById("s-pool-rows");

    function setTxt(id, v) {
      var el = document.getElementById(id);
      if (el) el.textContent = v;
    }
    function setBar(id, pct) {
      var el = document.getElementById(id);
      if (el) el.style.width = Math.max(0, Math.min(100, pct)) + "%";
    }

    function updatePanel(i) {
      if (!window.FRAME_STATE || !FRAME_STATE[i]) return;
      var st = FRAME_STATE[i];

      // ---- status pill ---------------------------------------------------
      var pill = document.getElementById("s-status");
      if (pill) {
        pill.className = "pill " + st.status;
        pill.textContent = st.status;
      }
      setTxt("s-status-sub", st.note || "");

      // ---- ingress vs capacity -------------------------------------------
      var zone = st.zone || 12000;
      var dem = st.demand || 0;
      var scale = Math.max(dem, zone) * 1.12;
      var okPct = Math.min(dem, zone) / scale * 100;
      var overPct = Math.max(0, dem - zone) / scale * 100;
      var zonePct = zone / scale * 100;

      var eOk = document.getElementById("b-demand-ok");
      var eOv = document.getElementById("b-demand-over");
      var eMk = document.getElementById("m-zone");
      if (eOk) eOk.style.width = okPct.toFixed(1) + "%";
      if (eOv) {
        eOv.style.left = okPct.toFixed(1) + "%";
        eOv.style.width = overPct.toFixed(1) + "%";
      }
      if (eMk) eMk.style.left = zonePct.toFixed(1) + "%";
      setTxt("s-demand", dem.toLocaleString() + " r/s");
      setTxt("s-zone", zone.toLocaleString() + " r/s");
      setTxt("s-shed", st.limited.toLocaleString() + " r/s");

      // ---- edge -----------------------------------------------------------
      setTxt("s-bucket", (st.bucketLeft || 0).toLocaleString());
      var bb = document.getElementById("b-bucket");
      if (bb) {
        var frac = Math.max(0, Math.min(1, st.bucket || 0));
        bb.style.width = (frac * 100).toFixed(1) + "%";
        bb.style.background = frac < 0.10 ? "#ff5f4a"
                            : frac < 0.35 ? "#ffc23d" : "#ffd65a";
      }
      setTxt("s-ws", st.ws ? "3,412" : "0");

      // ---- upstream pool: rate + health + latency + fail counter ----------
      var html = "";
      for (var k = 0; k < st.up.length; k++) {
        var v = st.up[k];
        var hs = st.upState[k];
        var lat = (st.latency && st.latency[k] != null) ? st.latency[k] : 0;
        var fails = (st.upFails && st.upFails[k]) ? st.upFails[k] : 0;

        var tag = hs === "fail" ? (fails ? "FAIL " + fails + "/3" : "EJECTED")
                : hs === "slow" ? "SLOW" : "ok";
        var cls = hs === "fail" ? "st-fail" : hs === "slow" ? "st-slow" : "st-ok";
        // latency is what makes SLOW legible; colour it by severity
        var lcls = lat > 500 ? "lat-bad" : lat > 200 ? "lat-mid" : "lat-ok";

        var pct = st.pool ? (v / st.pool * 100) : 0;
        var col = ["#4dffb8", "#ffc23d", "#9a8cff", "#ff73a8"][k];

        html += '<div class="up"><span class="nm">app-0' + (k + 1) + '</span>' +
                '<span class="st ' + cls + '">' + tag + '</span>' +
                '<span class="vl">' + v.toLocaleString() + '</span>' +
                '<span class="lt ' + lcls + '">' + lat + 'ms</span></div>' +
                '<div class="bar"><i style="width:' + pct.toFixed(0) +
                '%;background:' + (hs === "fail" ? "#ff5f4a" : col) + '"></i></div>';
      }
      stateRows.innerHTML = html;
      setTxt("s-pool", st.pool.toLocaleString());

      // ---- outcomes -------------------------------------------------------
      setTxt("s-acc", st.pool.toLocaleString());
      setTxt("s-cache", st.cache.toLocaleString());
      setTxt("s-lim", st.limited.toLocaleString());
      setTxt("s-4xx", st.fourxx.toLocaleString());
      setTxt("s-deny", st.deny.toLocaleString());
      setTxt("s-frame", (i + 1) + "/" + FRAMES.length);
    }

    function start() { last = performance.now(); requestAnimationFrame(tick); }
    function tick(now) {
      var raw = (now - last) / 1000; last = now;
      if (!(raw > 0)) raw = 1 / FPS;
      if (!paused) {
        acc += raw * speed;
        var step = 1 / FPS;
        while (acc >= step) { acc -= step; idx = (idx + 1) % imgs.length; }
      }
      var cssW = cv.width / DPR;
      var cssH = cv.height / DPR;
      ctx.clearRect(0, 0, cssW, cssH);
      if (imgs[idx] && imgs[idx].complete) {
        // One resample from the source frame straight onto the device grid.
        // Letting the browser do a second pass on an already-scaled canvas is
        // what doubles the softness.
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(imgs[idx], 0, 0, cssW, cssH);
      }
      if (sideEl.className === "on") updatePanel(idx);
      fpsEl.textContent = Math.round(1 / raw) + " fps · frame " +
                          (idx + 1) + "/" + imgs.length;
      requestAnimationFrame(tick);
    }
  } catch (e) { fatal(e && e.stack ? e.stack : e); }
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    build(n_frames=n)
