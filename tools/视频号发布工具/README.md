# 视频号批量发布工具

Playwright 驱动官方「视频号助手」网页（channels.weixin.qq.com），实现登录态持久化 + CSV 批量上传填表。

## 目录结构

```
视频号发布工具/
├── publish.py      # 主脚本
├── videos/         # 视频放这里，文件名与排期表「视频文件」列一致
├── profile/        # 登录态（扫码后生成，含敏感凭据，勿提交 git / 勿分享）
├── logs/           # 运行日志
├── screenshots/    # 每条视频填表后的截图（失败诊断用）
└── schedule.csv    # 默认排期表（也可用 --csv 指定已有排期表）
```

## 前置

- Python 3.13 + Playwright 已装好（managed venv），浏览器走系统 Chrome
- 把视频文件复制到 `videos/`，文件名与 CSV「视频文件」列严格一致

## 三步走

### 1. 登录（首次一次）

```bash
python publish.py login
```

弹出浏览器 → 手机微信扫码登录视频号助手 → 登录态自动存进 `profile/`，以后不用再扫。

### 2. 试跑（HITL，推荐）

```bash
python publish.py publish --csv ../视频号排期表_加拿大申请系列.csv
```

自动上传视频 + 填标题/话题，**停在「发表」前**，你人工核对（定时发布/合集/原创）后手动点发表。
每条填表后截图存在 `screenshots/`，状态列标为「待确认」。

### 3. 全自动（风险自担）

```bash
python publish.py publish --csv ../视频号排期表_加拿大申请系列.csv --auto
```

自动点「发表」。状态列标为「已发布」/「失败」。

## 断点续跑

```bash
python publish.py publish --csv ../视频号排期表_加拿大申请系列.csv --start 3
```

从第 3 条开始（失败或中断后继续）。

## 合规与风险

- 视频号**没有**面向普通创作者的公开上传 API，本工具走浏览器自动化，属平台规范风险边界。
- 默认 HITL，强烈建议保留人工确认；`--auto` 请自行评估封号/限流风险。
- `profile/` 登录态含敏感凭据，不要提交 git、不要发给任何人。
- 不要高频密集发布，避免触发风控。

## 选择器微调

视频号助手页面会改版。若某步卡住，看 `logs/` 和 `screenshots/`，编辑 `publish.py` 里 `publish_one()` 中对应 `find(...)` 的候选选择器即可。
