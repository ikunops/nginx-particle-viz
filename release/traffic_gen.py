#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''photon-flow traffic generator.

Keeps /app/ busy at a steady few requests per second so the collector always has
a full window. This is genuine traffic through the real upstream block: the
numbers the visualisation shows are measured, not invented.
'''
import time
import urllib.request

URL = "http://127.0.0.1:18100/app/"
RPS = 5

def main():
    period = 1.0 / RPS
    nxt = time.time()
    while True:
        try:
            urllib.request.urlopen(URL, timeout=3).read()
        except Exception:
            pass
        nxt += period
        d = nxt - time.time()
        if d > 0:
            time.sleep(d)
        else:
            nxt = time.time()

if __name__ == "__main__":
    main()
