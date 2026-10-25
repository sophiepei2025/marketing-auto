#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成视频号封面（1080×1260，6:7）。HTML 模板 + Playwright 截图渲染。"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("covers")
if not OUT.exists():
    OUT.mkdir(parents=True, exist_ok=True)

# (文件序号, 英文分类标签, 主标题行1, 主标题行2, 副标题, 主题色)
covers = [
    ("01", "KIRA INTERVIEW", "Kira 面试", "通关秘籍", "拒绝面试“见光死”", "#2563eb"),
    ("02", "KIRA SCORING", "Kira 高分", "真相", "破解人类评审的“模式识别”", "#1d4ed8"),
    ("03", "KIRA PROTOCOL", "Kira 5 步", "黄金答题协议", "答题从此有套路", "#3b82f6"),
    ("04", "UBC SAUDER", "UBC Sauder", "通关秘籍", "告别假大空的极简指南", "#b45309"),
    ("05", "UOFT ENGINEERING", "多大工程", "面试满分逻辑", "满分逻辑拆解", "#15803d"),
    ("06", "WESTERN CASPER", "破解 Western", "Casper 测试", "工程申请避坑指南", "#16a34a"),
    ("07", "QUEEN'S COMMERCE", "女王商学院", "文书通关", "10 分钟限时通关指南", "#d97706"),
    ("08", "YORK SCHULICH", "Schulich", "附加申请", "2026 破解攻略", "#b45309"),
    ("09", "PRE-MED", "加拿大医学院", "五大通道", "升学避坑指南", "#b91c1c"),
    ("10", "UBC SCIENCE", "UBC 理科", "活动描述转化", "跨越转化的鸿沟", "#15803d"),
]

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; }
.cover {
  width: 1080px; height: 1260px; position: relative; overflow: hidden;
  background: linear-gradient(165deg, var(--accent) 0%, #0b1220 78%);
  color: #fff;
}
.deco1 { position:absolute; right:-200px; top:-200px; width:560px; height:560px;
  border-radius:50%; background:rgba(255,255,255,0.07); }
.deco2 { position:absolute; left:-140px; bottom:-140px; width:400px; height:400px;
  border-radius:50%; background:rgba(255,255,255,0.05); }
.deco3 { position:absolute; left:70px; top:400px; width:16px; height:16px;
  border-radius:50%; background:rgba(255,255,255,0.5); }
.topbar { position:absolute; left:90px; right:90px; top:80px; display:flex;
  align-items:center; justify-content:space-between; }
.brand { font-size:38px; font-weight:600; letter-spacing:2px; }
.tag { font-size:30px; padding:10px 24px; border:2px solid rgba(255,255,255,0.55);
  border-radius:40px; color:rgba(255,255,255,0.9); }
.kicker { position:absolute; left:90px; top:330px; font-size:34px; letter-spacing:6px;
  color:rgba(255,255,255,0.75); font-weight:500; }
.title { position:absolute; left:84px; top:410px; font-size:150px; font-weight:700;
  line-height:1.12; letter-spacing:2px; }
.title .l2 { display:block; }
.sub { position:absolute; left:90px; top:800px; font-size:44px; font-weight:500;
  color:rgba(255,255,255,0.92); line-height:1.4; max-width:900px; }
.footer { position:absolute; left:90px; right:90px; bottom:80px; display:flex;
  align-items:center; justify-content:space-between; }
.footline { width:150px; height:6px; background:rgba(255,255,255,0.6); border-radius:3px; }
.foottxt { font-size:28px; color:rgba(255,255,255,0.6); letter-spacing:2px; }
"""


def build_html():
    parts = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]
    for seq, kicker, l1, l2, sub, color in covers:
        parts.append(
            f'<div class="cover" id="c{seq}" style="--accent:{color}">'
            f'<div class="deco1"></div><div class="deco2"></div><div class="deco3"></div>'
            f'<div class="topbar"><span class="brand">苏苏留学有话说</span>'
            f'<span class="tag">加拿大留学</span></div>'
            f'<div class="kicker">{kicker}</div>'
            f'<div class="title">{l1}<span class="l2">{l2}</span></div>'
            f'<div class="sub">{sub}</div>'
            f'<div class="footer"><span class="footline"></span>'
            f'<span class="foottxt">收藏 · 转发 · 关注</span></div>'
            f'</div>'
        )
    parts.append("</body></html>")
    return "".join(parts)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1080, "height": 1260}, device_scale_factor=1)
    page.set_content(build_html(), wait_until="load")
    page.wait_for_timeout(500)
    for seq, *_ in covers:
        el = page.locator(f"#c{seq}")
        el.screenshot(path=str(OUT / f"cover_{seq}.png"))
        print("saved:", f"cover_{seq}.png")
    browser.close()
print("DONE")
