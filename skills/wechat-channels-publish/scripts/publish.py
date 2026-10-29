#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频号助手批量发布脚本（Playwright 驱动官方网页·iframe + 自动播放修复版）

本版关键修复（针对「视频上传后自动播放、点不进下一步」）：
  1. 发布表单整体渲染在 <iframe name="content"> 内（URL .../micro/content/post/create）。
     原版在 main frame 上操作，描述框/按钮全查不到，回退到错误的 [contenteditable]
     又被 autoplay 遮罩盖住 → click 30s 超时。本版所有操作都在该 iframe 内执行。
  2. 视频自动播放的元素也在 iframe 内（实测 5 个 <video>），原版 page.evaluate
     在 main frame 查到 0 个 video，等于没暂停。本版在 iframe 内 JS 暂停+静音所有
     video，释放焦点，确保「保存草稿 / 发表」按钮可点中。
  3. 描述框用 JS 注入填值（绕开被遮罩元素），失败再回退 click+fill(force)。
  4. 点按钮前先 scrollIntoView + force=True，并兼容可能的「下一步」。

合规提示：视频号无面向普通创作者的公开发布 API，本脚本属"浏览器自动化"路径，有
平台风控风险。默认 HITL（自动填表 + 存草稿，人工到后台点发表）；--auto 全自动风险自担。

用法：
  python publish.py login                 # 首次：可见窗口扫码登录，登录态存入 profile/
  python publish.py publish --csv 排期表.csv            # HITL：填表后存草稿，停在发表前
  python publish.py publish --csv 排期表.csv --auto     # 全自动：自动点「发表」
  python publish.py publish --csv 排期表.csv --start 3  # 从第 N 条开始（断点续跑）
