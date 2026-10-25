#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书图文批量发布（走本地 xiaohongshu-mcp 服务 :18060）

安全模式（默认）：visibility=仅自己可见 —— 内容会出现在你的笔记列表但别人看不到，
你在 App 里检查满意后，逐条改成公开即可；这就是"先不发，检查后再发"的实现方式。

用法：
  python3 xhs_publish.py check          # 查登录状态
  python3 xhs_publish.py run            # 批量发布 xhs_tasks.json（仅自己可见）
  python3 xhs_publish.py run --public   # 直接公开（风险自担）
  python3 xhs_publish.py run --start 3  # 从第 3 条断点续跑
"""
import json
import sys
import time
from pathlib import Path

import mcp_call

BASE = Path(__file__).resolve().parent
TASKS = BASE / "xhs_tasks.json"
STATE = BASE / "xhs_results.json"


def call_tool(name, args, timeout=180):
    # 发布含图片上传 + 指纹生成，实测可能超过 3 分钟，放宽到 7 分钟
    res, _ = mcp_call.post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                            "params": {"name": name, "arguments": args}}, timeout=timeout)
    err = res.get("error")
    if err:
        return False, json.dumps(err, ensure_ascii=False)[:300]
    texts = [c.get("text", "") for c in res["result"].get("content", [])
             if c.get("type") == "text"]
    text = "\n".join(texts)
    ok = ("成功" in text or "已发布" in text or "✅" in text or "成功发布" in text)
    return ok, text[:500]


def check():
    ok, text = call_tool("check_login_status", {})
    print("登录状态：", text)


def run(start=1, public=False, interval=30):
    tasks = json.load(open(TASKS, encoding="utf-8"))
    results = json.load(open(STATE, encoding="utf-8")) if STATE.exists() else {}
    vis = "公开可见" if public else "仅自己可见"
    print(f"共 {len(tasks)} 条，从第 {start} 条开始，可见范围：{vis}")
    for t in tasks:
        seq = t["seq"]
        if int(seq) < start:
            continue
        if results.get(seq, {}).get("ok"):
            print(f"[{seq}] 已成功过，跳过")
            continue
        if not Path(t["image"]).exists():
            print(f"[{seq}] 图片缺失：{t['image']}")
            results[seq] = {"ok": False, "msg": "图片缺失"}
            json.dump(results, open(STATE, "w"), ensure_ascii=False, indent=1)
            continue
        args = {
            "title": t["title"],
            "content": t["content"],
            "images": [t["image"]],
            "tags": t["tags"],
            "visibility": vis,
            "is_original": True,
        }
        print(f"[{seq}] 发布中：{t['title']}")
        ok, text = call_tool("publish_content", args)
        results[seq] = {"ok": ok, "msg": text.replace("\n", " ")[:200]}
        json.dump(results, open(STATE, "w"), ensure_ascii=False, indent=1)
        print(f"[{seq}] {'✅' if ok else '❌'} {text[:120]}")
        if int(seq) != len(tasks):
            print(f"    等 {interval}s 防风控…")
            time.sleep(interval)
    done = sum(1 for v in results.values() if v.get("ok"))
    print(f"完成：{done}/{len(tasks)} 成功。明细见 {STATE.name}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        check()
    elif cmd == "run":
        start = int(sys.argv[sys.argv.index("--start") + 1]) if "--start" in sys.argv else 1
        public = "--public" in sys.argv
        run(start, public)
    else:
        print(__doc__)
