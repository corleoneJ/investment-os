# Investment OS V5：交易决策过滤系统

V5 是一个独立的 Trade Filter Layer，定位不是“多抓新闻”，而是把已有扫描结果继续过滤为少数有交易价值的机会：

```text
Noise Filter
  → Market Impact
  → Price Reaction
  → Entry Timing
  → Risk Reward
  → Trade Grade
  → Final Action Resolver
  → Alert Filtering
  → Feishu Signal Text
```

当前实现位于 `src/`，不会自动下单，不连接交易账户，也不修改现有飞书 webhook。

## 核心原则

系统不能因为有新闻就推送。每个事件必须先回答：

1. 是否可能影响价格。
2. 影响程度有多大。
3. 市场是否已经反应。
4. 是否还有剩余交易空间。
5. 资金是否确认。
6. 技术位置是否合适。
7. 盈亏比是否值得做。
8. 当前应该是 `BUY`、`WATCH`、`WAIT` 还是 `AVOID`。

如果无法确认买入价值，默认 `WAIT`。

## 新增模块

- `src/models.py`：统一 V5 数据对象。
- `src/noise_filter.py`：过滤普通合作、普通产品更新、小金额订单、重复新闻、旧消息、低质量来源等。
- `src/market_impact_engine.py`：计算事件真实影响分数、方向、持续时间和置信度。
- `src/price_reaction.py`：判断价格是否已经提前反应，识别“不追高”。
- `src/entry_timing.py`：严格 BUY Gate，强新闻不能直接 BUY。
- `src/risk_reward.py`：动态止损、目标位和盈亏比。
- `src/trade_grade.py`：输出 S / A / B / C 机会等级。
- `src/early_opportunity.py`：识别 EARLY_ALPHA 补涨机会。
- `src/alert_filtering.py`：基于 decision fingerprint 的智能防轰炸。
- `src/feishu_signal_formatter.py`：生成 V5 飞书交易信号文本。
- `src/trade_filter_layer.py`：把所有 V5 模块串起来。
- `src/v5_dry_run.py`：本地 dry-run 模拟，不发送飞书。

## FINAL_ACTION 与 BUY 逻辑

`FINAL_ACTION` 是唯一最终动作。飞书格式器不得自行推导 BUY / WAIT，只能读取
`FinalActionResolver` 的输出。

优先级：

- `WAIT_FOR_PULLBACK` → `FINAL_ACTION=WAIT` 或 `WATCH`，禁止 BUY。
- `DO_NOT_CHASE` → `FINAL_ACTION=WAIT`，禁止 BUY。
- `NO_TRADE_VALUE` → `FINAL_ACTION=AVOID`，禁止 BUY。
- 只有 `ENTRY_CONFIRMED` 且其他风险条件通过时，才允许 `FINAL_ACTION=BUY`。

机会等级与入场动作彻底解耦：

- `grade=S` 只代表“这是高质量机会”。
- `grade=S` 不代表“现在可以买”。

`BUY` 必须同时满足：

- `Impact Score >= 65`
- `Opportunity Score >= 70`
- `Risk Score <= 60`
- 资金确认
- 技术位置确认
- 当前价格未严重过热
- `Risk Reward >= 2.0`

禁止因为新闻强直接 `BUY`。

## 入场模型

- `WAIT_FOR_PULLBACK`：强事件已确认，但还在等待回踩/技术确认。
- `ENTRY_CONFIRMED`：回踩、突破或反转结构已经确认，交给 Final Action Resolver 做最后 BUY Gate。
- `REVERSAL_WATCH`：基本面未破坏 + 超跌 + 反转结构。
- `DO_NOT_CHASE`：单日涨幅过大、RSI过热、VWAP/ATR偏离过大。

## S / A / B / C 等级

- `S`：Impact ≥ 80、Opportunity ≥ 80、Risk ≤ 50、R/R ≥ 2.5、资金和技术确认、数据质量高。
- `A`：有交易机会，但可能需要等待更好位置。
- `B`：普通观察，不推送。
- `C`：无交易价值，不推送。

## EARLY_ALPHA

用于类似 SNDK 闪迪事件驱动行情：

- 事件影响强。
- 产业链关联强。
- 同行业先行股已明显反应。
- 标的自身反应仍弱。
- 资金刚开始确认。
- 估值没有明显过热。

满足时输出 `EARLY_ALPHA`，进入 A 级机会池，提示“潜在补涨机会”。

## 飞书推送策略

当前阶段只推：

- `FINAL_ACTION=BUY`

不推：

- S级机会但 `WAIT`
- A级机会但 `WATCH`
- `WAIT_FOR_PULLBACK`
- `DO_NOT_CHASE`
- `ADD`
- `EXIT`
- `AVOID`
- B级
- C级
- 普通新闻
- 普通重大新闻
- 普通风险提示
- 普通价格波动
- 观察级机会
- 产业链机会但未确认
- 没有操作意义的分析
- 任何“值得关注但现在不能买”的信息

每日总结也遵守 BUY-only：当天没有 BUY 时不发送；当天有多个 BUY 时只发送简短 BUY 汇总，不重复完整消息。

## LLM 边界

LLM 只负责新闻总结、事件分类、产业链解释和自然语言表达。`BUY` 必须由规则系统决定。

## Dry-run

```bash
python -m src.v5_dry_run
```

示例输出：

```text
grade | entry_model | final_action | send
C | NO_TRADE_VALUE | AVOID | False
S | WAIT_FOR_PULLBACK | WAIT | False
S | ENTRY_CONFIRMED | BUY | True
S | DO_NOT_CHASE | WAIT | False
A | WAIT_FOR_PULLBACK | WATCH | False
A | ENTRY_CONFIRMED | BUY | True
```
