# -*- coding: utf-8 -*-
"""
edge_conf.py -- the nginx configuration, as data.

WHY THIS FILE EXISTS
--------------------
Before this, every feature the diagram claimed was typed into a draw call:

    d.text(..., "workers 8", ...)
    d.text(..., "tls 1.3 / h2 / gzip", ...)
    d.text(..., "least_conn / keepalive 64", ...)

So the picture could not answer "is gzip actually on?" -- the answer was a
literal in scene3.py. Turning a module off meant editing a string in the
renderer, and the side panel had no way to reflect it at all.

Now the configuration is one dict. The renderer reads its labels from here, and
the panel renders a module list from the same source, so a module that is off
disappears from BOTH instead of being contradicted by one of them.

To model a different deployment, copy this dict, change what is enabled, and
pass it through -- nothing in the drawing code needs to know.
"""
from __future__ import annotations

CONF = {
    # ---- process model ----
    "workers": 8,
    "worker_connections": 10240,

    # ---- transport ----
    "tls": {"enabled": True, "version": "1.3"},
    "http2": {"enabled": True},
    "gzip": {"enabled": True},
    "keepalive_timeout": 64,

    # ---- load balancing ----
    "upstream": {
        "method": "least_conn",
        "max_fails": 3,
        "fail_timeout": 7,
        "slow_start": 6,
    },

    # ---- request policing ----
    "limit_req": {
        "enabled": True,
        "zone": "api",
        "rate": 12000,
        "burst": 18000,
        "nodelay": True,
    },
    "deny": {
        "enabled": True,
        "rule": "map $http_user_agent $deny",
        "rps": 50,
    },

    # ---- caching ----
    "proxy_cache": {
        "enabled": True,
        "zone": "static",
        "hit_ratio": 0.215,
    },

    # ---- long-lived connections ----
    "ws_grpc": {"enabled": True, "conns": 3412},

    # ---- resilience ----
    "proxy_next_upstream": {"enabled": True},
    "health_check": {"enabled": True, "mode": "passive"},
}


def label_tls(c=CONF):
    if not c["tls"]["enabled"]:
        return "tls off"
    parts = ["tls " + c["tls"]["version"]]
    if c["http2"]["enabled"]:
        parts.append("h2")
    if c["gzip"]["enabled"]:
        parts.append("gzip")
    return " / ".join(parts)


def label_upstream(c=CONF):
    u = c["upstream"]
    return "%s / keepalive %d" % (u["method"], c["keepalive_timeout"])


def label_burst(c=CONF):
    lr = c["limit_req"]
    if not lr["enabled"]:
        return "limit_req off"
    return "limit_req zone=%s burst=%s%s" % (
        lr["zone"], format(lr["burst"], ","), " nodelay" if lr["nodelay"] else "")


def modules(c=CONF):
    """Flatten the config into rows the side panel can render.

    Each row is (name, on, detail). A disabled module is still listed, greyed,
    so the panel reads as a complete configuration rather than a highlights
    reel -- "gzip off" is information, absence is not.
    """
    out = []
    lr = c["limit_req"]
    out.append(("limit_req", lr["enabled"],
                "zone=%s %s/s" % (lr["zone"], format(lr["rate"], ","))))
    pc = c["proxy_cache"]
    out.append(("proxy_cache", pc["enabled"],
                "hit %.1f%%" % (pc["hit_ratio"] * 100)))
    up = c["upstream"]
    out.append((up["method"], True,
                "max_fails=%d" % up["max_fails"]))
    out.append(("health_check", c["health_check"]["enabled"],
                c["health_check"]["mode"]))
    out.append(("keepalive", c["keepalive_timeout"] > 0,
                "%ds" % c["keepalive_timeout"]))
    out.append(("tls " + c["tls"]["version"], c["tls"]["enabled"],
                "h2" if c["http2"]["enabled"] else "-"))
    out.append(("gzip", c["gzip"]["enabled"], "on" if c["gzip"]["enabled"] else "off"))
    ws = c["ws_grpc"]
    out.append(("ws / grpc", ws["enabled"],
                "%s conns" % format(ws["conns"], ",") if ws["enabled"] else "off"))
    out.append(("deny map", c["deny"]["enabled"], "%d r/s" % c["deny"]["rps"]))
    out.append(("next_upstream", c["proxy_next_upstream"]["enabled"],
                "on" if c["proxy_next_upstream"]["enabled"] else "off"))
    return out


if __name__ == "__main__":
    print("workers        :", CONF["workers"])
    print("tls label      :", label_tls())
    print("upstream label :", label_upstream())
    print("burst label    :", label_burst())
    print()
    print("modules:")
    for name, on, detail in modules():
        print("  %-14s %-3s %s" % (name, "on" if on else "off", detail))
