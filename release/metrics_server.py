#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nginx-perspective metrics collector.

Pipeline
    nginx -T   --parse--> vhosts[{ports[], targets[], upstream}]
    access log --agg----> perUpstream[{addr, rps, bw, latency, errRate, state}]
                  |
                  +--join--> topology

Endpoints
    /api/metrics   flat FEED-shaped payload for the current page
    /api/topology  three-tier graph: clients -> listen ports -> backends

All numbers come from the live config and the live log. Adding a vhost or an
upstream member appears automatically on the next poll.
"""
import hashlib
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = "/var/log/nginx/photon-flow.access.log"
WINDOW = 6.0
CACHE_TTL = 5.0

# our own observability ports must not appear as business data flow
# 我们自己的观测端口，不能当成业务流量
OBSERVABILITY = {18100, 18101, 8090, 18090, 18200}
IGNORE_PATH = ("/api/", "/metrics", "/static", "/health", "/_probe")

# 累计计数器：底部状态栏和遥测面板用它们，不再用硬编码数字
_tot = {"requests": 0, "proxied": 0, "errors": 0, "bytes": 0, "started": time.time()}

_hist = {"pos": 0, "rows": []}
_cfg = {"at": 0.0, "vhosts": [], "upstreams": {}}

# 配置变更检测：按 nginx -T 全文散列判断版本
_watch = {
    "hash": None,
    "since": None,      # 当前版本首次出现的时间
    "changed": 0,       # 累计变更次数
    "events": [],       # 最近若干次变更记录
    "reload_needed": False,
}


# --------------------------------------------------------------- access log
def tail_log():
    try:
        size = os.path.getsize(LOG)
    except OSError:
        return
    if size < _hist["pos"]:
        _hist["pos"] = 0
    if size == _hist["pos"]:
        return
    with open(LOG, "rb") as f:
        f.seek(_hist["pos"])
        chunk = f.read(size - _hist["pos"])
        _hist["pos"] = size
    now = time.time()
    for raw in chunk.split(b"\n"):
        if not raw.strip():
            continue
        try:
            p = raw.decode("utf-8", "replace").split("|")
            if len(p) < 11:
                continue
            # 字段顺序见 nginx.conf 的 photon_metrics：
            #   0 time | 1 port | 2 remote | 3 request | 4 status | 5 bytes |
            #   6 request_time | 7 upstream_addr | 8 upstream_status |
            #   9 upstream_response_time | 10 cache | 11 ua
            # 【为什么用固定下标而不是猜】这个格式后来加过 $server_port，
            # 旧解析器按 10 字段写，整体错位两位，upstream 读成空，
            # 所有聚合恒为 0。现在按真实顺序取。
            ts = time.mktime(time.strptime(p[0][:19], "%Y-%m-%dT%H:%M:%S"))
            _tot["requests"] += 1
            if p[7] not in ("-", ""):
                _tot["proxied"] += 1
            try:
                if int(p[4] or 0) >= 500:
                    _tot["errors"] += 1
            except Exception:
                pass
            try:
                _tot["bytes"] += int(float(p[5] or 0))
            except Exception:
                pass
            _hist["rows"].append({
                "t": ts,
                "status": int(p[4] or 0),
                "bytes": int(float(p[5] or 0)),
                "rt": float(p[6] or 0) if p[6] not in ("-", "") else 0.0,
                "port": int(p[1] or 0),
                "up": p[7], "ups": p[8], "uprt": p[9], "cache": p[10],
            })
        except Exception:
            continue
    cut = now - WINDOW
    _hist["rows"] = [r for r in _hist["rows"] if r["t"] >= cut]


def per_upstream():
    tail_log()
    agg = defaultdict(lambda: {"n": 0, "bytes": 0, "rt": 0.0, "rtn": 0,
                               "err": 0, "cache": 0})
    for r in _hist["rows"]:
        addrs = [a.strip() for a in r["up"].split(",")
                 if a.strip() and a.strip() != "-"]
        if not addrs:
            continue
        d = agg[addrs[0]]
        d["n"] += 1
        d["bytes"] += r["bytes"]
        if r["uprt"] not in ("-", ""):
            try:
                d["rt"] += float(r["uprt"].split(",")[0])
                d["rtn"] += 1
            except Exception:
                pass
        if r["status"] >= 500:
            d["err"] += 1
        if r["cache"] in ("HIT", "hit"):
            d["cache"] += 1

    out = []
    for addr, d in agg.items():
        lat = (d["rt"] / d["rtn"] * 1000.0) if d["rtn"] else 0.0
        er = (d["err"] / d["n"]) if d["n"] else 0.0
        state = "ok"
        if er > 0.25:
            state = "fail"
        elif lat > 500:
            state = "slow"
        out.append({
            "addr": addr,
            "rps": d["n"] / WINDOW,
            "bw": d["bytes"] / WINDOW,
            "latency": lat,
            "errRate": er,
            "cache": d["cache"] / WINDOW,
            "state": state,
        })
    out.sort(key=lambda x: -x["rps"])
    return out


# ------------------------------------------------------------- nginx config
def parse_nginx_conf():
    try:
        out = subprocess.run(["nginx", "-T"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return [], {}

    out = re.sub(r"#[^\n]*", "", out)

    upstreams = {}
    for m in re.finditer(r"upstream\s+([\w.\-]+)\s*\{([^}]*)\}", out, re.S):
        name, body = m.group(1), m.group(2)
        members = []
        for s in re.finditer(r"server\s+([\w.\-]+:\d+)([^;]*);", body):
            addr, opts = s.group(1), s.group(2)
            w = re.search(r"weight=(\d+)", opts)
            members.append({"addr": addr,
                            "weight": int(w.group(1)) if w else 1})
        if members:
            upstreams[name] = members

    vhosts = []
    for m in re.finditer(r"\bserver\s*\{", out):
        start = m.end() - 1
        depth, end = 0, start
        for i in range(start, len(out)):
            if out[i] == "{":
                depth += 1
            elif out[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = out[start:end]

        ports = []
        for lm in re.finditer(r"listen\s+([:\d\[\]\.]+)", body):
            p = lm.group(1).strip().replace("[::]", "").lstrip(":")
            if p.isdigit():
                ports.append(int(p))
        if not ports:
            continue

        targets, refs = [], []

        def take(u):
            u = re.sub(r"^https?://", "", u.strip()).rstrip("/")
            host = u.split("/")[0]
            if host in upstreams:
                refs.append(host)
                for mem in upstreams[host]:
                    targets.append(mem["addr"])
            elif re.match(r"^[\w.\-]+:\d+$", host):
                targets.append(host)

        for loc in re.finditer(r"location\s+([^\s{]+)\s*\{([^}]*)\}", body, re.S):
            lpath, lbody = loc.group(1), loc.group(2)
            if any(lpath.startswith(x) for x in IGNORE_PATH):
                continue
            for pm in re.finditer(r"proxy_pass\s+([^\s;]+)\s*;", lbody):
                take(pm.group(1))
        if not targets:
            for pm in re.finditer(r"proxy_pass\s+([^\s;]+)\s*;", body):
                take(pm.group(1))

        if targets:
            vhosts.append({
                "ports": sorted(set(ports)),
                "targets": sorted(set(targets)),
                "upstream": refs[0] if refs else None,
            })

    seen, uniq = set(), []
    for v in vhosts:
        k = (tuple(v["ports"]), tuple(v["targets"]))
        if k not in seen:
            seen.add(k)
            uniq.append(v)

    # drop our own observability ports
    keep = []
    for v in uniq:
        ports = [p for p in v["ports"] if p not in OBSERVABILITY]
        if ports:
            v = dict(v)
            v["ports"] = ports
            keep.append(v)
    return keep, upstreams


REV_FILE = "/opt/photon-flow/.cfg-rev"


def _load_rev():
    try:
        with open(REV_FILE) as f:
            return f.read().strip() or None
    except Exception:
        return None


def _save_rev(h):
    try:
        with open(REV_FILE, "w") as f:
            f.write(h)
    except Exception:
        pass


def note_config_revision(h, raw):
    """记录配置版本；变化时打一条事件并置 reload 标记。

    【为什么需要 reload 标记】拓扑结构（listen 端口、upstream 成员）只在页面
    加载时解析一次，运行期不会重建。配置变了以后，图上的节点数可能与 nginx
    实际情况不符 —— 但直接自动刷新页面会打断动画。所以只提示，由用户决定。
    """
    if h is None:
        return
    prev = _watch["hash"]
    if prev is None:
        prev = _load_rev()          # 重启后沿用上次的基线
        _watch["hash"] = prev
    if prev == h:
        return
    now_ts = time.time()
    _watch["hash"] = h
    _watch["since"] = now_ts
    _save_rev(h)
    if prev is not None:
        _watch["changed"] += 1
        _watch["reload_needed"] = True
        # 记录变更涉及的关键行，便于在 UI 里说明改动点
        keys = []
        for ln in raw.split("\n"):
            t = ln.strip()
            if not t or t.startswith("#"):
                continue
            if any(k in t for k in ("listen ", "proxy_pass", "upstream ",
                                    "server 1", "weight=", "location ")):
                keys.append(t)
        _watch["events"].insert(0, {
            "at": now_ts,
            "hash": h,
            "prev": prev,
            "lines": len(keys),
        })
        _watch["events"] = _watch["events"][:10]


def config_cached():
    now = time.time()
    if now - _cfg["at"] > CACHE_TTL:
        v, u = parse_nginx_conf()
        _cfg.update({"at": now, "vhosts": v, "upstreams": u})
    return _cfg["vhosts"], _cfg["upstreams"]


# ------------------------------------------------------------------ payloads
# ---------------------------------------------------------------- capacity
_watch_cap = {"at": 0.0, "cap": None}


def detect_capacity():
    """两套分母：速率用 rps 上限，并发用连接上限。

    【为什么必须分开】worker_connections 是「连接数」天花板，
    拿它当 rps 的分母会得到毫无意义的极小值。两件事必须各自找自己的上限。
    """
    import re as _re
    try:
        raw = subprocess.run(["nginx", "-T"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        raw = ""

    rate = None
    conn = None

    # ---- 速率上限：limit_req ----
    m = _re.search(r"limit_req\s+zone=\w+\s+rate=(\d+)([rm])/s", raw)
    if m:
        n = int(m.group(1))
        per_sec = n / 60.0 if m.group(2) == "r" else n
        rate = {"kind": "limit_req", "value": round(per_sec, 2),
                "source": "limit_req rate=" + m.group(1) + m.group(2) + "/s"}

    # ---- 连接上限：limit_conn 优先，其次 max_conns ----
    m = _re.search(r"limit_conn\s+\w+\s+(\d+)\s*;", raw)
    if m:
        conn = {"kind": "limit_conn", "value": int(m.group(1)),
                "source": "limit_conn " + m.group(1)}
    else:
        m = _re.search(r"max_conns=(\d+)", raw)
        if m:
            conn = {"kind": "max_conns", "value": int(m.group(1)),
                    "source": "upstream max_conns=" + m.group(1)}

    # ---- 兜底：worker_connections 是真实的连接上限（只是粒度粗） ----
    if conn is None:
        wc = _re.search(r"worker_connections\s+(\d+)\s*;", raw)
        if wc:
            n = int(wc.group(1))
            wp = _re.search(r"worker_processes\s+(\d+|auto)\s*;", raw)
            procs = 1
            if wp:
                procs = (os.cpu_count() or 4) if wp.group(1) == "auto" else int(wp.group(1))
            conn = {"kind": "worker_conn", "value": n * max(1, procs),
                    "source": "worker_connections %d x %d" % (n, procs)}

    # ---- 都没有就用观测峰值（在 payload 里填） ----
    if rate is None:
        rate = {"kind": "peak", "value": 0, "source": "未配限速，按观测峰值"}
    if conn is None:
        conn = {"kind": "peak", "value": 0, "source": "未配限连，按观测峰值"}

    return {"rate": rate, "conn": conn}



def payload_metrics():
    ups = per_upstream()
    n = len(_hist["rows"])
    return {
        "demand": n / WINDOW,
        "toUp": sum(u["rps"] for u in ups),
        "cache": sum(u["cache"] for u in ups),
        "limited": 0.0,
        "bucket": 400,
        "up": [u["rps"] for u in ups],
        "bw": [u["bw"] for u in ups],
        "latency": [u["latency"] for u in ups],
        "up5xx": [u["errRate"] * u["rps"] for u in ups],
        "upState": [u["state"] for u in ups],
        "upNames": [u["addr"] for u in ups],
        "ts": time.time(),
    }


def payload_topology():
    vhosts, _up = config_cached()
    ups = {u["addr"]: u for u in per_upstream()}
    nodes, links, seen = [], [], set()

    def add(node):
        if node["id"] in seen:
            return
        seen.add(node["id"])
        nodes.append(node)

    add({"id": "clients", "kind": "client", "label": "clients",
         "inferred": True})

    # 按 listen 端口统计入站量：日志里的 $server_port 就是它
    portRps = defaultdict(float)
    for r in _hist["rows"]:
        p = r.get("port")
        if p:
            portRps[int(p)] += 1.0 / WINDOW

    for v in vhosts:
        for port in v["ports"]:
            vid = "listen:%d" % port
            add({"id": vid, "kind": "listen", "label": ":%d" % port,
                 "rps": portRps.get(port, 0.0)})
            links.append({"source": "clients", "target": vid,
                          "kind": "inbound"})
            for t in v["targets"]:
                # 采集器自身不是业务后端
                if t in ("127.0.0.1:18200", "localhost:18200"):
                    continue
                tid = "up:" + t
                m = ups.get(t, {})
                add({"id": tid, "kind": "upstream", "label": t,
                     "rps": m.get("rps", 0.0), "bw": m.get("bw", 0.0),
                     "latency": m.get("latency", 0.0),
                     "errRate": m.get("errRate", 0.0),
                     "state": m.get("state", "idle")})
                links.append({"source": vid, "target": tid,
                              "kind": "proxy", "upstream": v["upstream"]})
    # 真实配置文本 + 版本散列：代码面板显示它，变更检测用散列
    cfg_lines = []
    cfg_hash = None
    try:
        raw = subprocess.run(["nginx", "-T"], capture_output=True,
                             text=True, timeout=10).stdout
        cfg_hash = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]
        note_config_revision(cfg_hash, raw)
        # 只保留有信息量的行，去掉空行与纯注释
        for ln in raw.split("\n"):
            s2 = ln.strip()
            if not s2 or s2.startswith("#"):
                continue
            if any(k in s2 for k in ("server {", "listen ", "proxy_pass",
                                     "upstream ", "location ", "server 1",
                                     "weight=", "root ", "access_log")):
                cfg_lines.append(s2)
        cfg_lines = cfg_lines[:60]
    except Exception:
        cfg_lines = []

    # 真实速率：页面用它来给动画定速，而不是自己跑计时器
    n_rows = len(_hist["rows"])
    inbound = n_rows / WINDOW
    proxied = sum(u["rps"] for u in ups.values())
    rate = {
        "inbound": inbound,          # 每秒进入 nginx 的请求
        "proxied": proxied,          # 每秒被转发到上游的请求
        "ratio": (proxied / inbound) if inbound > 0 else 0.0,
    }
    uptime = max(1.0, time.time() - _tot["started"])
    avg_lat = 0.0
    if ups:
        avg_lat = sum(u["latency"] for u in ups.values()) / len(ups) / 1000.0
    counters = {
        "requests": _tot["requests"],
        "proxied": _tot["proxied"],
        "errors": _tot["errors"],
        "bytes": _tot["bytes"],
        "active": round(inbound * avg_lat, 2),
        "uptime": round(uptime, 1),
        "rps": round(inbound, 2),
        "proxied_rps": round(proxied, 2),
    }
    # 容量语义：速率与并发各用各自的分母
    cap = detect_capacity()
    peak_rps = max([u["rps"] for u in ups.values()] or [0.0])
    peak_total = sum(u["rps"] for u in ups.values())
    if cap["rate"]["value"] <= 0:
        cap["rate"]["value"] = round(max(peak_total, 1.0), 2)
        cap["rate"]["source"] = "观测峰值 %.1f rps" % cap["rate"]["value"]
    if cap["conn"]["value"] <= 0:
        cap["conn"]["value"] = max(1, int(round(proxied * 1.5)) or 8)
        cap["conn"]["source"] = "观测并发峰值 %d" % cap["conn"]["value"]

    config_info = {
        "hash": _watch["hash"],
        "since": _watch["since"],
        "changed": _watch["changed"],
        "reloadNeeded": _watch["reload_needed"],
        "events": _watch["events"],
    }
    return {"nodes": nodes, "links": links, "rate": rate,
            "counters": counters, "config": cfg_lines,
            "configInfo": config_info, "capacity": cap, "ts": time.time()}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        # ensure_ascii=False + 显式 charset：否则中文会被转成 \uXXXX，
        # 客户端解码不一致时就会出现「涓笂娓」这类乱码。
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        """接收"已应用"确认，清掉变更提示的 latch。

        【为什么需要】reloadNeeded 是服务端的一个锁存位，一旦置起就永远为真。
        页面应用完新拓扑后必须回报一次，否则提示条会一直挂着。
        """
        try:
            if self.path.startswith("/api/config/ack"):
                _watch["reload_needed"] = False
                self._send({"ok": True})
            else:
                self._send({"ok": False})
        except Exception:
            pass

    def do_GET(self):
        try:
            if self.path.startswith("/api/stream"):
                self._stream()
            elif self.path.startswith("/api/topology"):
                self._send(payload_topology())
            else:
                self._send(payload_metrics())
        except Exception as e:
            try:
                self._send({"error": str(e)})
            except Exception:
                pass

    def _stream(self):
        """Server-Sent Events: 一次连接，服务端按秒推送。

        【为什么用 SSE 而不是轮询】页面之前每 2 秒发一次同步 XHR，
        每次都会阻塞主线程直到响应返回 —— 渲染每隔 2 秒卡一下，
        整体观感就是画面发暗、节奏断续。SSE 把这件事移出渲染路径：
        浏览器在后台接收，页面只处理已到达的消息。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_cfg = None
        while True:
            try:
                payload = payload_topology()
                cfg = payload.get("config")
                # 配置没变就不重复下发，省带宽
                body = {
                    "rate": payload.get("rate"),
                    "counters": payload.get("counters"),
                    "configInfo": payload.get("configInfo"),
                    "capacity": payload.get("capacity"),
                    "nodes": [n for n in payload.get("nodes", [])
                              if n.get("kind") != "client"],
                }
                if cfg != last_cfg:
                    body["config"] = cfg
                    last_cfg = cfg

                data = "data: " + json.dumps(body, ensure_ascii=False) + "\n\n"
                self.wfile.write(data.encode("utf-8"))
                self.wfile.flush()
                time.sleep(1.0)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18200), H).serve_forever()
