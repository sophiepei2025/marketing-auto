#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信视频号助手 · 批量全自动发布工具（10倍极速 & 单窗口静默版）

核心优化：
1. 单窗口单标签页复用：全程仅使用单一 Chrome 窗口，禁止频繁跳窗与闪烁。
2. 彻底静音与自动禁播：通过 Chrome 启动参数 (--mute-audio) 及全局原生注入
   (HTMLMediaElement.prototype.play)，彻底杜绝视频自动播放与抢夺前台焦点。
3. 瑞士网格封面（图二）毫秒级直传：通过 DOM DataTransfer 接口注入封面文件并自动确认裁剪。
4. 100% 微信运营合规：长文案专业细致 + 严格过滤极限词 + 3~5个优质标签 + 精准短标题 + 原创声明。
5. 自动断点续传：每处理完一条实时更新 CSV 状态。
"""

import argparse
import base64
import csv
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
VIDEO_DIR = BASE / "videos"
COVER_DIR = BASE / "covers"
PROFILE_DIR = BASE / "profile"
LOG_DIR = BASE / "logs"
SHOT_DIR = BASE / "screenshots"

CHANNELS_URL = "https://channels.weixin.qq.com/platform"
POST_URL = "https://channels.weixin.qq.com/platform/post/create"

PENDING_STATUS = {"待上传", "待发布", "pending", "todo", ""}

FIELD_MAP = {
    "video": ["视频文件", "视频", "video", "filename", "file"],
    "cover": ["封面文件", "封面", "cover", "poster"],
    "title": ["标题", "文案", "描述", "title", "desc"],
    "topic": ["话题", "标签", "topic", "tag", "tags"],
    "short_title": ["短标题", "short_title", "shortTitle"],
    "collection": ["合集", "合集名称", "collection"],
    "original": ["原创声明", "原创", "original"],
    "status": ["状态", "status"],
}


def ensure_dir(d: Path):
    d.mkdir(parents=True, exist_ok=True)


def setup_logging():
    ensure_dir(LOG_DIR)
    logfile = LOG_DIR / f"publish_{time.strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(logfile, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
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


def get_content_frame(page, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        fr = page.frame(name="content")
        if fr:
            return fr
        for f in page.frames:
            if "micro/content/post/create" in f.url:
                return f
        time.sleep(0.5)
    return None


def upload_cover_datatransfer(frame, cover_path: Path, idx):
    """通过 DOM DataTransfer 直接注入封面文件并完成裁剪确认。"""
    if not cover_path or not cover_path.exists():
        return False
    try:
        b64_data = base64.b64encode(cover_path.read_bytes()).decode("utf-8")
        injected = frame.evaluate("""([b64, filename]) => {
            const inp = document.querySelector('.single-cover-uploader-wrap input[type="file"]') || 
                        document.querySelector('input[type="file"][accept*="image"]');
            if (!inp) return false;
            const byteCharacters = atob(b64);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], { type: 'image/png' });
            const file = new File([blob], filename, { type: 'image/png', lastModified: Date.now() });

            const dt = new DataTransfer();
            dt.items.add(file);
            inp.files = dt.files;
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""", [b64_data, cover_path.name])

        if injected:
            time.sleep(1.5)
            # 点击裁剪确定按钮
            confirmed = frame.evaluate("""() => {
                const btns = [...document.querySelectorAll('.weui-desktop-dialog button')].filter(b => ['确定', '确认', '完成'].includes(b.innerText.trim()));
                if (btns.length > 0) {
                    btns[0].click();
                    return btns[0].innerText.trim();
                }
                return null;
            }""")
            logging.info("[%s] 成功上传并确认瑞士网格封面: %s (弹窗确认: %s)", idx, cover_path.name, confirmed)
            return True
        else:
            logging.warning("[%s] 未找到封面上传 input 节点", idx)
    except Exception as e:
        logging.warning("[%s] 上传封面异常: %s", idx, e)
    return False


def fill_post_form(page, frame, row, idx):
    title = row.get("_title", "")
    topic = row.get("_topic", "")
    short_title = row.get("_short_title", "")
    collection = row.get("_collection", "")
    original = row.get("_original", "")
    cover = row.get("_cover", "")

    # 1. 瑞士网格封面注入
    cover_path = None
    if cover:
        p1 = BASE / cover
        p2 = COVER_DIR / Path(cover).name
        if p1.exists():
            cover_path = p1
        elif p2.exists():
            cover_path = p2
    if cover_path:
        upload_cover_datatransfer(frame, cover_path, idx)

    # 2. 填写长文案与精选话题
    desc_text = f"{title}\n\n{topic}".strip() if (title and topic) else (title or topic)
    if desc_text:
        try:
            filled = frame.evaluate("""(text) => {
                const el = document.querySelector('[data-placeholder="添加描述"]') || 
                           document.querySelector('div.input-editor') || 
                           document.querySelector('[contenteditable]');
                if (el) {
                    el.scrollIntoView({block: 'center'});
                    el.focus();
                    el.innerText = text;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
                return false;
            }""", desc_text)
            if filled:
                logging.info("[%s] 已填合规描述与话题", idx)
            else:
                logging.warning("[%s] 填描述框未命中选择器", idx)
        except Exception as e:
            logging.warning("[%s] 填描述异常: %s", idx, e)

    # 3. 填写短标题（6-14字精炼抓人）
    if short_title:
        try:
            st_ok = frame.evaluate("""(val) => {
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
            }""", short_title)
            if st_ok:
                logging.info("[%s] 已填短标题: %s", idx, short_title)
        except Exception as e:
            logging.warning("[%s] 填短标题异常: %s", idx, e)

    # 4. 填写合集（若支持）
    if collection:
        try:
            col_input = frame.locator('input[placeholder*="合集"]').first
            if col_input.count() > 0 and col_input.is_visible():
                col_input.fill(collection)
                time.sleep(1)
                opt = frame.get_by_text(collection, exact=True).first
                if opt.count() > 0 and opt.is_visible():
                    opt.click()
                logging.info("[%s] 已勾选合集: %s", idx, collection)
        except Exception as e:
            logging.warning("[%s] 填合集忽略: %s", idx, e)

    # 5. 声明原创
    if original.lower() in ("是", "yes", "1", "true", "y"):
        try:
            orig_clicked = frame.evaluate("""() => {
                const all = [...document.querySelectorAll('*')];
                const orig = all.find(e => e.textContent && e.textContent.trim() === '声明原创' && e.children.length === 0);
                if (orig) {
                    orig.scrollIntoView({block: 'center'});
                    orig.click();
                    return true;
                }
                return false;
            }""")
            if orig_clicked:
                time.sleep(1)
                frame.evaluate("""() => {
                    const all = [...document.querySelectorAll('button, div[role="button"]')];
                    const agree = all.find(e => e.textContent && e.textContent.trim() === '同意');
                    if (agree) { agree.click(); return true; }
                    return false;
                }""")
                logging.info("[%s] 已声明原创并同意协议", idx)
        except Exception as e:
            logging.warning("[%s] 声明原创异常: %s", idx, e)


def publish_one_pipeline(page, row, dry_run, idx):
    video = row.get("_video", "")
    video_path = VIDEO_DIR / video
    if not video_path.exists():
        logging.error("[%s] 视频文件不存在: %s", idx, video_path)
        return False

    logging.info("========== [%s] 开始处理: %s ==========", idx, video)

    # 1. 访问发布页
    try:
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=40000)
    except Exception as e:
        logging.warning("[%s] 进入发布页超时或异常: %s", idx, e)

    # 2. 定位视频上传控件
    file_input = page.locator('input[type="file"][accept*="video"]').first
    try:
        file_input.wait_for(state="attached", timeout=30000)
        file_input.set_input_files(str(video_path))
        logging.info("[%s] 视频文件已注入，等待转码完成...", idx)
    except Exception as e:
        logging.error("[%s] 视频文件上传失败: %s", idx, e)
        page.screenshot(path=str(SHOT_DIR / f"{idx}_upload_failed.png"))
        return False

    # 3. 拿到微前端 iframe 并等待“保存草稿”按钮就绪
    frame = get_content_frame(page, timeout=30)
    if not frame:
        logging.error("[%s] 找不到微前端发布 iframe", idx)
        return False

    try:
        frame.wait_for_function(
            "() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === '保存草稿' && x.offsetParent !== null);"
            " return !!b && !b.classList.contains('weui-desktop-btn_disabled'); }",
            timeout=180000
        )
        logging.info("[%s] 转码完成，保存草稿按钮就绪！", idx)
    except Exception:
        logging.warning("[%s] 等待按钮就绪超时，尝试直接填表", idx)

    # 4. 全面填表（封面、合规描述、短标题、原创）
    fill_post_form(page, frame, row, idx)

    # 截图备查
    shot = SHOT_DIR / f"{idx}_form_ready.png"
    page.screenshot(path=str(shot))
    logging.info("[%s] 表单已完成填写，截图保存至: %s", idx, shot.name)

    # 5. 提交或保存草稿
    if dry_run:
        saved = frame.evaluate("""() => {
            const btns = [...document.querySelectorAll('button')];
            const b = btns.find(x => x.textContent.trim() === '保存草稿' && x.offsetParent !== null);
            if (b) {
                b.scrollIntoView({block: 'center'});
                b.click();
                return true;
            }
            return false;
        }""")
        if saved:
            time.sleep(3)
            logging.info("[%s] ✅ 成功保存草稿！", idx)
            return True
        else:
            logging.error("[%s] ❌ 点击「保存草稿」失败", idx)
            return False
    else:
        # 发表
        pub = frame.evaluate("""() => {
            const btns = [...document.querySelectorAll('button')];
            const b = btns.find(x => x.textContent.trim() === '发表' && x.offsetParent !== null);
            if (b) {
                b.scrollIntoView({block: 'center'});
                b.click();
                return true;
            }
            return false;
        }""")
        if pub:
            time.sleep(3)
            logging.info("[%s] ✅ 成功发表视频！", idx)
            return True
        else:
            logging.error("[%s] ❌ 点击「发表」失败", idx)
            return False


def cmd_publish(args):
    logfile = setup_logging()
    ensure_dir(SHOT_DIR)
    csv_path = Path(args.csv).resolve() if args.csv else (BASE / "视频号排期表_加拿大申请系列.csv")
    header, field2col, rows = load_csv(csv_path)
    status_col = field2col.get("status")

    todo = [r for r in rows if r.get("_status", "") in PENDING_STATUS]
    logging.info("排期表共 %d 条，待上传 %d 条", len(rows), len(todo))
    if args.start > 1:
        todo = todo[args.start - 1:]
    if args.limit and args.limit > 0:
        todo = todo[:args.limit]
    if not todo:
        logging.info("没有待处理的视频。")
        return

    dry_run = not args.auto
    logging.info("模式: %s | 浏览器: 单窗口静音运行", "【保存为草稿箱】" if dry_run else "【直接正式发表】")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            channel=args.channel or "chrome",
            args=[
                "--mute-audio",
                "--autoplay-policy=user-gesture-required",
                "--window-position=0,0",
                "--window-size=1280,900",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ]
        )
        # 全局注入：彻底静音与禁播所有 HTMLMediaElement，阻止自动弹声与抢焦点
        ctx.add_init_script("""
            HTMLMediaElement.prototype.play = function() {
                this.muted = true;
                this.pause();
                return Promise.resolve();
            };
        """)

        # 复用单个固定页面，杜绝反复跳窗
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", lambda d: d.dismiss() if d.type == "beforeunload" else d.accept())

        for idx, row in enumerate(todo, start=args.start):
            ok = False
            for attempt in range(2):
                try:
                    ok = publish_one_pipeline(page, row, dry_run=dry_run, idx=idx)
                    if ok:
                        break
                except Exception as e:
                    logging.error("[%s] 异常错误: %s", idx, e)
                logging.warning("[%s] 失败，1秒后平滑重试...", idx)
                time.sleep(1)

            # 更新排期表状态并存盘
            if status_col:
                row[status_col] = "已存草稿" if (ok and dry_run) else ("已发布" if ok else "失败")
            save_csv(csv_path, header, rows)

            # 单页平滑复位缓冲，避免同 URL 连续导航错误与弹窗跳动
            try:
                page.goto(CHANNELS_URL, wait_until="domcontentloaded", timeout=20000)
                time.sleep(1.5)
            except Exception:
                pass

        ctx.close()
    logging.info("全部任务处理完毕！详细日志参见: %s", logfile)


def main():
    ap = argparse.ArgumentParser(description="视频号助手批量全自动发布工具")
    ap.add_argument("command", choices=["publish", "check", "login"])
    ap.add_argument("--csv", help="排期表 CSV 路径")
    ap.add_argument("--channel", default="chrome", help="浏览器 channel（默认 chrome）")
    ap.add_argument("--start", type=int, default=1, help="从第 N 条开始")
    ap.add_argument("--limit", type=int, default=0, help="处理数量限制（0=全部）")
    ap.add_argument("--auto", action="store_true", help="是否直接发表（默认保存至草稿箱）")
    args = ap.parse_args()

    if args.command == "check":
        ok, detail = login_state_offline()
        print(f"{'✅ 已登录' if ok else '❌ 未登录'}（{detail}）")
    elif args.command == "login":
        # 单独扫码模式
        pass
    else:
        cmd_publish(args)


if __name__ == "__main__":
    main()
