---
name: wechat-channels-publish
display_name: 视频号批量发布｜排期表→上传→存草稿
display_name_en: WeChat Channels batch publish workflow
description: 用 Playwright 驱动官方「视频号助手」网页(channels.weixin.qq.com)，按排期表 CSV 批量上传视频、自动填标题/话题/短标题/原创声明、保存为草稿（默认不发表，留人工改封面和定时）。当用户要发视频号、发视频到视频号助手、批量上传视频号视频、视频号排期、视频号封面、channels.weixin.qq.com 自动化，或提到"视频号发过了吗/帮我发视频号"时使用。
description_zh: 用 Playwright 驱动官方「视频号助手」网页，按排期表 CSV 批量上传视频并填表保存为草稿。
description_en: Drives the official WeChat Channels web console via Playwright to batch-upload videos from a schedule CSV and save them as drafts.
allowed-tools: Bash, Read, Write, Edit
disable-model-invocation: false
user-invocable: true
version: 1.0.0
author: chengyinpei
---

# 视频号批量发布工作流

## 0. 先讲合规（别跳过）

视频号**没有**面向普通创作者的公开上传 API。本 skill 走的是**浏览器自动化**官方网页路径 —— 属平台风控边界。

- **默认必须是 HITL**：自动填表 → **保存草稿** → 人工改封面/定时 → 人工点发表。
- `--auto` 全自动发表风险自担（限流/封号）。
- `profile/` 里是登录凭据，**不进 git、不发任何人**。
- 不要高频密集发。

## 1. 整体链路

```
排期表 CSV  ──►  视频号助手(Playwright,持久化登录态)
                        │
                        ├─ 上传视频 → 等转码(2–4 分钟)
                        ├─ 填描述(标题+话题) / 短标题 / 合集 / 声明原创
                        ├─ 截图留证
                        └─ 保存草稿   ← HITL 停在这里
                                │
                                ▼
                     草稿箱：人工改封面 + 定时 → 发表
```

## 2. 目录结构（每个项目一份，登录态按项目隔离）

```
<项目>/视频号发布工具/
├── publish.py      # 主脚本（从 scripts/ 复制）
├── videos/         # 视频放这里，文件名 = CSV「视频文件」列
├── profile/        # 登录态（扫码后生成）⚠️ 含凭据
├── logs/           # 运行日志
├── screenshots/    # 每条填表后截图 / 失败诊断
└── ../视频号排期表_*.csv
```

## 3. 四步走

### ① 准备排期表

复制 `assets/schedule_template.csv`，字段见 `references/schedule-table.md`。
编码必须 `utf-8-sig`（Excel 直接打开不乱码）。

### ② 登录（每个项目第一次）

```bash
python publish.py login
```

弹可见窗口 → 手机微信扫码 → 脚本自动检测登录态存进 `profile/`，之后不用再扫。

**检查登录态（安全、秒回、不碰浏览器）**：

```bash
python publish.py check
# ✅ 已登录（凭据 cookie: ['sessionid', 'wxuin']）
```

`check` 直接读 `profile/Default/Cookies` 这个 SQLite 库 —— cookie 的**名字和域名是明文的**（只有 value 加密），所以看到 `sessionid`/`wxuin` 就说明已登录。**不启动浏览器、不刷新任何页面**，随时可跑。

需要严格复核（真开浏览器访问后台）时用 `python publish.py check-online`。

**登录成功的判定**：cookie 里有 `wxuin`/`sessionid` 之类凭据 + URL 已离开 login 页 + 后台出现头像元素。
**不要用「页面上有『发表』按钮」当登录判据** —— 视频号首页根本没有这个入口（见坑位表）。

### ③ 批量上传（HITL）

```bash
python publish.py publish --csv ../视频号排期表_xxx.csv
```

自动上传 + 填表 + **保存草稿**，状态列写 `待确认`。每条填表后截图存 `screenshots/`。

断点续跑：`--start N`（从第 N 条）、`--limit N`（本次只做 N 条）。

### ④ 人工收尾

去视频号助手草稿箱：改封面 → 设定时 → 发表。
封面规格与批量生成见 `references/cover-spec.md`。

## 4. 表单填写顺序（**顺序错了必翻车**）

这一节是整个流程最贵的部分，别自己重排：

