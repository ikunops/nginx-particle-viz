# -*- coding: utf-8 -*-
"""
Audit every lane in scene3.py: does it START and END on a real node?

Nodes are modelled as either a circle (client groups, ports, core) or a
rectangle (upstream cards), and distance is measured to the SURFACE, so a lane
that correctly touches a card's left edge scores 0.
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene3 as S
import numpy as np

CIRCLES = []      # (name, cx, cy, r)
BOXES = {}        # name -> (x0, y0, x1, y1)

for i, g in enumerate(S.GROUPS):
    CIRCLES.append(("group:%s" % g[0], S.CLIENT_X, g[3], 34.0))
CIRCLES.append(("ingress", S.INGRESS[0], S.INGRESS[1], 10.0))
CIRCLES.append(("bucket", S.BUCKET[0], S.BUCKET[1], 14.0))
CIRCLES.append(("trunk-junction", S.TRUNK_X0, 450.0, 12.0))
CIRCLES.append(("node-core", S.NGINX[0], S.NGINX[1], 0.0))
CIRCLES.append(("cache-store", S.NGINX[0] + 20.0, S.NGINX[1] - 34.0, 16.0))
for i in range(len(S.BACK_YS)):
    px, py = S.port(i, S.NG_R * 0.98)
    CIRCLES.append(("port%d" % i, px, py, 10.0))
for i, uy in enumerate(S.BACK_YS):
    BOXES["card:app-0%d" % (i + 1)] = (
        S.BOX_L, uy - S.BOX_H / 2.0, S.BOX_L + S.BOX_W, uy + S.BOX_H / 2.0)


def gap(p):
    best = (None, 1e9)
    for name, cx, cy, r in CIRCLES:
        d = max(0.0, math.hypot(p[0] - cx, p[1] - cy) - r)
        if d < best[1]:
            best = (name, d)
    for name, box in BOXES.items():
        x0, y0, x1, y1 = box
        dx = max(x0 - p[0], 0.0, p[0] - x1)
        dy = max(y0 - p[1], 0.0, p[1] - y1)
        d = math.hypot(dx, dy)
        if d < best[1]:
            best = (name, d)
    return best


P_WS = [(S.port(0)[0] + 10.0, S.port(0)[1] - 10.0),
        (896.0, 246.0), (1002.0, 122.0), (S.BOX_L + 30.0, 108.0)]

lanes = [("trunk", S.P_TRUNK)]
for i in range(len(S.GROUPS)):
    lanes.append(("group%d" % i, S.p_group(i)))
for i in range(len(S.BACK_YS)):
    lanes.append(("comb%d" % i, S.p_comb(i)))
    lanes.append(("fan%d" % i, S.p_up(i)))
    lanes.append(("probe%d" % i, S.p_probe(i)))
lanes += [("cacheIn", S.P_CACHE), ("cacheOut0", S.p_ret(0)),
          ("reject3", S.p_rej(3)), ("limited3", S.p_limited(3)),
          ("deny", S.P_DENY), ("redis21", S.p_redis(2, 0)),
          ("ws", P_WS), ("cacheOut1", S.p_ret(1)),
          ("reject0", S.p_rej(0)), ("limited0", S.p_limited(0))]

print("%-11s %-13s %-17s %-13s %-17s" % ("lane", "start", "nearest", "end", "nearest"))
print("-" * 80)
bad = []
for name, pts in lanes:
    p0 = S.F.bez(pts, np.array([0.0]))[0]
    p1 = S.F.bez(pts, np.array([1.0]))[0]
    n0, d0 = gap(tuple(p0))
    n1, d1 = gap(tuple(p1))
    f0 = " <S" if d0 > 8 else ""
    f1 = " <E" if d1 > 8 else ""
    if d0 > 8 or d1 > 8:
        bad.append(name)
    print("%-11s (%4.0f,%3.0f) %-15s (%4.0f,%3.0f) %-15s%s%s" % (
        name, p0[0], p0[1], "%s %.0f" % (n0, d0),
        p1[0], p1[1], "%s %.0f" % (n1, d1), f0, f1))

print()
print("DANGLING:", bad if bad else "none  -- every lane lands on a node")
