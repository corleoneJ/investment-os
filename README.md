# Investment OS 实时监控云端版

这是一个面向小额、长期、现货投资的 GitHub Actions 监控系统。它每 5 分钟扫描一次市场，但**只有触发预警条件时才发送飞书消息**；不再发送固定晨报。每天北京时间 20:05 仍会发送一次汇总。

系统遵守以下纪律：

- 只做现货，不提供合约或杠杆建议。
- 默认参考每日约 10 USDT、每月约 300 USDT 的预算。
- 重点发现重大机会和风险、阻止追高、提醒等待回踩。
- 不把短期波动描述为确定性机会，不使用“必涨”等表述。
- 行情或新闻缺失时明确标记“数据暂不可用”，不编造数据。

## 工作方式

- `.github/workflows/realtime-monitor.yml`
  - 支持手动运行。
  - 使用 `*/5 * * * *` 每 5 分钟调度。
  - 单次任务超时为 2 分钟。
  - 没有命中条件时不会发送飞书消息。
- `.github/workflows/daily-summary.yml`
  - 使用 `5 12 * * *`，即北京时间每天 20:05。
  - 即使当天没有预警，也会发送“今日无重大异常，维持原定定投计划”。
- 两个工作流共用 concurrency 组，避免同时运行并覆盖状态。
- `state/alerts.json` 通过 GitHub Actions cache 在不同运行间恢复和保存；文件本身不会提交到仓库。

> GitHub Actions 是分钟级定时调度，不是秒级实时系统。高负载时可能延迟，`cron` 也不保证恰好在指定分钟开始。

## 数据源

| 数据 | 来源 | 说明 |
| --- | --- | --- |
| BTC 现货 | Binance 公共现货 API | 使用 BTCUSDT 作为 BTC-USD 的近似代理，无需 API Key |
| 美股、QQQ、美元指数代理 | Yahoo Finance 公共图表接口 | 无需 API Key，但可能延迟、限流或临时变更 |
| 公司重大公告/财报 | SEC EDGAR Submissions API | 官方、无需 API Key |
| 美联储事件 | Federal Reserve 官方 RSS | 官方来源 |
| CPI/非农等宏观信息 | BLS 官方 RSS | 官方来源 |
| 财经新闻补充 | Google News RSS | 保留原始媒体来源和链接，只作补充 |

每个网络请求均设置 timeout，并配置 retry/backoff。单个来源失败只会使对应数据降级，不会中止其他资产扫描。

## 配置飞书 Webhook

1. 在飞书群中添加“自定义机器人”，复制 Webhook 地址。
2. 打开 GitHub 仓库的 **Settings → Secrets and variables → Actions**。
3. 新建 Repository secret：
   - 名称：`FEISHU_WEBHOOK`
   - 值：完整的飞书 Webhook
4. 可选：新建 Repository variable `SEC_USER_AGENT`，建议格式为 `项目名/版本 联系邮箱`，用于遵守 SEC 自动访问规范。

Webhook 只从 Secret 环境变量读取。程序不会输出完整 Webhook，也不会记录飞书失败响应正文。未配置时，扫描和测试仍会执行，日志会清晰显示“未配置 FEISHU_WEBHOOK”，发送阶段安全跳过。

## 第一次手动测试

1. 先在本地运行单元测试：

   ```bash
   python -m pip install -r requirements.txt
   pytest -q
   ```

2. 做一次不发送消息的真实数据扫描：

   ```bash
   python -m src.main --mode realtime --dry-run
   ```

3. 推送代码后，打开 GitHub **Actions → Investment OS 实时监控 → Run workflow**。
4. 第一次建议勾选：
   - `仅扫描，不发送飞书消息`：`true`
   - `额外发送一条飞书连通性测试消息`：`false`
5. 确认日志包含扫描时间、资产数量、触发数量、重复跳过数量。
6. 再次手动运行，把 `dry_run` 设为 `false`，并把 `send_test_message` 设为 `true`。飞书应收到一条明确标注“不代表市场预警”的连通性测试消息。
7. 最后将 `send_test_message` 恢复为 `false`。之后仅真实预警条件会触发消息。

也可本地临时设置 Webhook 测试，但不要把地址写入 shell 历史或仓库。更推荐通过 GitHub Secret 测试。

## 修改监控资产

编辑 `config/watchlist.json`。每项包含：

- `symbol`：消息中显示的资产代码。
- `type`：`crypto`、`stock` 或 `etf`。
- `provider_symbol`：可选，行情源代码。
- `cik`：美股公司可选，SEC 的 10 位 CIK，用于官方公告。

新增资产前应确认行情源代码和 CIK，禁止凭猜测填写。

## 修改预警阈值

编辑 `config/thresholds.json`：

- `rapid_rise` / `rapid_fall`：急涨急跌阈值。
- `breakout`：放量倍数和趋势评分。
- `pullback`：EMA20 距离和机会评分。
- `weakening`：RSI 和放量阈值。
- `dedup`：60 分钟冷却及“明显加强”的判定幅度。

调低阈值会显著增加消息量。修改后应先运行 `pytest -q`，再用 workflow 的 `dry_run` 验证。

## 防刷屏规则

- 同一资产、同一预警类型默认 60 分钟不重复。
- 冷却期内只有强度达到“上次的 1.2 倍”且至少增加 1 个强度点才允许再次发送。
- 新闻使用标准化链接（没有链接时使用标题）的 SHA-256 哈希去重。
- 同一新闻仅在飞书发送成功后记为已发送；发送失败不会误吞后续重试。
- 状态保留 14 天预警历史和 30 天新闻哈希，并控制最大历史数量。

## 暂停实时监控

在 GitHub 仓库进入 **Actions → Investment OS 实时监控**，点击右上角菜单并选择 **Disable workflow**。这只暂停实时监控；每日汇总需在 `Investment OS 每日汇总` 中单独停用。

也可以临时删除或注释 workflow 中的 `schedule`，但这需要提交代码。恢复时重新启用 workflow 或恢复 `schedule`。

## 已知限制

- Yahoo Finance 公共接口不是带 SLA 的正式行情服务，可能有约 15 分钟延迟、限流、盘前盘后数据缺口或接口变化；系统使用数据时间和 freshness 检查避免把旧数据当实时数据。
- BTCUSDT 与严格意义上的 BTC-USD 存在稳定币和交易场所价差。
- 免费新闻/RSS 不能保证覆盖所有事件，Google News 的分类只基于标题关键词；消息明确区分事实和推测，并提供来源、时间、链接供核对。
- SEC 的 8-K/10-Q/10-K 只能证明文件已提交，不能仅凭表单类型判断利好或利空。
- 免费源没有稳定、完整的结构化经济日历；每日汇总不会编造“明日事件”，未确认时会明确说明。
- Actions cache 是实用型持久化方案，不等同于数据库；手动清除 cache 后，防重复状态会从空状态重新开始。

## 项目结构

```text
src/main.py              入口与任务编排
src/market_data.py       行情获取与数据时间检查
src/news.py              SEC、官方 RSS、财经新闻
src/indicators.py        EMA、RSI、波动率
src/scoring.py           趋势、机会、风险评分
src/alerts.py            六类预警检测与中文消息
src/state.py             冷却、加强判定、新闻去重
src/feishu.py            飞书安全发送
src/daily_summary.py     北京时间每日汇总
config/watchlist.json    可编辑监控列表
config/thresholds.json   可编辑阈值
```
