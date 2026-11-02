# -*- coding: utf-8 -*-
"""Headless screenshot helper for the photon-flow HTML pages.

Usage:
    python shot.py <html> <out.png> [query] [width] [height]

Query is appended as ?query (or &query if the path already has '?').
The page is rendered with DPR locked to 1 so the shot is 1:1 with layout px.
"""
import sys
import pathlib
from playwright.sync_api import sync_playwright


def shot(html, out, query="", w=1600, h=960, wait=3500):
    p = pathlib.Path(html).resolve()
    url = p.as_uri()
    if query:
        url += ("&" if "?" in url else "?") + query
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox", "--disable-gpu",
                                     "--force-color-profile=srgb"])
        pg = b.new_page(viewport={"width": w, "height": h},
                        device_scale_factor=1)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append("console." + m.type + ": " + m.text)
              if m.type in ("error", "warning") else None)
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(wait)
        pg.screenshot(path=str(out))
        info = pg.evaluate("""() => {
            const c = document.getElementById('c');
            const r = {w: c ? c.width : 0, h: c ? c.height : 0,
                       cw: c ? c.clientWidth : 0, ch: c ? c.clientHeight : 0};
            if (window.__stats) Object.assign(r, window.__stats);
            return r;
        }""")
        b.close()
    print("wrote", out, info)
    for e in errs[:12]:
        print("  ERR", e)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        raise SystemExit(__doc__)
    shot(a[0], a[1],
         a[2] if len(a) > 2 else "",
         int(a[3]) if len(a) > 3 else 1600,
         int(a[4]) if len(a) > 4 else 960)
