# 历史回放方法

运行 `python -m src.backtest`。案例配置在 `config/backtest_cases.json`，结果写入 `reports/backtest_report.md` 和 `reports/backtest_results.json`。

`ReplayEngine.generate_signal` 先执行 `bars[:signal_index + 1]`，技术和量价评分只能看到信号日及以前。未来20个交易日单独用于1/5/20日收益、MFE和MAE。测试会篡改未来K线并验证信号完全不变。

聚合指标包括20日命中率、盈亏比、假阳性率、分数/收益相关性、高机会高风险分组和数据质量分组。数据源失败的案例标为UNAVAILABLE且不纳入统计。

限制：目前只有少量人工选择的历史事件，存在样本选择和幸存者偏差；历史事件文本、当时可见财务快照和退市样本尚未完整重建；Yahoo复权口径可能变化。因此报告是工程验证，不是盈利证明。
