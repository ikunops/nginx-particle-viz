# nginx-particle-viz

把 nginx 的实时运行状态可视化成一幅「光子流」：左侧是各个入口（listen 端口）的请求，
汇入中央网关，处理后分发到右侧各台上游后端。所有数字来自真实日志，没有一个随机数。

```
┌──────────────┐        ┌─────────┐        ┌──────────────┐
│ :80   入口   │───────▶│         │───────▶│ 127.0.0.1:8088│
│ :9000 入口   │        │  nginx  │        │ 127.0.0.1:8778│
│ :18080 入口  │◀───────│  网关   │◀───────│ 127.0.0.1:18081│
└──────────────┘        └─────────┘        └──────────────┘
     客户端入口            吸积/转发              上游后端
```

## 它显示什么

**左侧卡片**（每个 listen 端口一张）

| 字段 | 含义 | 数据来源 |
|---|---|---|
| 请求 | 该入口 rps ÷ 速率上限 | 日志 `$server_port` 聚合 |
| 并发 | 该入口承担的上游数 ÷ 连接上限 | `nginx -T` 的 proxy_pass 关系 |
| 均值 | 最近 30 个采样的滑动平均 | 上述请求值的滑动窗口 |
| `:18080` | 端口 / 该端口下有几个上游 | `nginx -T` |
| BUSY / IDLE | 该入口是否正在承担流量 | 实时 rps |

**右侧卡片**（每台上游一张）：真实 IP、实测 rps、实测延迟、状态。
**悬停**任意卡片会显示负载条所用的分母来源。

**顶部两个阶段**

| 阶段 | nginx 含义 | 时长 |
|---|---|---|
| 01 吸积 INGEST | 请求进入 nginx，写入 access.log | 3–16 秒，由入站速率决定 |
| 02 转发 COLLAPSE | 匹配 location 后 proxy_pass 到上游 | 1.2–6 秒，由转发速率决定 |

速率越高，阶段越短 —— 流量大的时候动画跑得快，没流量时会慢下来。

## 数据从哪来

全部只读，不改动任何业务配置：

| 数据 | 采集方式 | 频率 |
|---|---|---|
| 每台上游的 rps / 带宽 / 延迟 / 错误率 | `/var/log/nginx/*.log` 按 `$upstream_addr` 聚合 | 1 秒 |
| listen 端口 → 上游的对应关系 | 解析 `nginx -T` 的 `server{}` / `location{}` / `upstream{}` | 5 秒（带缓存） |
| 累计请求 / 转发 / 错误数 | 日志计数 | 实时 |
| 容量上限（负载条的分母） | 见下 | 5 秒 |

**日志格式**需要新增一个 `log_format`（不影响原有格式）：

```nginx
log_format photon_metrics
  '$time_iso8601|$server_port|$remote_addr|$request|$status|$body_bytes_sent|'
  '$request_time|$upstream_addr|$upstream_status|$upstream_response_time|'
  '$upstream_cache_status|$http_user_agent';

access_log /var/log/nginx/photon-flow.access.log photon_metrics;
```

没有 `$upstream_addr` 就无法拆分「每个后端各自的指标」，只能看到全局总量。

## 负载条的分母（两种情况自适应）

「负载到 500/1000 就显示一半」需要一个容量上限，但 nginx 只有在你配置了才有。
采集器按优先级探测，探测到哪层就用哪层，并在界面上标注，不会假装有一个不存在的上限：

| 优先级 | 配置 | 速率条分母 | 并发条分母 |
|---|---|---|---|
| 1 | `limit_req zone=... rate=Nr/s` | N（换算成每秒） | — |
| 2 | `limit_conn zone N` | — | N |
| 3 | `upstream { server x max_conns=N; }` | — | N |
| 4 | `worker_connections N` × 进程数 | — | N × 进程数 |
| 5 | 什么都没配 | 观测峰值 rps | 观测峰值并发 |

本仓库附带的环境没有配置任何限流，所以会走第 5 层和第 4 层：

```json
{"rate": {"kind": "peak", "value": 85.0,  "source": "观测峰值 85.0 rps"},
 "conn": {"kind": "worker_conn", "value": 4096, "source": "worker_connections 1024 x 4"}}
```

## 配置热更新

nginx 配置改动后**不需要刷新页面**：

1. 采集器对 `nginx -T` 全文算 SHA1，发现变化就置 `reloadNeeded`
2. 页面顶部出现提示条「nginx 配置已变更 · 下一轮生效」
3. **等当前这一轮动画跑完**（不是立刻），在循环边界重建拓扑
4. 旧的光点继续沿旧曲线飞完，新的光点用新曲线
5. 提示条自动消失

为什么不立刻重建：半途重建会让环、能量、黑洞尺寸瞬间跳到新状态，视觉上就是「啪」地一下。
为什么不自动刷新页面：会打断正在查看的视角。

## 运行

### 前置

- Linux + nginx 1.20+
- Python 3.9+（采集器只用标准库，无第三方依赖）
- 现代浏览器（Canvas 2D，不需要 WebGL）

### 部署

