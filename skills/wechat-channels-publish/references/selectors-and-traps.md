# 选择器候选表 & 四轮排查实录

视频号助手是 wujie 微前端架构，页面会改版。下面是实战中确认过的结构与坑，改版后照着这张表排查。

## 关键 URL

| 用途 | URL |
|------|-----|
| 后台首页 | `https://channels.weixin.qq.com/platform` |
| **发布页（直接进）** | `https://channels.weixin.qq.com/platform/post/create` |
| 草稿箱 | `https://channels.weixin.qq.com/platform/post/draft` |

**首页没有「发表」入口** —— 这是第一轮排查最大的误判来源。别找它，直接 goto 发布页。

## 选择器候选表

| 元素 | 首选 | 备选 | 备注 |
|------|------|------|------|
| 描述框 | `[data-placeholder="添加描述"]` | `div.input-editor` → `[contenteditable]` | 在 `micro/content/post/create` iframe 内，JS 注入优先 |
| 视频上传 | `input[type="file"][accept*="video"]` | `input[type="file"]` | 用 `wait_for(state="attached")`，iframe/main frame 兼容 |
| 短标题 | `input[placeholder*="短标题"]` | — | JS 注入或 `scroll_into_view_if_needed()` 后 `fill()` |
| 合集 | `input[placeholder*="合集"]` | — | **默认折叠**，不可见就跳过 |
| 原创声明 | `get_by_text("声明原创", exact=True)` | JS 节点文本匹配 | 滚动至视口正中后点击，再等弹「同意」 |
| 保存草稿 | `button:has-text("保存草稿")` | JS 按钮匹配 | 需滚动至居中可视区，或用 JS `b.click()` 触发 |
| 发表 | `get_by_text("发表", exact=True)` | `button:has-text("发表")` | 仅 `--auto` 用 |
| 头像/账号 | `[class*="avatar"]` `[class*="profile-img"]` `[class*="user-info"]` | — | 登录态信号之一 |

## 诊断脚本

页面改版、卡住、元素找不到时，用这个一次性把页面结构打出来：

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir="profile/", headless=False, channel="chrome")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://channels.weixin.qq.com/platform/post/create")
    page.wait_for_timeout(5000)

    print("URL:", page.url)
    print("输入框总数:", page.locator("input").count())
    print("文件 input:", page.locator('input[type="file"]').count())
    print("contenteditable:", page.locator("[contenteditable]").count())
    print("按钮总数:", page.locator("button").count())

    for i in range(min(page.locator("button").count(), 120)):
        b = page.locator("button").nth(i)
        try:
            t = (b.text_content() or "").strip()
            if t:
                print(f"  button[{i}]: {t!r}")
        except Exception:
            pass

    # shadow DOM 里到底有没有东西？
    print("shadow hosts:", page.evaluate(
        "() => [...document.querySelectorAll('*')]"
        ".filter(e => e.shadowRoot).map(e => e.tagName + '.' + e.className)"))

    page.screenshot(path="diag.png", full_page=True)
    ctx.close()
