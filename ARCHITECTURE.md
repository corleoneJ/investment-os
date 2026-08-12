# V5 架构说明

## 设计原则

V5 在远端 V4 生产工程上增量集成，不推倒重写。V4 继续负责公开数据采集、新闻/SEC/宏观扫描、基础评分、每日汇总、Feishu 和状态缓存；V5 负责把实时交易提醒统一过滤为唯一最终动作 `FINAL_ACTION`。

结构化规则负责数据、评分和动作解析，LLM只负责受约束的自然语言表达。任何模块都不得绕过 V5 Final Action Resolver 直接生成买入推送。

## 分层

1. 数据层：`market_data`、`news`、`future_events`、`data_quality`。
2. 解释层：`industry_graph`、V3事件/新闻/风险模块。
3. 研究层：`alpha_finder`、`flow_analyzer`、`valuation_engine`、`peer_comparison`。
4. V4决策层：`investment_score`、`ranking`、`v4_engine`。
5. V5过滤层：`noise_filter`、`market_impact_engine`、`price_reaction`、`entry_timing`、`risk_reward`、`trade_grade`、`final_action`、`trade_filter_layer`、`alert_filtering`。
6. 生产桥接层：`v5_production` 将 V4 数据对象转换为 V5 `TradeContext`，并统一通过 `TradeFilterLayer` 生成 `FINAL_ACTION`。
7. 交付层：`feishu_signal_formatter`、`daily_summary`、`state`。
8. 验证层：`replay_engine`、`backtest`、配置校验、V5 dry-run 和测试。

每个外部源独立失败降级。Provider元数据贯穿数据质量评分；PLACEHOLDER不参与评分。核心资产全部形成决策，候选池只有Alpha榜中的有意义候选加入消息，同轮按 symbol 去重。

## 分频调度与事件状态

实时行情每5分钟只覆盖高优先级资产；公司新闻每10分钟、财报SEC每30分钟、宏观每小时采集。V5 保留这些调度频率，但所有实时飞书交易信号必须经过 `V5ProductionBridge`：

```text
Provider / Scanner
→ V4 数据分析
→ V5 TradeFilterLayer
→ FINAL_ACTION
→ Alert Filtering / StateStore
→ V5 Feishu Formatter
```

事件以规范化来源链接、类型和时间生成稳定 `event_id`。不同工作流可补充同一记录，`notified=true` 后不因另一个工作流再次发现而重复发送。单轮新事件合并为一条飞书消息；状态由 Actions cache 跨运行恢复。

## FINAL_ACTION 规则

- `WAIT_FOR_PULLBACK` → `WAIT`，禁止 `BUY`。
- `DO_NOT_CHASE` → `WAIT` 或 `AVOID`，禁止 `BUY`。
- `NO_TRADE_VALUE` → `AVOID`，禁止 `BUY`。
- 只有 `ENTRY_CONFIRMED` 且资金、技术、风险收益比和风险条件通过时才允许 `BUY`。
- 机会等级 `S/A/B/C` 与入场动作解耦；`S` 只代表高质量机会，不代表现在可以买。

## 安全边界

密钥只从环境变量读取；日志不打印URL Secret、请求头或响应正文。建议枚举固定，规则不支持杠杆、合约和重仓。LLM输出失败不影响规则决策。
