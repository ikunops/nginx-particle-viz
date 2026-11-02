# -*- coding: utf-8 -*-
"""
STYLE TEMPLATES — reusable particle grammars, kept for future work.

Background
----------
We cycled through several visual grammars while iterating on the nginx scene.
Only one ("pulse": the fibre lights up in travelling segments) is what the
current scene uses. The others were NOT wrong — they simply were not the right
choice for THIS scene. Missile heads and particle clumps are exactly what you
want for, say, a neural-network activation visualisation, a packet trace, or a
memory-access graph.

So they live here as named presets you can switch on with one argument:

    import fibre as F
    F.route(buf, s, P, col, phase, rng, style="missile", beads=24, bead_amp=6)

Presets
-------
    "pulse"    (default in the nginx scene)  travelling lit segments, width-exact
    "missile"  bright head + long decay tail; direction unmistakable
    "clump"    dense soft blobs, comet clusters; great for "thousands of tiny
               things moving" (neural activations, particle fields)
    "bead"     small discrete beads evenly spaced; discrete-event traffic

All four share the same fibre underlay, so you can mix them per route.
"""
import io, os

HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "fibre.py")
s = io.open(p, encoding="utf-8").read()

if "STYLE_PRESETS" in s:
    print("styles already defined")
else:
    block = '''

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
'''
    s = s.rstrip() + block
    io.open(p, "w", encoding="utf-8").write(s)
    print("fibre.py: 4 style presets added")
