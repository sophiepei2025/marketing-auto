#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频号封面 · Swiss 编辑网格版式（1080×1260）
保留信息建筑派设计语言：米白纸底 + 黑色粗分隔线 + 超大主句 + 单一红色行动块。
文案采用 Mel Robbins 风格两行钩子：上行共鸣/反问，下行大白话劝告。
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("covers")
if not OUT.exists():
    OUT.mkdir(parents=True, exist_ok=True)

SANS = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif'

# (序号, EP, 英文分类, 上行[共鸣/反问], 下行[劝告], 行动块, 分类色)
covers = [
    ("01", "EP.01", "KIRA INTERVIEW", "准备 Kira 面试前", "请先听我一句劝", "Kira 通关", "#E24B4A"),
    ("02", "EP.02", "KIRA SCORING", "招生官看面试视频", "真的只看前 15 秒", "评分内幕", "#C0392B"),
    ("03", "EP.03", "KIRA PROTOCOL", "倒计时一响就脑子空白？", "记住这个万能公式", "5 步答题", "#D35400"),
    ("04", "EP.04", "UBC SAUDER", "申请 UBC Sauder 商学院", "千万别说这 3 句假大空", "商科面试", "#A04000"),
    ("05", "EP.05", "UOFT ENGINEERING", "均分 95+ 为何被多大秒拒？", "他们踩了这道死穴", "工程面试", "#1E7145"),
    ("06", "EP.06", "WESTERN CASPER", "Western Casper 情境测试", "最忌讳非黑即白", "Casper", "#17693C"),
    ("07", "EP.07", "QUEEN'S COMMERCE", "10 分钟写出高分文书", "你只需要这套节奏", "限时文书", "#B7791F"),
    ("08", "EP.08", "YORK SCHULICH", "申请约克舒立克商学院", "别把领导力写成流水账", "附加申请", "#8C5A00"),
    ("09", "EP.09", "PRE-MED", "想在加拿大读医？", "千万别在选专业上交学费", "医学路径", "#96281B"),
    ("10", "EP.10", "UBC SCIENCE", "课外活动平平无奇？", "如何救活你的 UBC 文书", "活动描述", "#4A6B22"),
    ("11", "EP.11", "MOCKVIEW AI", "被 Kira 面试整崩溃？", "提前练到不慌", "AI 模拟面试", "#4A3B8C"),
]

ACCENT = "#E24B4A"  # 统一行动块红（信息建筑派只保留一个强调色）

CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#fff; font-family:{SANS}; }}
.c {{ width:1080px; height:1260px; background:#F6F4EE; color:#191917;
  padding:76px 90px 70px; display:flex; flex-direction:column; overflow:hidden; }}

/* 顶栏 */
.top {{ display:flex; justify-content:space-between; align-items:baseline;
  padding-bottom:26px; border-bottom:3px solid #191917; flex:none; }}
.brand {{ font-size:34px; font-weight:600; letter-spacing:2px; }}
.topic {{ font-size:26px; color:#6b6b66; letter-spacing:4px; }}

/* 主区 */
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

/* 底栏 */
.foot {{ display:flex; justify-content:space-between; align-items:center;
  border-top:3px solid #191917; padding-top:24px; flex:none; }}
.foot .l {{ font-size:24px; color:#6b6b66; letter-spacing:2px; }}
.foot .r {{ font-size:26px; color:#191917; letter-spacing:2px; font-weight:600; }}
"""


def build_html():
    parts = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]
    for seq, ep, cat, up, down, action, color in covers:
        parts.append(
            f'<div class="c" id="c{seq}" style="--cat:{color}">'
            f'<div class="top"><span class="brand">苏苏留学有话说</span>'
            f'<span class="topic">加拿大留学</span></div>'
            f'<div class="main">'
            f'<div class="kicker"><span class="chip"></span>'
            f'<span class="ep">{ep}</span><span class="cat">{cat}</span></div>'
            f'<div class="up">{up}</div>'
            f'<div class="rule"></div>'
            f'<div class="down">{down}</div>'
            f'<div class="badge">{action}</div>'
            f'</div>'
            f'<div class="foot"><span class="l">苏苏留学 · 加拿大申请系列</span>'
            f'<span class="r">第 {seq} 集</span></div>'
            f'</div>'
        )
    parts.append("</body></html>")
    return "".join(parts)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1080, "height": 1260}, device_scale_factor=1)
    page.set_content(build_html(), wait_until="load")
    page.wait_for_timeout(500)

    # 溢出自检：主句/共鸣行超出宽度则逐步缩字号，保证不被裁切
    for seq, *_ in covers:
        for cls in ("up", "down"):
            sel = f"#c{seq} .{cls}"
            guard = 0
            while guard < 40:
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
                guard += 1

    # 高度自检：主区若超出容器则整体缩一档
    for seq, *_ in covers:
        guard = 0
        while guard < 30:
            over = page.evaluate(
                f"() => {{ const m=document.querySelector('#c{seq} .main'); "
                f"const c=document.querySelector('#c{seq}'); "
                f"return m.scrollHeight > m.clientHeight + 1 || c.scrollHeight > 1260; }}"
            )
            if not over:
                break
            page.evaluate(
                f"() => {{ const d=document.querySelector('#c{seq} .down'); "
                f"d.style.fontSize=(parseFloat(getComputedStyle(d).fontSize)-4)+'px'; }}"
            )
            guard += 1

    for seq, *_ in covers:
        page.locator(f"#c{seq}").screenshot(path=str(OUT / f"cover_{seq}.png"))
        print("saved:", f"cover_{seq}.png")
    browser.close()
print("DONE")