"""

import argparse
import csv
import logging
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
PROFILE_DIR = BASE / "profile"
VIDEO_DIR = BASE / "videos"
LOG_DIR = BASE / "logs"
SHOT_DIR = BASE / "screenshots"
CHANNELS_URL = "https://channels.weixin.qq.com/platform"
POST_URL = "https://channels.weixin.qq.com/platform/post/create"
CONTENT_FRAME_URL = "micro/content/post/create"  # 发布表单所在 iframe 的 URL 特征

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


def get_content_frame(page, timeout=30000):
    """拿到发布表单所在的 iframe（name=content 或 URL 含 micro/content/post/create）。"""
    fr = page.frame(name="content")
    if fr:
        return fr
    deadline = time.time() + timeout
    while time.time() < deadline:
        for fr in page.frames:
            if CONTENT_FRAME_URL in fr.url:
                return fr
        time.sleep(0.4)
    return page.frame(name="content")


def login_state(ctx, page):
    try:
        cookies = ctx.cookies("https://channels.weixin.qq.com")
    except Exception:
        cookies = []
    has_cred = any(
        any(k in c["name"].lower() for k in ("ticket", "session", "uin", "skey", "token", "login"))
        for c in cookies
    )
    away_login = "login" not in (page.url or "").lower()
    return has_cred and away_login


def login_state_offline():
    db = PROFILE_DIR / "Default" / "Cookies"
    if not db.exists():
        return False, "profile/Default/Cookies 不存在"
    tmp = None
    try:
        tmp = Path(tempfile.mkstemp(suffix=".db")[1])
        shutil.copy(db, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT host_key, name FROM cookies "
            "WHERE host_key LIKE '%channels.weixin.qq.com%' OR host_key LIKE '%weixin%'"
        ).fetchall()
        con.close()
        cred = [
            (h, n) for h, n in rows
            if any(k in n.lower() for k in ("ticket", "session", "uin", "skey", "token", "login"))
        ]
        return (bool(cred), f"凭据 cookie: {[n for _, n in cred] or '无'}")
    except Exception as e:
        return False, f"读取失败: {e}"
    finally:
        if tmp and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def cmd_check(args):
    ok, detail = login_state_offline()
    print(f"{'✅ 已登录' if ok else '❌ 未登录'}（{detail}）")
    if not ok:
        print("   → 先运行: python publish.py login")
    return ok


def cmd_check_online(args):
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=True, channel=args.channel or "chrome")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(CHANNELS_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logging.warning("打开后台超时: %s", e)
        page.wait_for_timeout(2000)
        ok = login_state(ctx, page)
        print(f"{'✅ 在线复核：已登录' if ok else '❌ 在线复核：未登录'}")
        try:
            ctx.close()
        except Exception:
            pass
        return ok


def cmd_login(args):
    ensure_dir(LOG_DIR)
    ensure_dir(PROFILE_DIR)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, channel=args.channel or "chrome")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CHANNELS_URL)
        print(">> 请在弹出的浏览器中用手机微信扫码登录视频号助手")
        print(">> 登录成功后脚本会自动保存并退出（最长等待 %d 秒）" % args.timeout)
        deadline = time.time() + args.timeout
        logged_in = False
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            if login_state(ctx, page):
                logged_in = True
                break
        if logged_in:
            print(">> 登录成功！登录态已保存到 profile/ 目录")
        else:
            print(">> 超时未检测到登录成功，请确认已扫码并重试")
        ctx.close()


def pause_video(frame):
    """★关键修复：在 iframe 内暂停并静音所有 <video>（kill 自动播放）。返回暂停个数。"""
    try:
        return frame.evaluate(
            "() => { const vs = document.querySelectorAll('video');"
            " vs.forEach(v => { try { v.pause(); v.muted = true; v.loop = false;"
            " v.style.pointerEvents='none'; } catch(e){} }); return vs.length; }"
        )
    except Exception:
        return 0


def fill_description(page, frame, text, idx):
    """在 iframe 内填描述：先暂停视频，再 JS 注入（绕开遮罩），失败回退 click+fill(force)。"""
    if not text:
        return True
    # iframe 内真实选择器（diag3 实测）
    selectors = [
        '[data-placeholder="添加描述"]',
        'div.input-editor',
        '[contenteditable]',
        'textarea[placeholder*="添加描述"]',
    ]
    sel = None
    deadline = time.time() + 15
    while time.time() < deadline:
        for s in selectors:
            try:
                has_el = frame.evaluate("(sel) => !!document.querySelector(sel)", s)
                if has_el:
                    sel = s
                    break
            except Exception:
                pass
        if sel:
            break
        time.sleep(0.5)

    if not sel:
        page.screenshot(path=str(SHOT_DIR / f"{idx}_no_desc.png"))
        logging.error("[%s] 未找到描述框（iframe 内尝试过 %s）", idx, selectors)
        return False

    pause_video(frame)
    frame.wait_for_timeout(400)

    # 方案 A：JS 注入
    try:
        res = frame.evaluate(
            """(args) => {
                const el = document.querySelector(args.sel);
                if (!el) return 'no-el';
                el.focus();
                if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                    setter.call(el, args.text);
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                } else {
                    el.innerText = args.text;
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                }
                return 'filled:' + el.tagName;
            }""",
            {"sel": sel, "text": text},
        )
        if isinstance(res, str) and res.startswith("filled"):
            check = frame.evaluate(
                "(args) => { const el=document.querySelector(args.sel);"
                " return (el ? (el.innerText||el.value||'') : ''); }",
                {"sel": sel},
            )
            if check and check.strip():
                logging.info("[%s] 已用 JS 注入填描述（%s）：%s", idx, res, sel)
                return True
            logging.warning("[%s] JS 注入后描述仍空，回退 click+fill", idx)
    except Exception as e:
        logging.warning("[%s] JS 注入异常: %s，回退 click+fill", idx, e)

    # 方案 B：click + fill（force）
    try:
        loc = frame.locator(sel).first
        loc.scroll_into_view_if_needed()
        loc.click(force=True, timeout=8000)
        frame.wait_for_timeout(200)
        loc.fill(text, timeout=8000)
        logging.info("[%s] 已用 click+fill 填描述: %s", idx, sel)
        return True
    except Exception as e:
        logging.warning("[%s] 填描述失败: %s", idx, e)
        page.screenshot(path=str(SHOT_DIR / f"{idx}_fill_fail.png"))
        return False


def find_button(frame, texts):
    for t in texts:
        loc = frame.locator(f'button:has-text("{t}")').first
        if loc.count() > 0:
            return loc
        loc2 = frame.get_by_text(t, exact=True).first
        if loc2.count() > 0:
            return loc2
    return None


def click_button_force(frame, texts, idx, label):
    pause_video(frame)
    # 方案 A: JS 查找、居中滚动并点击
    for t in texts:
        try:
            clicked = frame.evaluate(
                """(text) => {
                    const btns = [...document.querySelectorAll('button, div[role="button"], a')];
                    const b = btns.find(x => x.textContent.trim() === text || x.textContent.trim().includes(text));
                    if (b) {
                        b.scrollIntoView({behavior: 'instant', block: 'center'});
                        b.click();
                        return true;
                    }
                    return false;
                }""",
                t,
            )
            if clicked:
                logging.info("[%s] 已通过 JS 点击%s: %s", idx, label, t)
                return True
        except Exception as e:
            logging.warning("[%s] JS 点击%s异常: %s", idx, label, e)

    # 方案 B: Playwright locator 回退
    btn = find_button(frame, texts)
    if not btn:
        return False
    try:
        btn.scroll_into_view_if_needed()
        frame.wait_for_timeout(300)
        btn.click(force=True, timeout=12000)
        logging.info("[%s] 已点击%s", idx, label)
        return True
    except Exception as e:
        logging.warning("[%s] 点击%s失败: %s", idx, label, e)
        return False


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

    # 尝试打开发布页（重试防 net::ERR_ABORTED）
    nav_ok = False
    for attempt in range(3):
        try:
            page.goto(POST_URL, wait_until="domcontentloaded", timeout=30000)
            nav_ok = True
            break
        except Exception as e:
            logging.warning("[%s] 打开发布页第 %d 次提示: %s，等待重试...", idx, attempt + 1, e)
            page.wait_for_timeout(3000)
    if not nav_ok:
        logging.error("[%s] 无法打开发布页", idx)
        return False

    page.wait_for_timeout(2000)
    frame = get_content_frame(page)
    if not frame:
        page.screenshot(path=str(SHOT_DIR / f"{idx}_no_frame.png"))
        logging.error("[%s] 找不到发布表单 iframe", idx)
        return False
    logging.info("[%s] 已进入发布 iframe: %s", idx, frame.url[:80])

    # 1. 上传视频（等 file input 挂载）
    file_input = None
    for loc in [
        page.locator('input[type="file"][accept*="video"]').first,
        frame.locator('input[type="file"][accept*="video"]').first,
        page.locator('input[type="file"]').first,
        frame.locator('input[type="file"]').first,
    ]:
        try:
            loc.wait_for(state="attached", timeout=30000)
            file_input = loc
            break
        except Exception:
            continue
    if not file_input:
        page.screenshot(path=str(SHOT_DIR / f"{idx}_no_file_input.png"))
        logging.error("[%s] 找不到文件上传 input", idx)
        return False
    try:
        file_input.set_input_files(str(video_path))
    except Exception as e:
        logging.error("[%s] 上传视频失败: %s", idx, e)
        return False
    logging.info("[%s] 视频已提交上传，等待转码...", idx)

    # 等保存草稿按钮从 disabled 变可用（iframe 内判断）
    try:
        frame.wait_for_function(
            "() => { const b = [...document.querySelectorAll('button')].find("
            "x => x.textContent.trim() === '保存草稿' && x.offsetParent !== null);"
            " return !!b && !b.classList.contains('weui-desktop-btn_disabled'); }",
            timeout=180000,
        )
        logging.info("[%s] 转码完成，按钮就绪", idx)
    except Exception:
        logging.warning("[%s] 保存草稿按钮长时间未就绪，继续尝试填表", idx)

    # ★ 关键修复：暂停 + 静音 iframe 内自动播放的视频，释放焦点
    n = pause_video(frame)
    frame.wait_for_timeout(800)
    logging.info("[%s] 已暂停 iframe 内自动播放视频（%d 个）", idx, n)

    # 填描述
    text = f"{title}\n{topic}" if (title and topic) else (title or topic)
    if text:
        fill_description(page, frame, text, idx)

    # 短标题
    if short_title:
        try:
            filled_st = frame.evaluate(
                """(val) => {
                    const el = document.querySelector('input[placeholder*="短标题"]');
                    if (el) {
                        el.scrollIntoView({block: 'center'});
                        el.focus();
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, val);
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                    return false;
                }""",
                short_title,
            )
            if filled_st:
                logging.info("[%s] 已填短标题: %s", idx, short_title)
            else:
                st = frame.locator('input[placeholder*="短标题"]').first
                if st.count() > 0:
                    st.scroll_into_view_if_needed()
                    st.fill(short_title, timeout=8000)
                    logging.info("[%s] 已填短标题", idx)
        except Exception as e:
            logging.warning("[%s] 填短标题失败: %s", idx, e)

    # 合集
    if collection:
        col = frame.locator('input[placeholder*="合集"]').first
        if col.count() > 0 and col.is_visible():
            try:
                col.fill(collection)
                frame.wait_for_timeout(1200)
                opt = frame.get_by_text(collection, exact=True).first
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

    # 原创声明
    if original in ("是", "yes", "1", "true", "Y", "y"):
        try:
            orig_clicked = frame.evaluate(
                """() => {
                    const all = [...document.querySelectorAll('*')];
                    const orig = all.find(e => e.textContent.trim() === '声明原创' && e.children.length === 0);
                    if (orig) {
                        orig.scrollIntoView({block: 'center'});
                        orig.click();
                        return true;
                    }
                    return false;
                }"""
            )
            if orig_clicked:
                frame.wait_for_timeout(1500)
                frame.evaluate(
                    """() => {
                        const all = [...document.querySelectorAll('button, div[role="button"]')];
                        const agree = all.find(e => e.textContent.trim() === '同意');
                        if (agree) { agree.click(); return true; }
                        return false;
                    }"""
                )
                logging.info("[%s] 已声明原创", idx)
            else:
                orig = frame.get_by_text("声明原创", exact=True).first
                if orig.count() > 0:
                    orig.scroll_into_view_if_needed()
                    orig.click()
                    frame.wait_for_timeout(1500)
                    agree = frame.get_by_text("同意", exact=True).first
                    if agree.count() > 0:
                        agree.click()
                    logging.info("[%s] 已声明原创", idx)
        except Exception as e:
            logging.warning("[%s] 声明原创失败: %s", idx, e)

    # 处理可能的「下一步」
    nxt = find_button(frame, ["下一步", "下一步，发表"])
    if nxt:
        logging.info("[%s] 检测到「下一步」按钮，先点击", idx)
        if not click_button_force(frame, ["下一步", "下一步，发表"], idx, "下一步"):
            logging.warning("[%s] 点击下一步失败，尝试直接找保存/发表", idx)
        frame.wait_for_timeout(2000)
        pause_video(frame)

    shot = SHOT_DIR / f"{idx}_before_submit.png"
    page.screenshot(path=str(shot))
    logging.info("[%s] 表单已填好，截图: %s", idx, shot.name)

    if dry_run:
        if click_button_force(frame, ["保存草稿"], idx, "保存草稿"):
            frame.wait_for_timeout(3000)
            logging.info("[%s] 已保存草稿，请到草稿箱改封面/定时后发表", idx)
            return True
        page.screenshot(path=str(SHOT_DIR / f"{idx}_no_draft.png"))
        logging.error("[%s] 找不到/点不动「保存草稿」按钮", idx)
        return False

    if click_button_force(frame, ["发表"], idx, "发表"):
        frame.wait_for_timeout(3000)
        logging.info("[%s] 已点击发表", idx)
        return True
    logging.error("[%s] 找不到/点不动「发表」按钮", idx)
    page.screenshot(path=str(SHOT_DIR / f"{idx}_no_submit.png"))
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
            user_data_dir=str(PROFILE_DIR), headless=False, channel=args.channel or "chrome")
        init_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        init_page.goto(CHANNELS_URL, wait_until="domcontentloaded")
        init_page.wait_for_timeout(2000)
        if not login_state(ctx, init_page):
            logging.error("未检测到登录态，请先运行: python publish.py login")
            ctx.close()
            return
        try:
            init_page.close()
        except Exception:
            pass

        for i, row in enumerate(todo, start=args.start):
            page = ctx.new_page()
            page.on("dialog", lambda d: (d.dismiss() if d.type == "beforeunload" else d.accept()))
            try:
                ok = publish_one(page, row, dry_run=dry_run, idx=i)
            except Exception as e:
                logging.error("[%s] 发布处理异常: %s", i, e)
                ok = False
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            if status_col:
                if ok:
                    row[status_col] = "待确认" if dry_run else "已发布"
                else:
                    row[status_col] = "失败"
            save_csv(csv_path, header, rows)
            time.sleep(3)

        ctx.close()
    logging.info("完成。日志: %s", logfile)


def main():
    ap = argparse.ArgumentParser(description="视频号助手批量发布脚本")
    ap.add_argument("command", choices=["login", "publish", "check", "check-online"])
    ap.add_argument("--csv", help="排期表路径（默认本目录 schedule.csv）")
    ap.add_argument("--channel", help="浏览器 channel（默认 chrome）")
    ap.add_argument("--timeout", type=int, default=180, help="登录等待秒数（默认 180）")
    ap.add_argument("--start", type=int, default=1, help="从第 N 条开始（断点续跑）")
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理 N 条（0=全部）")
    ap.add_argument("--auto", action="store_true", help="全自动点「发表」（默认 HITL 停在发表前）")
    args = ap.parse_args()
    if args.command == "login":
        cmd_login(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "check-online":
        cmd_check_online(args)
    else:
        cmd_publish(args)


if __name__ == "__main__":
    main()
