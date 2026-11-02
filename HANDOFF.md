# NGINX 光子流可视化 · 交接文档

> 用途：新会话开工前通读这一份。它代替不了你的判断，但能省掉前 100 轮的错误。
> 上一轮会话的问题不是做得少，而是**在没有曲线/没有参考文件的情况下反复调参数**。

---

## 一、要做的东西

一张 **nginx 请求流转的实时动画图**（网页，单文件 HTML）。

左侧 4 个客户端分组，中间一个 nginx 边缘节点，右侧 4 个上游服务。
请求从左流进 nginx，在圆盘里绕行，再分发到右侧上游；响应反向流回。

**技术约束**：必须能接真实数据（WebSocket / fetch 推指标），不能是预渲染位图。

---

## 二、必须参考的资产（这三个比任何口头描述都重要）

### 1. 视觉目标 —— 旧预渲染版

```
C:\Users\31807\Documents\deepseek-harness\default-workspace\nginx-particle-viz\out\photon-flow-python.html
```

**这是唯一被认可"好看"的版本。** 7MB，36 张预渲染帧。它不能接数据，但**视觉是基准**。

它的渲染器在：
```
C:\Users\31807\Documents\deepseek-harness\default-workspace\nginx-particle-viz\scene3.py
```

### 2. 线条与光段的实现

```
C:\Users\31807\opencode-dotfiles\skills\photon-flow-viz\scripts\fibre.py
```

**关键函数 `route()`**。它的参数就是那个好看效果的来源：

```python
def route(buf, s, P, col, phase, rng, nfib=10, spread=26.0, fibw=1.0,
          fib_amp=0.30, wob=3.0, freq=1.4, grow=1.4, steps=900,
          beads=0, bead_amp=3.0, bead_len=0.09, bead_r=1.6,
          packets=0, packet_w=0.05, back=False, taper=0.10, env=None,
          pulse=0, pulse_len=0.075, pulse_amp=6.0, pulse_w=1.0)
```

各参数含义：
| 参数 | 作用 |
|---|---|
| `nfib` | 平行纤维股数（5–18） |
| `spread` | 纤维分布带宽 |
| `fib_amp` | 纤维本身亮度 |
| `wob` / `freq` | 每股纤维的正弦扰动，**这是"纤维"而非"曲线"的关键** |
| `pulse` / `pulse_len` / `pulse_amp` | 沿线移动的亮段数量 / 长度 / 亮度 |
| `taper` | 两端淡出，无硬边 |
| `env` | 宽度包络：`tight`=两端收中间散，`flat`=恒定，`open`=展开后收 |

### 3. 实际调用参数（直接抄这些）

从 `scene3.py` 里摘出来的真实用法：

```python
# 客户端线（左侧）
F.route(buf, s, p_group(gi), col, phase, rng,
        nfib=max(2, round(3 + 5*share*5)),   # 3–8 股
        spread=11.0, fib_amp=0.30,
        pulse=max(2, min(5, round(2 + 6*share))),
        wob=1.6, freq=1.25, taper=0.11, env="tight")

# 上游线（右侧）
F.route(buf, s, p_up(i), col, phase, rng,
        nfib=max(3, round(16*wgt*1.6)),      # 3–13 股
        spread=26.0*(0.45+wgt), fib_amp=0.32,
        pulse=max(2, min(6, round(2 + 8*wgt))),
        wob=2.8, freq=1.35, taper=0.11, env="open")
```

---

## 三、⚠️ 最大的坑：色调映射曲线

**这是上一轮花了几十次都没找出的根因。**

旧版把光累积到浮点缓冲区，最后套一条曲线：

```python
def tonemap(light, gain=1.95, bg=None):
    L = 1.0 - np.exp(-np.clip(light * gain, 0, 40))
    return (np.clip(bg + L * (1 - bg), 0, 1) * 255).astype(np.uint8)
```

这条曲线**大幅抬升中间调**：

| 输入 | 输出 | 对应 8-bit |
|---|---|---|
| 0.10 | 0.18 | 47 |
| **0.30** | **0.44** | **113** |
| 0.52 | 0.64 | 164 |
| 1.00 | 0.86 | 219 |
| 3.00 | 1.00 | 255 |

**所以 `fib_amp=0.30` 在旧版屏幕上显示为 113/255，清晰可见。**

如果在 Canvas 2D 里直接 `ctx.strokeStyle = rgba(..., 0.30)`，得到的是 76/255，再被 bloom 合成除权后基本消失。

**结论：所有来自 fibre.py / scene3.py 的亮度数值都是"曲线前"的。Canvas 里必须逐通道套用 `1 - exp(-x*1.95)` 才能还原。**

工作代码（已经验证有效）：

```js
var TONE_GAIN = 1.95;
function tone(x) {
  return 1 - Math.exp(-Math.max(0, Math.min(40, x * TONE_GAIN)));
}
function toneRGBA(col, amp) {
  return "rgba(" +
    Math.round(tone(amp * col[0] / 255) * 255) + "," +
    Math.round(tone(amp * col[1] / 255) * 255) + "," +
    Math.round(tone(amp * col[2] / 255) * 255) + ",1)";
}
```

Bloom 也照抄：

```python
F.bloom(buf, s, scales=(2.0, 6.5, 20.0), weights=(0.52, 0.26, 0.15))
F.tonemap(light, gain=1.95, bg=base_bg(W, H))
```

---

## 四、星云（圆盘）的要求

圆盘不是装饰，是主体之一。要求：