```bash
# 1. 放到 /opt
sudo mkdir -p /opt/photon-flow/{out,archive}
sudo cp release/nginx-flow.html   /opt/photon-flow/out/
sudo cp release/metrics_server.py /opt/photon-flow/
sudo cp release/traffic_gen.py    /opt/photon-flow/     # 仅演示

# 2. 加日志格式（追加到 nginx.conf 的 http{} 块）
log_format photon_metrics '$time_iso8601|$server_port|$remote_addr|$request|$status|$body_bytes_sent|$request_time|$upstream_addr|$upstream_status|$upstream_response_time|$upstream_cache_status|$http_user_agent';

# 3. 加站点（改端口和 upstream 为你自己的）
sudo cp release/nginx-site.conf /etc/nginx/conf.d/photon-flow.conf
sudo nginx -t && sudo systemctl restart nginx

# 4. 采集器常驻
sudo cp release/photon-metrics.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now photon-metrics
```

打开 `http://<你的IP>:18100/`。

> **注意**：`nginx -s reload` 有时不会重新打开新的日志文件，必须
> `systemctl restart nginx`。这个坑排查起来很费时间：reload 后配置生效、
> 页面正常返回 200，但 access_log 一直不写入。

### 配置项

| 文件 | 变量 | 说明 |
|---|---|---|
| `metrics_server.py` | `PHOTON_LOG`（环境变量） | 兜底日志路径。正常情况下**不需要设**：路径从 `nginx -T` 自动发现 |
| | `WINDOW` | 聚合窗口（秒），默认 6 |
| | `CACHE_TTL` | `nginx -T` 解析缓存（秒），默认 5 |
| | `OBSERVABILITY` | 不作为业务流量统计的端口（观测端口自身） |
| `traffic_gen.py` | `URL` / `RPS` | 压测目标与速率，**仅演示用，生产环境请删掉** |

## 架构

```
nginx 日志 ──┐
             ├──▶ metrics_server.py ──▶ /api/topology    一次性快照
nginx -T  ───┘         │              └─▶ /api/stream      SSE 每秒推送
                       │              └─▶ /api/config/ack  应用确认
                       ▼
              nginx-flow.html
              ├─ 左栏：客户端入口（数组驱动）
              ├─ 中央：吸积 / 转发 两阶段
              ├─ 右栏：上游卡片（数组驱动）
              ├─ 04 响应记录：每轮结束时记一条
              ├─ 05 事件流 / 06 连接负载
              ├─ 07 实时配置：真实 nginx.conf 逐字符打印
              └─ 08 网关遥测：实测累计
```

**两侧都是数组驱动**：新增一个 `server{}` 或一台 upstream，下一轮就会多出一张卡，
不需要改任何代码。

## 兼容性

- **Python 3.6+**。CentOS 7 / RHEL 7 自带 3.6.8，旧版本用了 `ThreadingHTTPServer`
  和 `subprocess.run(capture_output=)`（都是 3.7+），在 3.6 上直接 ImportError。
  现已改为兼容垫片，3.7+ 仍走原生实现。
- **日志路径自动发现**。不再依赖 `LOG` 常量：解析 `nginx -T` 里所有
  `access_log` 指令，优先选带 `$upstream_addr` 的那个文件。同时存在多种格式
  时只读管道格式，避免同一请求被重复计数。
- **静态站点 / 重定向站点不再被丢弃**。旧版只把 `proxy_pass` 当流量目标，
  导致 `root` 和 `return 301` 的 vhost 完全不进图——在标准安装里这可能是
  大部分流量。现在 vhost 带 `kind`（`proxy` / `static` / `redirect` / `other`）
  和真实 `target`。

## 已知限制

- **客户端分组是推断的**。nginx 看不到真实调用方，所以左栏的「一组」=
  一个 listen 端口。想要真实客户端分组，需要接入别的数据源。
- **配置变更后拓扑要等下一轮才更新**，最长约 16 秒（低流量时阶段会被拉长）。
- **SSE 长连接**会让浏览器的「加载中」指示器一直转。这是 SSE 的固有行为，
  页面功能不受影响。
- **浏览器缓存**：页面已在 nginx 侧加了 `Cache-Control: no-store`，
  但如果你反代别的服务器，记得也加。

## 视觉设计上的硬约束

这些是踩过坑之后定下来的，不是随便选的：

- **线宽不编码任何指标**，光段宽度也不。带宽只以数字形式出现在侧栏。
- **延迟不驱动路径弯曲**，弯曲只由几何决定。
- **线数固定**，与通道数、流量都无关。
- **亮度只编码占比**，且故障必须更亮而不是更暗。
- **循环交界处不能硬跳**：`collapse` 结束时 ring=1、energy=1.2，
  `ingest` 开头用 35% 的时间把这几个值平滑衰减回基线，而不是直接归零。

## 目录

```
.
├── release/
│   ├── nginx-flow.html          单文件前端（含全部样式与逻辑）
│   ├── metrics_server.py        采集器（Python 3 标准库）
│   ├── traffic_gen.py           演示用流量生成（生产请删）
│   ├── nginx-site.conf          站点配置示例
│   └── photon-metrics.service   systemd 单元
├── docs/                        设计文档与截图
└── tools/                       开发期的分析验证脚本
```

## License

MIT
