# NGINX Photon Flow — 重做规格

> 这份文档给新接手的人。**完全重做**，可以借鉴映射表，不要继承旧文件的代码结构。
> 旧文件 `out/photon-flow-v2.html` 改了 20+ 轮，已有结构性混乱，不要在其上继续打补丁。

---

## 一、任务

一张 **nginx 请求流转的实时可视化页面**。单文件 HTML，纯前端。

```
左侧 4 个客户端  →  中间 nginx 边缘节点  →  右侧 4 个上游服务
```

请求从左流入，在中间节点绕行，分发到右侧；响应反向流回。

**必须能接真实数据**，不是演示动画。

---

## 二、必须先看的参考资料

### 本地已部署（可直接打开）

| 地址 | 是什么 |
|---|---|
| `http://127.0.0.1:8899/_refs/haloflux/lab.html` | 光环 + 光束层叠，**纯 Canvas 2D** |
| `http://127.0.0.1:8899/_refs/agent-display/index.html#ops` | OPS 调度中心，**纯 Canvas 2D** |
| `http://127.0.0.1:8899/_refs/agent-display/index.html#forge` | FORGE 视觉熔炉，**WebGL + Canvas 混合** |

> 服务可能需要重启：
> ```powershell
> cd C:\Users\31807\Documents\deepseek-harness\default-workspace
> python -m http.server 8899 --bind 127.0.0.1
> ```

### 源码

```
_refs/haloflux/lab.html                     93 KB   单文件 Canvas 2D
_refs/agent-display/index.html             932 KB   8 主题，Shadow DOM 隔离
```

**重点看 OPS 主题的这几个函数**（`grep` 得到）：

| 函数 | 作用 |
|---|---|
| `buildStreaks()` | 建光束：每条线自带 `d:{p,len,v}` 光段表 |
| `buildThreads()` | 建左侧节点连线，`quadraticCurveTo` + 随机控制点 |
| `drawWheelStreaks()` | 画光束：**4 个 Path2D 分档 + 一次 stroke** |
| `drawPulses()` | 画流动脉冲：`bez()` 采样 7 点，Path2D 批量 |
| `newPulse()` | 脉冲对象 `{q, u, v}` |

**haloflux 重点看** `makeStrandLayer()` / `drawStrands()`：

- 每段有独立 `pf[k]`/`pp[k]`（频率/相位），整束轻微呼吸
- 按边缘衰减分 3 个 `Path2D` 档位
- 拖尾用 dash 段数组，**不创建渐变对象**

---

## 三、必须实现的视觉规则

### 1. 线的三态

| 状态 | 条件 | 视觉 |
|---|---|---|
| **base** | 无流量 | 细线 **0.6px**，暗淡但**可见** |
| **active** | 有流量 | 线宽 0.6→2.0，变亮，多股 |
| **head** | 有流量 | 短光段沿线移动 |

**基础线必须可见**，不是等有流量才出现。

### 2. 光段属于「线」，不属于「股」

这是最容易错的地方。一条通道有 3–12 股，**但光段只有 1–2 个**，沿路径中心线走。

按股生成会变成一条线上几十个并排的短划 → 用户原话：「怎么一根线上有那么多的光段呢」

### 3. 光晕用「同路径画两遍」

```js
// 粗而淡
ctx.strokeStyle = color; ctx.globalAlpha = 0.1;  ctx.lineWidth = 4.5; ctx.stroke(path);
// 细而亮
ctx.globalAlpha = 0.6; ctx.lineWidth = 0.9; ctx.stroke(path);
```

**不要用 `shadowBlur`**（极慢），**不要指望 bloom 后处理**做光晕。

### 4. 线要「整束一起弯」

弯曲是整条通道的形变，**不是每股各走各的**。每股用独立相位会把线束拆散成乱麻。

### 5. 入口必须对齐客户端的行位置

**踩过的坑**：符号写反，顶部客户端连接到圆盘底部，线横穿整个画面。

正确做法：入口点应位于圆盘左侧、**与该客户端的 y 坐标接近**的高度，让线接近水平接入。

### 6. 不要画圆盘描边

任何 `ctx.arc` / `ctx.ellipse` 描边都会让用户说「星云外面有个圆圈」。边界靠粒子密度自然衰减。

### 7. 星云的螺旋必须是「拖尾」