1. **铺满整个盘面**，任何区域都不能是空的
2. **螺旋密度波**，不是同心圆环。用 3 条不同螺距的对数螺旋叠加，密度下限 0.35 左右
   - 参考实现：`scripts/galaxy.py` 的 `fbm` / `colour_field`
   - 或 `scripts/preview_galaxy.py`
3. **螺旋必须是拖尾（trailing）** —— 盘逆时针转，则臂角随半径**减小**
   - 数学：`phi = theta + pitch * 2π * ln(r/r0)`，注意是 `+`（配合逆时针转向）
   - 判断：`d(theta)/d(ln r) < 0`
   - 上一轮写反过，用户一眼看出"螺纹不对"
4. **两级亮度**：
   - 基础亮度：暗，铺满
   - 流动光带：一段明亮区域绕盘旋转，粒子被扫到时亮起、扫过后回落
5. **颜色按半径**：暖白核心 → 金 → 玫瑰 → 蓝 → 深蓝（不是随机色相）
6. **不要画圆环描边** —— 任何 `ctx.arc` / `ctx.ellipse` 描边都会让用户说"星云外面有个圈"
7. **不要画可见的螺旋线** —— 用户明确说过"怎么跟乱画一样"，参考星云图里一根线都没有，全是粒子密度

---

## 五、连接方式（用户反复强调）

- 客户端线束要**顺畅接入**星云，不能像"插了根管子"
- 做法：线进入圆盘后**渐变到透明**，在星云已经够亮的地方溶解
  - 溶解起点约 `0.72R`，不是边缘
- 出口同理，从 `0.55R` 开始沿半径向外
- 入口不要全挤在一点：4 条客户端线在左侧弧上**分散进入**（约 1.5 rad 跨度）
- 上一轮的错误：入口只差 0.52 rad → 四条线打结

---

## 六、已验证的技术细节

### 路径插值
用 **centripetal Catmull-Rom**（Barry-Goldman），必须用**正确分母**：

```js
var A1x = ((t1 - t) * p0[0] + (t - t0) * p1[0]) / (t1 - t0);
var A2x = ((t2 - t) * p2[0] + (t - t1) * p3[0]) / (t2 - t1);   // ← 注意是 t2-t1
var B1x = ((t2 - t) * A1x + (t - t0) * A2x) / (t2 - t0);
```

分母写错会让曲线在控制点间距不均时炸开（上一轮曲率比 8556，正确是 1.07）。

参数化用 `sqrt(dist)`（centripetal, alpha=0.5），不要用 uniform。

### 弧长重采样
插值后必须按**弧长**均匀重采样，否则粒子在曲线节点处会堆积：

```js
function resample(path, count) {
  // 累积弧长 → 等距取点
}
```
验证指标：段长比 max/mean 应接近 **1.00–1.05**。

### 性能
Canvas 2D 实测：
- 每帧创建渐变 → **12,600 个/帧 → 卡死**。必须缓存 sprite 或按需创建
- 粒子数 14,000 + 5 bloom pass → 单帧 58ms（60fps 需要 16.7ms）
- **光缓冲用半分辨率**（`w >> 1`），四分之一会丢细节
- 用 `?t=秒数` 冻结时间，方便截图对比

### 全局状态 bug（踩过）
```js
// 星星循环里设置了 globalAlpha
lctx.globalAlpha = perMoteAlpha;
// 然后画线时
lctx.save();   // ← save 会保留 globalAlpha！
// 结果：整层线的不透明度由"最后一个星星的亮度"决定 → 呼吸感
```
**画每一层前显式 `globalAlpha = 1`。**

---

## 七、用户明确否定过的做法

| 做法 | 用户原话 |
|---|---|
| 等距等亮的圆点 | "跟个装满了灯珠的灯带一样 就那种廉价的那种" |
| 星云只覆盖部分圆盘 | "怎么剩四分之一 什么也没有" |
| 星云外圈有描边 | "为什么中间的星云外面有一个圆圈" |
| 线接入像插管子 | "很突兀的插个管子一样" |
| 7 股粗白线束 | "你自己觉得好看吗" |
| 全白线条 | 颜色信息丢失 |
| 中间白色螺旋线 | "这跟我乱画的有啥区别啊" |
| 呼吸灯效果 | "怎么搞的跟呼吸灯一样啊" |

---

## 八、未完成 / 待验证

1. **布局**：`photon-flow-v2.html` 里星云和卡片位置可能需要按实际窗口微调
2. **性能**：移植 route() 后每帧大约 15 条路径 × 5–18 股 = 100+ 次 stroke，未实测帧率
3. **反方向（响应）**：目前有路径但视觉上没和请求区分开
4. **特殊通道**：cache 命中、429 限流、deny 拒绝三条路径还没画
5. **配置驱动**：`CONF` 已支持增删客户端/上游自动重排，但未测试 6 个上游的情况

---

## 九、可以直接用的起点

```
C:\Users\31807\Documents\deepseek-harness\default-workspace\nginx-particle-viz\out\photon-flow-v2.html
```

最新状态：已移植 tone 曲线 + drawRoute()，线条多股、有 wob、有流动光段。
覆盖率 28.2%，但**星云和布局是这轮没顾上的部分**。

---

## 十、给新会话的建议

1. **先打开那两个参考文件**（旧版 HTML + fibre.py），不要凭描述做
2. **先做静态一帧**，确认线和星云的观感对了，再谈动画
3. **亮度一定走 tone 曲线**，不要直接调 alpha
4. **每改一轮截图给用户看**，不要自己判断"改好了"——上一轮 100 多轮里，我自己认为改好的一次都没对
5. 用户的判据是**眼睛**，不是数值。数值用来定位问题，不用来宣告成功
