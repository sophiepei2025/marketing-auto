#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频号助手批量发布脚本（Playwright 驱动官方网页）

合规提示：视频号没有面向普通创作者的公开发布 API，本脚本通过驱动官方
「视频号助手」网页(channels.weixin.qq.com)实现半自动/自动发布，属于
"浏览器自动化"路径，存在平台风控风险。默认 HITL 模式（自动填表 + 人工
最终确认），请优先使用；--auto 全自动发布风险自担。

用法：
  python publish.py login                 # 首次：可见窗口扫码登录，登录态存入 profile/
  python publish.py publish --csv 排期表.csv            # HITL：填表后停在"发表"前
  python publish.py publish --csv 排期表.csv --auto     # 全自动：自动点"发表"
  python publish.py publish --csv 排期表.csv --start 3  # 从第 N 条开始（断点续跑）
"""

import argparse
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = Path(__file__).resolve().parent
PROFILE_DIR = BASE / "profile"
VIDEO_DIR = BASE / "videos"
LOG_DIR = BASE / "logs"
SHOT_DIR = BASE / "screenshots"
CHANNELS_URL = "https://channels.weixin.qq.com/platform"
POST_URL = "https://channels.weixin.qq.com/platform/post/create"

# 中文 / 英文表头映射（key = 内部字段，value = 可能的表头名）
FIELD_MAP = {
    "video": ("视频文件", "video"),
    "title": ("标题", "title"),
    "topic": ("话题", "topic"),
    "short_title": ("短标题", "short_title"),
    "publish_time": ("定时发布时间", "publish_time"),
    "collection": ("合集", "collection"),
    "original": ("原创声明", "original"),
    "status": ("状态", "status"),
}
PENDING_STATUS = {"", "待上传", "待发布", "pending", "todo"}
HITL_WAIT = 240  # HITL 模式填表后保持浏览器打开的秒数，供人工点发表


def ensure_dir(path: Path):
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)


def setup_logging():
    ensure_dir(LOG_DIR)
    ensure_dir(SHOT_DIR)
    logfile = LOG_DIR / f"publish_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(logfile, encoding="utf-8"),
        ],
    )
    return logfile


def load_csv(path: Path):
    if not path.exists():
        raise SystemExit(f"CSV 不存在: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h for h in (reader.fieldnames or [])]
        col2field, field2col = {}, {}
        for h in header:
            hs = h.strip()
            for field, names in FIELD_MAP.items():
                if hs in names:
                    col2field[hs] = field
                    field2col[field] = h
                    break
        rows = []
        for raw in reader:
            row = dict(raw)
            for h, val in raw.items():
                field = col2field.get(h.strip())
                if field:
                    row["_" + field] = (val or "").strip()
            if row.get("_video"):
                rows.append(row)
    return header, field2col, rows


def save_csv(path: Path, header, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def find(page, candidates, timeout=8000):
    """按候选选择器依次尝试，返回第一个可见 Locator；总时长不超过 timeout。"""
    deadline = time.time() + timeout
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            remaining = max(500, int((deadline - time.time()) * 1000))
            loc.wait_for(state="visible", timeout=remaining)
            if loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def cmd_login(args):
    ensure_dir(LOG_DIR)
    ensure_dir(PROFILE_DIR)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            channel=args.channel or "chrome",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CHANNELS_URL)
        print(">> 请在弹出的浏览器中用手机微信扫码登录视频号助手")
        print(">> 登录成功后脚本会自动保存并退出（最长等待 %d 秒）" % args.timeout)

        deadline = time.time() + args.timeout
        logged_in = False
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            # 信号1：channels 域出现登录凭据 cookie（登录态的本质，最可靠）
            try:
                cookies = ctx.cookies("https://channels.weixin.qq.com")
            except Exception:
                cookies = []
            has_cred = any(
                "ticket" in c["name"].lower()
                or "session" in c["name"].lower()
                or "uin" in c["name"].lower()
                or "skey" in c["name"].lower()
                or "token" in c["name"].lower()
                or "login" in c["name"].lower()
                for c in cookies
            )
            # 信号2：URL 已离开登录页
            away_login = "login" not in page.url.lower()
            # 信号3：后台首页出现头像/账号元素
            ui_ready = bool(find(page, ['[class*="avatar"]', '[class*="profile-img"]', '[class*="user-info"]'], timeout=800))
            if has_cred or (away_login and ui_ready):
                logged_in = True
                break

        if logged_in:
            print(">> 登录成功！登录态已保存到 profile/ 目录")
        else:
            print(">> 超时未检测到登录成功，请确认已扫码并重试")
        ctx.close()


def publish_one(page, row, dry_run, idx):
    video = row.get("_video", "")
    title = row.get("_title", "")
    topic = row.get("_topic", "")
    short_title = row.get("_short_title", "")
    collection = row.get("_collection", "")
    original = row.get("_original", "")
    video_path = VIDEO_DIR / video
    if not video_path.exists():
        logging.warning("[%s] 视频文件不存在: %s", idx, video_path)
        return False

    logging.info("[%s] 开始发布: %s", idx, video)

    # 1. 直达发布页
    page.goto(POST_URL)

    # 2. 等描述框出现（未上传视频时表单已渲染）
    desc = page.locator('[data-placeholder="添加描述"]').first
    if desc.count() == 0:
        desc = page.locator('div.input-editor').first
    if desc.count() == 0:
        desc = page.locator('[contenteditable]').first
    try:
        desc.wait_for(state="visible", timeout=60000)
    except Exception:
        page.screenshot(path=str(SHOT_DIR / f"{idx}_no_desc.png"))
        logging.error("[%s] 未找到描述框", idx)
        return False

    # 3. 上传视频（等 file input 挂载，发布页为 SPA 异步渲染）
    file_input = page.locator('input[type="file"][accept*="video"]').first
    try:
        file_input.wait_for(state="attached", timeout=30000)
    except Exception:
        file_input = page.locator('input[type="file"]').first
        try:
            file_input.wait_for(state="attached", timeout=30000)
        except Exception:
            page.screenshot(path=str(SHOT_DIR / f"{idx}_no_file_input.png"))
            logging.error("[%s] 找不到文件上传 input", idx)
            return False
    try:
        file_input.set_input_files(str(video_path))
    except Exception as e:
        logging.error("[%s] 上传视频失败: %s", idx, e)
        return False
    logging.info("[%s] 视频已提交上传，等待转码...", idx)

    # 4. 等保存草稿按钮从 disabled 变为可用（转码完成）
    try:
        page.wait_for_function(
            "() => { const b = [...document.querySelectorAll('button')].find("
            "x => x.textContent.trim() === '保存草稿' && x.offsetParent !== null);"
            " return !!b && !b.classList.contains('weui-desktop-btn_disabled'); }",
            timeout=180000,
        )
        logging.info("[%s] 转码完成，按钮就绪", idx)
    except Exception:
        logging.warning("[%s] 保存草稿按钮长时间未就绪，继续尝试填表", idx)

    # 5. 填描述（标题 + 话题）
    text = f"{title}\n{topic}" if (title and topic) else (title or topic)
    if text:
        try:
            desc.click()
            desc.fill(text)
        except Exception:
            try:
                desc.click()
                desc.press_sequentially(text)
            except Exception as e:
                logging.warning("[%s] 填描述失败: %s", idx, e)
    logging.info("[%s] 已填描述", idx)

    # 6. 短标题
    if short_title:
        st = page.locator('input[placeholder*="短标题"]').first
        if st.count() > 0:
            try:
                st.fill(short_title)
                logging.info("[%s] 已填短标题", idx)
            except Exception as e:
                logging.warning("[%s] 填短标题失败: %s", idx, e)

    # 7. 合集（尽力而为；输入框默认折叠，不可见则跳过）
    if collection:
        col = page.locator('input[placeholder*="合集"]').first
        if col.count() > 0 and col.is_visible():
            try:
                col.fill(collection)
                page.wait_for_timeout(1200)
                opt = page.get_by_text(collection, exact=True).first
                if opt.count() > 0 and opt.is_visible():
                    try:
                        opt.click()
                    except Exception:
                        pass
                logging.info("[%s] 已填合集", idx)
            except Exception as e:
                logging.warning("[%s] 填合集失败: %s", idx, e)
        else:
            logging.info("[%s] 合集输入框不可见，跳过（可后续手动添加）", idx)

    # 8. 原创声明（可选）
    if original in ("是", "yes", "1", "true", "Y", "y"):
        orig = page.get_by_text("声明原创", exact=True).first
        if orig.count() > 0 and orig.is_visible():
            try:
                orig.click()
                page.wait_for_timeout(1500)
                agree = page.get_by_text("同意", exact=True).first
                if agree.count() > 0 and agree.is_visible():
                    try:
                        agree.click()
                    except Exception:
                        pass
                logging.info("[%s] 已声明原创", idx)
            except Exception as e:
                logging.warning("[%s] 声明原创失败: %s", idx, e)

    # 6. 截图留证
    shot = SHOT_DIR / f"{idx}_before_submit.png"
    page.screenshot(path=str(shot))
    logging.info("[%s] 表单已填好，截图: %s", idx, shot.name)

    if dry_run:
        draft = page.locator('button:has-text("保存草稿")').first
        try:
            draft.click(timeout=8000)
            page.wait_for_timeout(3000)
            logging.info("[%s] 已保存草稿，请到草稿箱改封面/定时后发表", idx)
            return True
        except Exception as e:
            logging.warning("[%s] 点保存草稿失败: %s", idx, e)
            page.screenshot(path=str(SHOT_DIR / f"{idx}_no_draft.png"))
            return False
    submit = page.get_by_text("发表", exact=True).first
    if submit.count() == 0:
        submit = page.locator('button:has-text("发表")').last
    try:
        submit.click(timeout=8000)
        page.wait_for_timeout(3000)
        logging.info("[%s] 已点击发表", idx)
        return True
    except Exception as e:
        logging.error("[%s] 点击发表失败: %s", idx, e)
        return False


def cmd_publish(args):
    logfile = setup_logging()
    csv_path = Path(args.csv).resolve() if args.csv else (BASE / "schedule.csv")
    header, field2col, rows = load_csv(csv_path)
    status_col = field2col.get("status")

    todo = [r for r in rows if r.get("_status", "") in PENDING_STATUS]
    logging.info("共 %d 条，待处理 %d 条", len(rows), len(todo))
    if args.start > 1:
        todo = todo[args.start - 1:]
        logging.info("从第 %d 条开始，剩余 %d 条", args.start, len(todo))
    if args.limit and args.limit > 0:
        todo = todo[:args.limit]
        logging.info("本次只处理前 %d 条", args.limit)
    if not todo:
        logging.info("没有待处理的记录")
        return

    dry_run = not args.auto
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            channel=args.channel or "chrome",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CHANNELS_URL)
        if not find(page, ["text=发表", "text=发表动态"], timeout=15000):
            logging.error("未检测到登录态，请先运行: python publish.py login")
            ctx.close()
            return

        for i, row in enumerate(todo, start=args.start):
            ok = publish_one(page, row, dry_run=dry_run, idx=i)
            if status_col:
                if ok:
                    row[status_col] = "待确认" if dry_run else "已发布"
                else:
                    row[status_col] = "失败"
            save_csv(csv_path, header, rows)  # 每条后保存，便于断点续跑

        ctx.close()
    logging.info("完成。日志: %s", logfile)


def main():
    ap = argparse.ArgumentParser(description="视频号助手批量发布脚本")
    ap.add_argument("command", choices=["login", "publish"])
    ap.add_argument("--csv", help="排期表路径（默认本目录 schedule.csv）")
    ap.add_argument("--channel", help="浏览器 channel（默认 chrome，即系统 Chrome）")
    ap.add_argument("--timeout", type=int, default=180, help="登录等待秒数（默认 180）")
    ap.add_argument("--start", type=int, default=1, help="从第 N 条开始（断点续跑）")
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理 N 条（0=全部）")
    ap.add_argument("--auto", action="store_true", help="全自动点「发表」（默认 HITL 停在发表前）")
    args = ap.parse_args()
    if args.command == "login":
        cmd_login(args)
    else:
        cmd_publish(args)


if __name__ == "__main__":
    main()