```

## 四轮排查实录（真实踩坑顺序）

### 第 1 轮：找不到「发表」入口
- **现象**：脚本在首页找 `text=发表`，永远超时
- **诊断**：把首页所有 button 文本打出来 → 根本没有「发表」
- **结论**：发布页要**直接 goto `/platform/post/create`**

### 第 2 轮：shadow DOM 空空如也
- **现象**：怀疑表单在 wujie 微前端的 shadow root 里，Playwright 常规选择器穿不透
- **诊断**：打印所有 `shadowRoot` 宿主 → 只有一个 input-editor 在主文档
- **结论**：**表单在主 document**，别去 shadow DOM 里找

### 第 3 轮：文件 input count == 0
- **现象**：`page.locator('input[type="file"][accept*="video"]').count()` 返回 0
- **诊断**：发布页是 SPA，异步渲染，元素还没挂载
- **结论**：`wait_for(state="attached", timeout=30000)`，**不要**用固定 sleep

### 第 4 轮：上传后找不到描述框
- **现象**：先上传视频，再去找描述框 → 找不到
- **诊断**：上传动作触发页面重渲染，之前拿到的 Locator 失效
- **结论**：**先定位描述框，再上传**。顺序反了必翻车。

### 第 5 轮：表单迁入微前端 iframe 与视频自动播放遮罩
- **现象**：新版发布表单整体挂载在 `<iframe name="content">` 内（URL 含 `micro/content/post/create`），main frame 查不到描述框与按钮；同时视频上传后在 iframe 内自动播放（多个 `<video>` 元素），盖住输入焦点引发超时。
- **诊断**：诊断脚本遍历 `page.frames`，发现真实表单在 `micro/content/post/create` 内，且 iframe 中渲染了多个 autoplay video。
- **结论**：所有发布交互（输入框、原创声明、保存按钮）必须在 `frame` 内执行，并在填表前用 JS 暂停并静音所有 `<video>`（`pause()` + `muted = true` + `pointerEvents='none'`），且描述框使用 JS 原型属性描述符注入（`HTMLTextAreaElement/HTMLInputElement.prototype` 或 `innerText`）绕过遮罩。

### 第 6 轮：同页面连续跳转引发 net::ERR_ABORTED
- **现象**：批量发布时，第一条成功存为草稿，从第二条开始 `page.goto(POST_URL)` 报 `Page.goto: net::ERR_ABORTED`。
- **诊断**：草稿保存后页面处于单页 SPA 内部状态，再次直接在同一 `page` 对象上调用 `goto` 相同 URL 遭到 Chromium 拦截中止。
- **结论**：采用**独立标签页生命周期架构**，每条视频用 `page = ctx.new_page()` 单独处理，存完草稿在 `finally` 中执行 `page.close()`。彻底实现每条视频隔离，杜绝页面缓存与导航冲突。

## 时序参考（10 条视频实测）

| 阶段 | 耗时 |
|------|------|
| 打开发布页 | ~3–5 秒 |
| 视频上传提交 | ~2 秒 |
| **转码（等保存草稿解禁）** | **2–4 分钟** ⬅️ 最长的一步 |
| 填表 + 原创弹窗 | ~10 秒 |
| 存草稿 | ~3 秒 |

10 条串行总耗时 ≈ 30–45 分钟。建议后台跑 + `run_in_background`，别在前台等。

## 沙箱 / 环境坑

| 现象 | 原因 | 解法 |
|------|------|------|
| `ModuleNotFoundError: playwright` | 没用 managed venv | 用 `~/.workbuddy/binaries/python/envs/default/bin/python` |
| playwright chromium 安装失败 | `broker denied delete` / dirlock | 改系统 Chrome：`channel="chrome"` |
| `PermissionError: EEXIST` on mkdir | 沙箱里对已存在目录 mkdir | `if not path.exists(): path.mkdir(parents=True, exist_ok=True)` |
| `ps` operation not permitted | 沙箱限制 | 用 `pgrep` / `lsof` |
| Chrome 报 code_sign_clone 删除失败 | macOS 沙箱噪音 | 忽略，实际任务已完成 |

## 登录态检测（别再用文本判断）

```python
# ✅ 最稳：离线读 cookie 库，零浏览器、零等待
import sqlite3, shutil, tempfile
from pathlib import Path
db = Path("profile/Default/Cookies")
tmp = tempfile.mktemp(suffix=".db"); shutil.copy(db, tmp)
con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
rows = con.execute(
    "SELECT host_key, name FROM cookies WHERE host_key LIKE '%channels.weixin.qq.com%'"
).fetchall()
cred = [n for _, n in rows
        if any(k in n.lower() for k in ("ticket","session","uin","skey","token","login"))]
print("已登录" if cred else "未登录", cred)
```

要点：**cookie 的 name/host_key 是明文的**（只有 value 加密），所以只看名字就够判断登录态。
**必须先复制再读** —— 直接连原库可能被 Chrome 锁住。

在线复核（会开浏览器，可能因系统 Chrome 抢占而长时间挂起，慎用）：

```python
has_cred = any(any(k in c["name"].lower()
                    for k in ("ticket","session","uin","skey","token","login"))
                for c in ctx.cookies("https://channels.weixin.qq.com"))
away_login = "login" not in page.url.lower()
logged_in = has_cred and away_login

# ❌ 错误：首页没有「发表」按钮
find(page, ["text=发表"])
```

登录成功后 `profile/` 里会出现 `wxuin`、`sessionid` 等 cookie，LocalStorage 里会有 `finder_uin`、`finder_username`。**不要把 cookie 明文打印到对话里。**
