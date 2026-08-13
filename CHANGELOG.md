# 变更记录

## V5

- 收紧 Feishu 推送策略为 BUY-only：只有 `FINAL_ACTION=BUY` 才发送实时消息；`WAIT`、`WATCH`、`AVOID`、`ADD`、`EXIT` 和普通每日总结暂不推送。
- BUY 消息改为固定结构，必须说明“为什么现在可以买”，并包含至少3条结构化买入理由、触发条件、资金确认、技术位置、催化剂、已确认事实/系统推断/暂无法验证、买入计划、风险、失效条件和一句总结。
- 在远端 V4 生产工程基础上接入 V5 Trade Filter Layer，保留原有 Provider、Scanner、Feishu、state 和 GitHub Actions。
- 新增 Noise Filter、Market Impact Engine、Price Reaction Analyzer、Entry Timing Engine、Risk Reward Engine、Trade Grade、Final Action Resolver、Early Opportunity Detector、V5 Feishu Formatter 和 Alert Filtering。
- 建立唯一最终动作 `FINAL_ACTION`：`WAIT_FOR_PULLBACK` 不得生成 `BUY`，`DO_NOT_CHASE` 不得生成 `BUY`，`NO_TRADE_VALUE` 不得生成 `BUY`，只有 `ENTRY_CONFIRMED` 且风控通过才允许 `BUY`。
- 实时、新闻、财报/SEC、宏观模式统一进入 V5 过滤；旧 V4 模块不得绕过 `FINAL_ACTION` 直接发送买入信号。
- 新增 V5 dry-run 矩阵、生产集成测试和 config validator 决策链校验。
- GitHub Actions 显示名称升级为 Investment OS V5，触发频率保持不变。

## V4

- 将实时、新闻、财报SEC、宏观、每日汇总和回测拆分为独立频率工作流。
- 新增跨工作流稳定 event_id、事件补充、统一状态缓存和技术性去重。
- 新增可配置产业链图谱和最多50个标的候选池。
- 新增Alpha Finder，区分补涨、弱势未涨和已充分定价。
- 新增资金流代理、Provider状态和数据质量体系。
- 新增股票/周期股/BTC估值与同行比较。
- 新增可配置综合评分、六类排行榜和V4决策矩阵。
- 同轮同资产飞书消息合并；保留全量观察模式。
- 每日汇总加入早期判断对照和错误记录。
- 新增无前视历史回放、报告和手动Actions工作流。
- LLM加入结构、长度、枚举、事实引用和失败回退校验。

## V3

- 实时行情、新闻、产业链、机会、风险、未来事件、决策中心、飞书和每日汇总。
