# marketing-auto — 内容运营自动化工具箱

把「加拿大申请系列」这条内容线跑通后沉淀下来的可复用资产：**两个 WorkBuddy skill + 两个自动化工具 + 内容模板**。

```bash
git clone git@github.com:sophiepei2025/marketing-auto.git
```

## 目录

```
skills/
├── wechat-channels-publish/    # 视频号批量发布工作流（主 skill）
│   ├── SKILL.md
│   ├── scripts/publish.py      # 视频号助手 RPA 发布脚本（login / check / publish）
│   ├── scripts/cover_gen.py    # 封面批量生成（Swiss 版式 1080×1260）
│   ├── references/             # 选择器候选表 / 排期表字段 / 封面规格
│   └── assets/                 # 排期表模板 + 封面配置示例
└── mel-robbins-hooks/          # 标题钩子改写方法（视频号 skill 依赖它）

tools/
├── 视频号发布工具/              # publish.py / cover_gen.py / cover_swiss.py
└── 小红书发布工具/              # xhs_publish.py（批量图文）/ mcp_call.py（MCP 客户端）

assets/
├── 视频号排期表_模板.csv
├── 加拿大申请系列_三平台文案.md
└── examples/covers/            # 11 张成品封面示例
```

## 安装 skill

```bash
cp -R skills/wechat-channels-publish ~/.workbuddy/skills/
cp -R skills/mel-robbins-hooks ~/.workbuddy/skills/
```

之后在 WorkBuddy 里说「发视频号」「批量上传视频号视频」就会自动触发。

## 快速上手

```bash
# 1. 建项目目录
mkdir -p 视频号发布工具/{videos,logs,screenshots}
cp tools/视频号发布工具/publish.py 视频号发布工具/
cp assets/视频号排期表_模板.csv 视频号排期表_新批次.csv

# 2. 登录（可见窗口扫码，登录态存进 profile/）
cd 视频号发布工具 && python publish.py login

# 3. 检查登录态（秒回，不碰浏览器）
python publish.py check

# 4. 批量上传并存草稿（默认不发表，人工改封面/定时后自己发）
python publish.py publish --csv ../视频号排期表_新批次.csv
```

断点续跑：`--start N` / `--limit N`。

## 核心设计取舍

| 决策 | 原因 |
|------|------|
| **默认存草稿，不自动发表** | 平台风控 + 封面/定时必须人工确认 |
| **登录态检测用离线读 cookie 库** | 不启动浏览器、不刷新页面，秒回且不会打断任何在跑的浏览器会话 |
| **直接 goto 发布页，不从首页找入口** | 视频号首页**根本没有**「发表」按钮 |
| **先定位描述框，再上传视频** | 上传触发页面重渲染，顺序反了必翻车 |
| **封面用 HTML + Playwright 截图** | 中文不糊、版式可精确控制、文案可脚本化改 |

## 踩坑实录

四轮排查的完整过程（首页无发表入口 / 表单在主文档不在 shadow DOM / SPA 异步渲染 / 上传后定位失效）见
`skills/wechat-channels-publish/references/selectors-and-traps.md`。

## 合规

- 视频号**没有**面向普通创作者的公开发布 API，本方案走浏览器自动化官方网页，属平台规范边界。
- 默认 HITL，`--auto` 全自动发表风险自担（限流/封号）。
- `profile/` 与 `cookies.json` 含登录凭据，**已加入 .gitignore，绝不入库**。
- 不要高频密集发布。

## 小红书

`tools/小红书发布工具/` 基于 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)：

```bash
# 服务端（二进制在 ~/.local/bin/）
~/.local/bin/xiaohongshu-mcp -port ":18060"          # 无头，适合批量
~/.local/bin/xiaohongshu-mcp -port ":18060" -headless=false   # 可见窗口，用于扫码

# 批量图文（默认「仅自己可见」= 先不发，人工检查后再转公开）
python xhs_publish.py check
python xhs_publish.py run
```

登录态会写到 `~/cookies.json`，**重启服务免扫码**。
注意：`check_login_status` 会驱动浏览器导航，长轮询会导致页面反复刷新 —— 检测登录请读 `~/cookies.json`。

### 已知问题：publish_content 超时 panic

v2.2.6 在发布图文时可能报 `context deadline exceeded`，堆栈落在
`publish.go:144 mustClickPublishTab` —— 原因是 MCP 内置 Chromium 打开
`creator.xiaohongshu.com/publish/publish` 后找不到「上传图文」标签页（5 分钟超时）。

处置顺序：
1. 确认 `~/cookies.json` 里 `web_session` / `access-token-creator` 齐全且 `saved_at` 是近期
2. 用 `-headless=false` 起服务，在可见窗口里手动进一次发布页完成初始化（Cookie 落盘后无头也认）
3. 单条试发（`xhs_publish.py run --limit 1`），成功后再跑全量

不要用高频轮询去"探活"，每次 `check_login_status` 都会触发页面导航，把正在排队的发布页切走。
