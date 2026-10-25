#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频号封面批量生成（Swiss 编辑网格版式，1080×1260）

用法：
    python cover_gen.py items.json [--out covers] [--brand "苏苏留学有话说"]

items.json 格式（数组）：
    [{
      "seq": "01",
      "ep": "EP.01",
      "cat": "KIRA INTERVIEW",     # 英文分类小字
      "up": "准备 Kira 面试前",      # 上行钩子：共鸣/反问
      "down": "请先听我一句劝",      # 下行钩子：大白话劝告（主视觉，最大字号）
      "action": "Kira 通关",        # 红色行动块
      "color": "#E24B4A",          # 分类色（仅用于顶部小色块）
      "footer": "加拿大申请系列"     # 底栏左侧
    }]

设计要点：
    - 1080×1260（6:7 竖版），朋友圈分享裁 1:1 → 核心信息保持在中间
    - 两行钩子层级：上行浅灰小字（52px），下行黑色超大字（104px）
    - 溢出自检：横向溢出逐级缩字号，纵向溢出再降一档，保证不裁切
    - HTML/CSS 渲染 + Playwright 截图，中文不糊

依赖：pip install playwright（浏览器用系统 Chrome，channel="chrome"）
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

W, H = 1080, 1260
SANS = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif'
ACCENT = "#E24B4A"  # 统一行动块红——信息建筑派只保留一个强调色

CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#fff; font-family:{SANS}; }}
.c {{ width:{W}px; height:{H}px; background:#F6F4EE; color:#191917;
  padding:76px 90px 70px; display:flex; flex-direction:column; overflow:hidden; }}
.top {{ display:flex; justify-content:space-between; align-items:baseline;
  padding-bottom:26px; border-bottom:3px solid #191917; flex:none; }}
.brand {{ font-size:34px; font-weight:600; letter-spacing:2px; }}
.topic {{ font-size:26px; color:#6b6b66; letter-spacing:4px; }}
.main {{ flex:1; display:flex; flex-direction:column; justify-content:center; }}
.kicker {{ display:flex; align-items:center; gap:14px; margin-bottom:40px; }}
.chip {{ width:22px; height:22px; border-radius:3px; background:var(--cat); flex:none; }}
.kicker .ep {{ font-size:30px; font-weight:600; letter-spacing:3px; color:#191917; }}
.kicker .cat {{ font-size:26px; letter-spacing:5px; color:#8a8a84; }}
.up {{ font-size:52px; font-weight:500; color:#8a8a84; letter-spacing:1px;
  line-height:1.25; margin-bottom:30px; }}
.rule {{ width:100%; height:5px; background:#191917; margin-bottom:34px; flex:none; }}
.down {{ font-size:104px; font-weight:800; color:#191917; line-height:1.16;
  letter-spacing:-2px; }}
.badge {{ align-self:flex-start; margin-top:52px; background:{ACCENT}; color:#fff;
  font-size:42px; font-weight:600; padding:20px 40px; border-radius:10px;
  letter-spacing:3px; }}
.foot {{ display:flex; justify-content:space-between; align-items:center;
  border-top:3px solid #191917; padding-top:24px; flex:none; }}
.foot .l {{ font-size:24px; color:#6b6b66; letter-spacing:2px; }}
.foot .r {{ font-size:26px; color:#191917; letter-spacing:2px; font-weight:600; }}
"""


def build_html(items, brand, topic):
    parts = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]
    for it in items:
        seq = it["seq"]
        parts.append(
            f'<div class="c" id="c{seq}" style="--cat:{it.get("color", ACCENT)}">'
            f'<div class="top"><span class="brand">{brand}</span>'
            f'<span class="topic">{topic}</span></div>'
            f'<div class="main">'
            f'<div class="kicker"><span class="chip"></span>'
            f'<span class="ep">{it.get("ep", "")}</span>'
            f'<span class="cat">{it.get("cat", "")}</span></div>'
            f'<div class="up">{it.get("up", "")}</div>'
            f'<div class="rule"></div>'
            f'<div class="down">{it.get("down", "")}</div>'
            f'<div class="badge">{it.get("action", "")}</div>'
            f'</div>'
            f'<div class="foot"><span class="l">{it.get("footer", "")}</span>'
            f'<span class="r">第 {seq} 集</span></div>'
            f'</div>'
        )
    parts.append("</body></html>")
    return "".join(parts)


def fit(page, items):
    """双向溢出自检：横向溢出逐级缩字号；纵向溢出再降一档。"""
    for it in items:
        seq = it["seq"]
        for cls in ("up", "down"):
            sel = f"#c{seq} .{cls}"
            for _ in range(40):
                over = page.evaluate(
                    f"() => {{ const e=document.querySelector('{sel}'); "
                    f"return e && e.scrollWidth > e.clientWidth + 1; }}"
                )
                if not over:
                    break
                page.evaluate(
                    f"() => {{ const e=document.querySelector('{sel}'); "
                    f"e.style.fontSize=(parseFloat(getComputedStyle(e).fontSize)-3)+'px'; }}"
                )
        for _ in range(30):
            over = page.evaluate(
                f"() => {{ const m=document.querySelector('#c{seq} .main'); "
                f"const c=document.querySelector('#c{seq}'); "
                f"return m.scrollHeight > m.clientHeight + 1 || c.scrollHeight > {H}; }}"
            )
            if not over:
                break
            page.evaluate(
                f"() => {{ const d=document.querySelector('#c{seq} .down'); "
                f"d.style.fontSize=(parseFloat(getComputedStyle(d).fontSize)-4)+'px'; }}"
            )


def main():
    ap = argparse.ArgumentParser(description="视频号封面批量生成（Swiss 版式 1080×1260）")
    ap.add_argument("items", help="items.json 路径")
    ap.add_argument("--out", default="covers", help="输出目录")
    ap.add_argument("--brand", default="苏苏留学有话说", help="品牌名（顶栏左）")
    ap.add_argument("--topic", default="加拿大留学", help="栏目名（顶栏右）")
    args = ap.parse_args()

    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    out = Path(args.out)
    if not out.exists():
        out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.set_content(build_html(items, args.brand, args.topic), wait_until="load")
        page.wait_for_timeout(500)
        fit(page, items)
        for it in items:
            seq = it["seq"]
            path = out / f"cover_{seq}.png"
            page.locator(f"#c{seq}").screenshot(path=str(path))
            print("saved:", path)
        browser.close()

    # 尺寸校验
    try:
        from PIL import Image
        for it in items:
            p2 = out / f"cover_{it['seq']}.png"
            size = Image.open(p2).size
            flag = "OK " if size == (W, H) else "❌ "
            print(f"{flag}{p2.name} {size}")
    except ImportError:
        print("（装 pillow 可开启尺寸自检）")
    print("DONE")


if __name__ == "__main__":
    main()