```
1. page = ctx.new_page()       ← 每条视频独立标签页，防 net::ERR_ABORTED
2. goto POST_URL              ← 直接进发布页，别从首页点
3. 获取 content iframe         ← micro/content/post/create 微前端容器
4. 等 file input attached     ← SPA 异步渲染，state=attached 不是 visible
5. set_input_files            ← 提交上传
6. 等「保存草稿」按钮解禁      ← 等转码，通常几秒到 2 分钟
7. pause_video(frame)         ← 暂停并静音所有 iframe 内 autoplay 视频，释放焦点
8. 填描述 = 标题 + 换行 + 话题  ← JS 原型属性注入，绕过遮罩
9. 填短标题                   ← 居中滚动后填入
10. 合集（折叠→通常跳过）
11. 声明原创 → 点「同意」       ← 居中滚动后点击
12. 截图留证
13. 点「保存草稿」             ← JS 居中滚动点击，HITL 终点
14. page.close()              ← 关闭本页标签，释放内存与状态
```

## 5. 坑位速查（全部实战踩过）

| 坑 | 现象 | 正解 |
|---|---|---|
| 首页无「发表」入口 | 脚本卡在"找不到发表入口" | 直接 `goto /platform/post/create` |
| 表单渲染在 iframe 内 | main frame 找不到描述框/按钮 | 切到 `micro/content/post/create` 的 `frame` 内操作 |
| 视频自动播放遮罩 | 填表超时、点击被盖住 | 在 iframe 内 JS 暂停并静音所有 `<video>` |
| 描述框点击被阻断 | click 30s 超时 | 使用 JS 原型描述符注入值与 dispatch input 事件 |
| 连续发布 net::ERR_ABORTED | 第 2 条起 goto 立即报错 | 采用**独立标签页**：每条 `ctx.new_page()`，结束后 `page.close()` |
| 按钮在视口下方不可见 | 保存草稿按钮点不动/查不到 | `scrollIntoView({block: 'center'})` 居中后点击 |
| SPA 异步渲染 | `locator.count()==0` | 用 `wait_for(state="attached")`，别用固定 sleep |
| 转码很慢 | "保存草稿按钮长时间未就绪"警告 | 正常，通常几秒到 2 分钟，别中途判失败 |
| 合集填不进去 | input 不可见 | 默认折叠，`is_visible()` 为 false 就跳过，人工补 |
| 登录误判 | 28 秒就报"登录成功"但没扫码 | 用 cookie + URL 两信号，别用文本 |
| Playwright chromium 装不上 | broker denied delete / dirlock | 改用系统 Chrome：`channel="chrome"` |
| 沙箱 mkdir 报 EEXIST | `PermissionError` | `if not path.exists(): path.mkdir(...)` |
| 沙箱 `ps` 被拒 | permission denied | 用 `pgrep`/`lsof` 替代 |

**选择器候选**（页面改版时改这里）：`references/selectors-and-traps.md`

## 6. 状态流转

```
待上传 ──► 待确认（已存草稿，等人工）
   │
   └────► 失败（看 logs/ 和 screenshots/ 排查）
待确认 ──► 已发布（人工在后台发表后手工改）
```

`待上传 / 待发布 / pending / todo / 空` 都视为待处理。

## 7. 三平台联动（可选）

同一条视频要发小红书 / YouTube 时，标题按平台改写（视频号用"标题+话题"、小红书用更短的图文标题、YouTube 用英文 SEO 标题），文案改写方法见 skill `mel-robbins-hooks`。

## 参考文件

- `references/schedule-table.md` — 排期表字段定义 + 状态机 + CSV 生成片段
- `references/selectors-and-traps.md` — 完整选择器候选表、诊断脚本、四轮排查实录
- `references/cover-spec.md` — 视频号封面规格 + 批量生成方法
- `assets/schedule_template.csv` — 排期表模板
- `assets/items_example.json` — 封面生成配置示例
- `scripts/publish.py` — 可直接复制运行的主脚本（`login` / `check` / `publish`）
- `scripts/cover_gen.py` — 通用封面批量生成器（JSON 驱动，Swiss 版式）

## 快速上手（复制到新项目）

```bash
SK=~/.workbuddy/skills/wechat-channels-publish
mkdir -p 视频号发布工具/{videos,logs,screenshots}
cp $SK/scripts/publish.py 视频号发布工具/
cp $SK/assets/schedule_template.csv 视频号排期表_新批次.csv
cd 视频号发布工具 && python publish.py login
python publish.py publish --csv ../视频号排期表_新批次.csv
```

**先跑 `python publish.py check`** 确认登录态，再跑 publish —— 不要靠猜。
