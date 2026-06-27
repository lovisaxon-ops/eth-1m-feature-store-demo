# Backtest Methodology Summary

This public demo intentionally describes process, not production strategy
thresholds.

Recommended workflow:

1. Build a timestamp-indexed OHLCV feature store.
2. Split data chronologically into train, validation, and holdout windows.
3. Fit or select signal rules only on train/validation windows.
4. Lock parameters before evaluating the holdout window.
5. Include fees, spread/slippage assumptions, and execution delay.
6. Report drawdown, trade count, exposure, turnover, and out-of-sample behavior.
7. Repeat across rolling walk-forward windows before treating any result as stable.

Common failure modes:

- optimizing thresholds directly on the final test period,
- ignoring fees or assuming perfect fills,
- mixing future candles into feature rows,
- treating one high-return run as robust without regime checks,
- using live-trading code paths before validating data freshness and order safety.

This repository is for research infrastructure demonstration only.