盘逆时针转，则臂角随半径**减小**：

```js
// phi 用加号配合逆时针
var phi = th + pitch * 2 * Math.PI * Math.log(r / r0) - phase;
// 判据：d(theta)/d(ln r) < 0
```

写反了用户一眼能看出「螺纹不对」。

### 8. 不要画可见的螺旋线

参考星云图里**一根线都没有**，全是粒子密度。画白线螺旋 = 「跟我乱画的一样」。

---

## 四、指标映射（可借鉴，也可调整）

完整版见 `MAPPING.md`。核心：

| nginx 指标 | 视觉通道 | 公式 | 值域 |
|---|---|---|---|
| 通道 rps 占比 | **股数**（主） | `3 + 9·√share` | 3–12 |
| 通道 rps 占比 | **线宽**（次） | `0.6 + 1.4·√share` | 0.6–2.0 |
| 通道 rps 占比 | 亮度（弱） | `0.15 + 0.10·√share` | 0.15–0.25 |
| **带宽** | **光段增量** | `lineW + 1.0 + 2.0·√(bw/bwRef)` | +1.0–+3.0 |
| **带宽** | **光段长度** | `6 + 26·√(bw/bwRef)` | 6–32 px |
| **延迟** | **光段速度** | `0.30 · min(1, 60/lat)` | 0.055–0.30 |
| 延迟 | 线弯曲（弱） | `clamp(3 + lat·0.04, 3, 12)` | 3–12 |
| **在途请求** | **光段数量** | `k>0.55:2, k>0.15:1, else 0` | 0–2 |
| **5xx 率** | 色相偏移 | `+25° · min(1, er·10)` | +0–25° |
| `fail` | 红色脉冲 | 亮度 **≥0.60** | — |
| `slow` | 降饱和 | 亮度 ≥0.40 | — |

### 六条硬规则

1. **光段永远比基础线粗** —— 用加法 `segW = lineW + ΔW`，不用乘法
2. **一个指标一主一辅** —— 不要四个通道同时编码 `share`
3. **故障要更亮，不是更暗** —— 变暗会被误读为「空闲」
4. **所有公式两端钳位**
5. **自适应分母用 P95 滑窗**，不用 `max()`（一个尖峰会压扁全场）
6. **基础值不为零** —— 空载时仍有 3 股、0.6px 线

### 自适应分母

```js
REF.rps      = P95(每通道 rps, 90 样本, 下限 1)
REF.bw       = max(CONF.bandwidthLimit, P95(bw) × 1.15)
REF.inflight = P95(在途请求, 下限 1)
```

### 在途请求用 Little's Law 算

```js
inflight[i] = up[i] * latency[i] / 1000;   // 不需额外数据源
```

**不要用「并发连接数」** —— 与请求数语义不同，且需要额外数据源。

---

## 五、数据接口

```js
window.FEED = function (m) {
  simActive = false;                      // 一接真实数据永久停用模拟器
  Object.assign(M, m);
};

// 需要的字段
{
  demand, toUp, cache, limited, bucket,     // 全局
  up:      [rps, ...],                     // 每上游请求速率
  bw:      [bytesPerSec, ...],             // 每上游带宽
  latency: [ms, ...],                      // 每上游响应时间
  up5xx:   [count, ...],                   // 每上游 5xx 数
  upState: ["ok"|"slow"|"fail", ...]       // 健康状态
}
```

`inflight` 由代码算出，不需外部提供。

### nginx 侧日志配置（供参考）

```nginx
log_format viz '$upstream_addr $upstream_response_time '
               '$upstream_status $body_bytes_sent $request_time';
access_log /var/log/nginx/access.log viz;
```

**没有 `$upstream_addr` 就无法按上游拆分**，这是硬前提。

---

## 六、用户明确否定过的（附原话）

| 做法 | 原话 |
|---|---|
| 等距等亮圆点 | 「跟个装满了灯珠的灯带一样 就那种廉价的那种」 |
| 星云只覆盖部分圆盘 | 「怎么剩四分之一 什么也没有」 |
| 星云外圈描边 | 「为什么中间的星云外面有一个圆圈」 |
| 线接入像插管子 | 「很突兀的插个管子一样」 |
| 7 股粗白线束 | 「你自己觉得好看吗」 |
| 中间白色螺旋线 | 「这跟我乱画的有啥区别啊」 |
| 呼吸灯效果 | 「怎么搞的跟呼吸灯一样啊」 |
| 一根线上几十个光段 | 「怎么一根线上有那么多的光段呢」 |
| 线歪歪扭扭 | 「这些线的走势怎么歪歪扭扭的呢」 |
| 局部过亮 | 「有部分区域非常亮」 |
| 入口排线感 | 「我们的接入有点像一个排线搭上去了」 |

