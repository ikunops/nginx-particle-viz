# 架构梳理：从 FORGE 学到什么、我们要改什么

---

## 一、FORGE 为什么不慢（已从源码确认）

**352 条静态曲线不是每帧画的，而是烘焙到离屏 canvas，每帧只贴一次。**

```js
var web = document.createElement("canvas");   // 离屏
var wctx = web.getContext("2d");

function renderWeb() {                        // 只有几何变化时才调用
  for (i = 0; i < curvesIn.length; i++) {
    g = wctx.createLinearGradient(...);       // 每条线一个渐变
    pathTwo(wctx, cv); wctx.stroke();
  }
}
```

调用点只有 4 个：

| 时机 | 代码 |
|---|---|
| 初始化 | `buildCurves(); renderWeb();` |
| 窗口 resize | `if (appR) { buildCurves(); renderWeb(); }` |
| 重置视图 | `resetView() { ...; buildCurves(); renderWeb(); }` |
| 缩放停止 60ms 后 | `zoomTimer = setTimeout(() => { buildCurves(); renderWeb(); }, 60)` |

**每帧实际只做：**

```js
1. c.drawImage(web, 0, 0);                    // 静态线层，一次贴图
2. 画彗星（上限 1400 颗）                      // 每颗 3 点折线 + 1 个 2×2 方块
```

**这就是关键：静态的烘焙，动态的实时。**

---

## 二、FORGE 的线条拓扑（三段式）

```js
// buildCurves()
var busIn = { x: bx, y0: b0, y1: b1, label: "STATE IN" };

for (k = 0; k < nPer; k++) {
  var by = b0 + (k * AG.length + i) / (total - 1) * (b1 - b0);   // 总线格位
  cv = twoSeg(
    [px, y0, ..., bx, by],   // 第1段：卡片 → 总线
    [bx, by, ..., ex, ey]    // 第2段：总线 → 黑洞
  );
}
```

```
客户端卡片 ──→ ║STATE IN║ ──→ 黑洞
   散开          收束           再散开
```

`drawBus()` 就是那条竖带，`352 CH` 是格位数量。

**每段都是三次贝塞尔**（`bzPt` 用 8 个参数：起点、控制点1、控制点2、终点）。

**落点半径独立随机**：

```js
var th = Math.PI * (0.62 + 0.76 * rr());   // 入射角
var re = Rh * (2.0 + rr() * 0.7);          // 落点半径 = 核心的 2~2.7 倍
```

线**不扎进核心**，而是飞向核心周围的环带。

---

## 三、需要借鉴的四项技术

| 技术 | FORGE 怎么做 | 我们该怎么做 |
|---|---|---|
| **静态层烘焙** | 离屏 canvas，只在几何变化时重绘 | 基础线层烘焙，光段实时画 |
| **三段式拓扑** | 卡片 → 总线 → 黑洞 | 客户端 → 总线 → nginx → 总线 → 后端 |
| **贝塞尔控制点** | `bzPt` 三次贝塞尔，切线连续 | 已有 `bz3`，保留 |
| **落点环带** | 半径独立随机，不收敛到一点 | 已实现（`rLand` 抖动） |

---

## 四、我们的架构问题

### 问题 1：所有数量都是硬编码 `4`

```js
for (var ci = 0; ci < 4; ci++)                    // 客户端
for (var ui = 0; ui < 4; ui++)                    // 上游
ANG.push((i - 1.5) * 0.415);                      // 4 条腿均分
var busTop = cy - R * 1.05;                       // 总线跨度固定
```

**加一个客户端要改 8 处。** 必须换成 `CONF.clients.length`。

### 问题 2：静态线每帧重画

现在的 `drawChannelBase`：

```js
for (var li = 0; li < list.length; li++) {
  var path = new Path2D();
  for (var i = 1; i <= p.n; i++) path.lineTo(p.x[i], p.y[i]);   // 每帧重建 237 点
  c.stroke(path);
}
```

12 条 × 237 点 × 8 走廊 = **22,752 次 lineTo，每帧**。

这就是为什么 `LINE_N` 提到 40 会卡。

### 问题 3：没有抽象出「节点」

客户端和上游是两套几乎相同的代码，只是方向不同。

---

## 五、重构方案

### 5.1 数据驱动

```js
var CONF = {
  clients:   [ {id, name, rate, col}, ... ],   // 任意数量
  upstreams: [ {id, name, weight, col}, ... ], // 任意数量
  edge:      { name: 'nginx', modules: [...] }
};
```

所有循环用 `.length`，所有几何按数量动态计算：

```js
// 锚点 y 均分
function anchorY(i, n) {
  var top = V.H * 0.12, bot = V.H * 0.88;
  return n === 1 ? V.H * 0.5 : top + (i / (n - 1)) * (bot - top);
}

// 盘缘角度均分
function rimAngle(i, n) {
  var span = Math.min(1.24, 0.32 * n);       // 数量越多跨度越大，但有上限
  return n === 1 ? 0 : (i / (n - 1) - 0.5) * span;
}
```

### 5.2 两层渲染

```js
// 基础线层：离屏 canvas，几何变化时烘焙
var LINE_LAYER = document.createElement('canvas');
var llctx = LINE_LAYER.getContext('2d');

function bakeLines() {
  llctx.clearRect(0, 0, W, H);
  for each corridor:
    for each of LINE_N paths:
      llctx.beginPath(); ...path...; llctx.stroke();
}

// 每帧
function render(t) {
  ctx.drawImage(BG, 0, 0);
  drawNebula(t);
  ctx.drawImage(LINE_LAYER, 0, 0);      // 一次贴图
  drawSegments(t);                       // 只画光段
}
```

**烘焙时机**：resize、LINE_N 改变、配色改变、状态改变（fail 要变红）。

### 5.3 状态着色也要分层

故障变色如果每帧改，就失去烘焙的意义。方案：

```
基础线层（单色，烘焙）
  +
故障覆盖层（只在有 fail 时烘焙一次，贴在上面）
  +
光段层（实时，颜色跟状态）
```

---

## 六、重构后的性能预估

| 项 | 现在（每帧） | 重构后（每帧） |
|---|---|---|
| 基础线 lineTo | 22,752 | **0**（烘焙） |
| 基础线 stroke | 96 | **1 次 drawImage** |
| 光段 | 8 条 | 8 条（不变） |

`LINE_N` 从 12 提到 40，基础线数量 5→160 条，**每帧成本不变**，因为都在烘焙层里。

---

## 七、建议顺序

1. **先做数据驱动**（问题 1）—— 影响面最大，且不改渲染逻辑
2. **再做烘焙**（问题 2）—— 解锁 LINE_N 提升
3. **最后调视觉** —— 密度、总线位置、落点半径

---

## 八、需要你确认

1. **客户端/上游数量上限**？我建议支持 1–12 个。
2. **总线（STATE IN）要不要画出来**？FORGE 画了，是一条带刻度的竖带。我们的 nginx 居中，可能不需要，或者用别的形式。
3. **密度目标**？FORGE 是 352 条。我们 40 条/走廊 × 8 = 320 条，接近。
