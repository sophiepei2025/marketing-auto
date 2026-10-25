#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钩子文案自检：机构感词黑名单 + 字数 + 结构检查

用法：
  python3 lint_copy.py "准备 Kira 面试前" "请先听我一句劝"
  python3 lint_copy.py --file 排期表.csv        # 检查标题列（会自动合成上下行）
"""
import argparse
import re
import sys

BLOCKLIST = [
    "秘籍", "指南", "攻略", "宝典", "全解析", "深度剖析", "赋能", "助力",
    "闭环", "抓手", "体系", "方法论", "打通", "解读", "漫谈", "浅析",
    "提升", "塑造", "实现xxx", "浅谈", "概述", "综述",
]
WEAK_OPENERS = ["如何", "关于", "谈谈", "分享", "介绍"]


def check(up: str, down: str, platform: str = "视频号") -> list:
    """返回问题列表，空列表 = 通过"""
    issues = []
    text = f"{up}{down}"

    hits = [w for w in BLOCKLIST if w in text]
    if hits:
        issues.append(f"❌ 命中机构感词：{'、'.join(hits)}")

    for w in WEAK_OPENERS:
        if text.startswith(w):
            issues.append(f"❌ 以「{w}」开头，缺乏钩子，请换成场景/反问")

    if down:  # 单行标题（如小红书）跳过两行结构检查
        # 上行的合法模式（对应 hook-formulas.md 的 8 式）
        UP_PATTERNS = [
            r"前$",                        # 场景锚点：在…之前
            r"[？?]",                      # 反问式
            r"(招生官|评审|导师|教授|系统|学校)",  # 揭评分黑箱
            r"^(申请|想|准备|考|报|申)",    # 群体点名（动词开头）
            r"(申请.*的|想.*的|准备.*的)",  # 群体点名
            r"(分钟|秒钟|\d+\s*秒|小时)",   # 时限压迫
            r"(平平无奇|崩溃|空白|没戏|被拒|秒拒|不知道)",  # 痛点自白
            r"(别在|千万别)",              # 代价警告
        ]
        if not any(re.search(pa, up) for pa in UP_PATTERNS):
            issues.append("⚠️ 上行缺少代入锚点：加具体场景/反问/数字/痛点词")

        DOWN_OPENERS = r"^(请|别|千万别|记住|你|如何|最忌讳|真的|他们|这|那|只要)"
        if not re.match(DOWN_OPENERS, down):
            issues.append("⚠️ 下行建议以劝告/禁令动词开头（请/别/千万别/记住/你只需要）")

    # 各平台字数规则：封面按「每行」判，图文/YouTube 按「整句」判
    if platform == "视频号" and down:
        for label, line in (("上行", up), ("下行", down)):
            n = len([c for c in line if c.strip()])
            if n > 14:
                issues.append(f"❌ {label} 超长：{n} 字 > 14（封面建议 ≤12–14 字/行）")
        if len(down) > len(up) + 6:
            issues.append("⚠️ 下行应比上行短且更狠，视觉层级做不出来")
    elif platform == "小红书":
        # 中文字计 1，连续英文数字算 1 个词
        total = len([c for c in text if "一" <= c <= "鿿"]) + len(re.findall(r"[A-Za-z0-9]+", text))
        if total > 20:
            issues.append(f"❌ 超长：{total} > 20（小红书标题限制）")
    elif platform == "YouTube":
        if len(text) > 70:
            issues.append(f"❌ 超长：{len(text)} > 70 字符（YouTube 标题建议）")

    return issues


def main():
    ap = argparse.ArgumentParser(description="钩子文案自检")
    ap.add_argument("lines", nargs="*", help="上行 下行")
    ap.add_argument("--file", help="CSV 文件（检查标题列）")
    ap.add_argument("--platform", default="视频号", choices=["小红书", "视频号", "YouTube"])
    args = ap.parse_args()

    if args.file:
        import csv
        with open(args.file, encoding="utf-8-sig") as f:
            for i, row in enumerate(csv.DictReader(f), 1):
                title = (row.get("标题") or "").strip()
                if not title:
                    continue
                parts = re.split(r"[，,]\s*", title, maxsplit=1)
                if len(parts) < 2:
                    # 没有逗号：在「？/。」处断，或按下行动词强行切
                    m = re.search(r"[？?]", title)
                    if m:
                        up, down = title[:m.end()], title[m.end():]
                    else:
                        m = re.search(r"(?=请|别|千万|记住|你只需|最忌讳|如何|真的)", title)
                        up, down = (title[:m.start()], title[m.start():]) if m else (title, title)
                else:
                    up, down = parts[0], parts[1]
                issues = check(up, down, args.platform)
                flag = "✅" if not issues else "  ".join(issues)
                print(f"{i:>2}. {title}  →  {flag}")
        return

    if len(args.lines) < 2:
        print(__doc__)
        sys.exit(1)

    up, down = args.lines[0], args.lines[1]
    print(f"上行：{up}")
    print(f"下行：{down}")
    issues = check(up, down, args.platform)
    if issues:
        for i in issues:
            print(i)
        sys.exit(1)
    print("✅ 通过")


if __name__ == "__main__":
    main()