---

## 七、技术约束

| 项 | 要求 |
|---|---|
| 渲染 | **纯 Canvas 2D**（haloflux 和 OPS 都是，证明够用） |
| 文件 | 单 HTML，无构建，无外部依赖 |
| 屏幕 | 需适配 1280–2560 宽，侧栏在窄屏隐藏 |
| 性能 | 60fps。Canvas 2D 实测：14k 粒子 + 5 级 bloom = 58ms/帧（不达标） |
| 调试 | 加 `?t=秒数` 冻结时间，方便截图对比 |

### 性能要点

- ❌ `shadowBlur`（极慢）
- ❌ 每帧 `createLinearGradient`（实测 12,600 个/帧直接卡死）
- ✓ 按亮度分档 → `Path2D` → 一次 `stroke()`
- ✓ 光段用 dash 段数组，不建渐变对象
- ✓ 光缓冲用半分辨率（`w >> 1`）
- ✓ sprite 全缓存，帧内零分配

### 已踩过的 bug

```js
// 星云循环设置了 globalAlpha，画线时 save() 会保留它！
lctx.globalAlpha = perMoteAlpha;   // 循环里
lctx.save();                        // 这里会继承上面的值
// 结果：整层线的不透明度由「最后一个粒子的亮度」决定 → 呼吸感
```

**每画一层前显式 `globalAlpha = 1`。**

---

## 八、星云要求

1. **铺满整个盘面**，任何区域不能空
2. **螺旋密度波**，3 条不同螺距的对数螺旋叠加，密度下限 ~0.35
   - 参考 `C:\Users\31807\opencode-dotfiles\skills\photon-flow-viz\scripts\galaxy.py`
3. **两级亮度**：
   - 基础：暗，铺满
   - 流动光带：一段明亮区域绕盘旋转，粒子被扫到时亮起、扫过后回落
4. **颜色按半径**：暖白核心 → 金 → 玫瑰 → 蓝 → 深蓝
5. **核心应最亮**，向外衰减

---

## 九、可用的旧资产

| 文件 | 用途 |
|---|---|
| `MAPPING.md` | 完整映射表（已推导，可直接用） |
| `HANDOFF.md` | 更早的交接文档，含 tone 曲线等内容 |
| `out/photon-flow-v2.html` | 旧实现，**只借鉴不继承** |
| `scene3.py` / `fibre.py` | 旧的 Python 渲染器，含 `route()` 参数 |

### fibre.py 的 route() 参数（如果要用）

```python
def route(buf, s, P, col, phase, rng, nfib=10, spread=26.0, fibw=1.0,
          fib_amp=0.30, wob=3.0, freq=1.4, grow=1.4, steps=900,
          beads=0, bead_amp=3.0, bead_len=0.09, bead_r=1.6,
          packets=0, packet_w=0.05, back=False, taper=0.10, env=None,
          pulse=0, pulse_len=0.075, pulse_amp=6.0, pulse_w=1.0)
```

⚠️ **这些亮度值是「色调映射前」的。** 旧的 Python 渲染器最后套了：

```python
L = 1.0 - np.exp(-light * 1.95)
```

所以 `fib_amp=0.30` 在屏幕上显示为 **113/255**。Canvas 里直接画 alpha 0.30 只有 76/255，会暗一半。**如果需要这个亮度，必须逐通道套用该曲线。**

---

## 十、交付要求

1. **先做静态一帧**，确认线、光段、星云的观感，再谈动画
2. **每改一轮截图**，不要自己判断「改好了」
3. 用户的判据是**眼睛**，不是数值。数值用来定位问题，不用来宣告成功
4. 遇到的每个判断，写成注释说明**为什么这样做**，不要只写代码

---

## 十一、输出位置

```
C:\Users\31807\Documents\deepseek-harness\default-workspace\nginx-particle-viz\out\photon-flow-v3.html
```

新建文件，不要覆盖 v2。
