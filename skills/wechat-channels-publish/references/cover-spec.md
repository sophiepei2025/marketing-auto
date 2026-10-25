# 视频号封面规格 & 批量生成

## 规格

| 项 | 值 |
|----|-----|
| 尺寸 | **1080 × 1260**（6:7 竖版） |
| 格式 | PNG |
| 注意 | 分享到朋友圈会**裁成 1:1**，所以核心信息必须在中间正方形区域内 |

## 设计规律（来自 Canva《视频号封面 10 招》）

1. **尺寸**：竖版 6:7（1080×1260）✅
2. **6 种封面类型**：纯文字 / 人物 IP / 结果对比 / 数字清单 / 场景图 / 图标组合
3. **标题要有「打开率钩子」**：纯文字封面成败全在标题
4. **底部留浮评位**：浮评在视频最下方会遮内容 → 底部 1/6 别放关键文字
5. **左上角加引导关注**：小角标，不宜太大
6. **花叔 huashu-video-check（MrBeast 策略）** 更激进：把「纯文字封面」列为避免项，主张 **结果展示 + 强对比 + 文字 0–5 字**；粉丝 <10 万阶段**不建议人脸封面**（结果比脸更直接）

## 三种可用版式（花叔三大流派）

| 版式 | 风格 | 适合 |
|------|------|------|
| **Swiss 编辑网格** | 米白底 + 黑/红网格 + 结果对比 | 教学、攻略、清单类（当前项目采用） |
| **撞色冲击** | 深底 + 超大标题 + 撞色胶囊 | 想在信息流里最抓眼 |
| **东方留白** | 宣纸底 + 宋体 + 朱红印章 | 差异化、走"人无我有" |

## 批量生成方法（推荐：HTML 模板 + Playwright 截图）

用 HTML/CSS 排版再截图渲染，中文不糊、可精确控制版式、可脚本化改文案。

```python
# 1. 每条内容准备：分类标签 / 英文 kicker / 上行钩子 / 下行钩子 / 配色
ITEMS = [
    ("01", "EP.01", "KIRA INTERVIEW", "准备 Kira 面试前", "请先听我一句劝", "#1F4E9C"),
    ...
]

# 2. 套 HTML 模板，body 宽 1080 高 1260
html = f"""<!doctype html><meta charset="utf-8">
<style>
  body{{margin:0;width:1080px;height:1260px;background:#F5F2EC;
        font-family:"PingFang SC","Noto Sans SC",sans-serif;}}
</style>
<div class="wrap">{title_html}</div>"""

# 3. Playwright 截图
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    pg = b.new_page(viewport={"width":1080,"height":1260})
    pg.set_content(html)
    pg.screenshot(path=f"covers/cover_{seq}.png")
    b.close()
```

### 必做的两道保险

1. **超长行自动缩字号**：钩子文案长短不一，必须按字符数动态降 font-size，否则溢出裁切
2. **截图后校验尺寸**：`PIL` 读一下确认是 1080×1260

```python
from PIL import Image
im = Image.open(path)
assert im.size == (1080, 1260), im.size
```

## 封面与视频号草稿的衔接

视频号脚本的 HITL 终点是**保存草稿**，封面需要在草稿箱里人工替换（脚本未自动化这步，因为草稿编辑页的选择器与发布页不同）。

批量替换草稿封面的思路：
1. 进草稿箱 → 逐条打开编辑
2. 找到「封面」区域 → 上传本地 PNG
3. **不点发表**，保存回草稿

> 自动化这步需要重新做一轮 DOM 诊断（草稿编辑页 ≠ 发布页），别直接套发布页选择器。

## 文案钩子

封面标题用两行钩子结构（上行场景锚点 + 下行大白话劝告）。改写方法与自检脚本见 skill **`mel-robbins-hooks`**。

## 交付

封面 PNG 建议同步一份到 WorkBuddy 资料库（按批次建文件夹），本地作为上传源。
