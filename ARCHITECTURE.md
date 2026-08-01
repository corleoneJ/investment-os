# V4 架构说明

## 设计原则

V4在V3上增量扩展，保留扫描、未来事件、风险发现、飞书、状态缓存和测试。结构化规则负责数据和评分，LLM只负责受约束的自然语言表达。

## 分层

1. 数据层：`market_data`、`news`、`future_events`、`data_quality`。
2. 解释层：`industry_graph`、V3事件/新闻/风险模块。
3. 研究层：`alpha_finder`、`flow_analyzer`、`valuation_engine`、`peer_comparison`。
4. 决策层：`investment_score`、`ranking`、`v4_engine`。
5. 交付层：`alert_manager`、`daily_summary`、`state`。
6. 验证层：`replay_engine`、`backtest`、配置校验和测试。

每个外部源独立失败降级。Provider元数据贯穿数据质量评分；PLACEHOLDER不参与评分。核心资产全部形成决策，候选池只有Alpha榜中的有意义候选加入消息，同轮按 symbol 去重。

## 安全边界

密钥只从环境变量读取；日志不打印URL Secret、请求头或响应正文。建议枚举固定，规则不支持杠杆、合约和重仓。LLM输出失败不影响规则决策。
