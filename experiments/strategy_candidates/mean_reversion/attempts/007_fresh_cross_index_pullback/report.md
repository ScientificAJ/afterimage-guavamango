# Fresh cross-index pullback/resumption direct-ETF candidate

Fresh nested rolling OOS; variant family frozen before May-August 2026 acquisition.

## Rolling-OOS decision

**69 trades**, **$-2051.07 net**, **-0.2823R expectancy**, **PF 0.5302218944398127364843198871**, **26.7960R / $2832.05 max drawdown**.

Admitted: **False**.

## Admission matrix

| Criterion | Pass |
|---|---:|
| target_stop_gte_3 | True |
| profit_factor_gte_2 | False |
| expectancy_gte_quarter_r | False |
| closed_oos_trades_gte_30 | True |
| max_drawdown_lte_6r | False |
| positive_on_two_underlyings | False |
| positive_in_60pct_folds | False |
| positive_in_60pct_months | False |
| profitable_at_1_5x_costs | False |
| at_least_60pct_neighbors_positive | False |
| no_single_trade_gt_25pct_gross_profit | True |

## Implementation contract

- Require SPY/QQQ/IWM completed-bar trend confirmation and an actual two-bar pullback/resumption event; only then trade each confirming ETF.
- Enter after the next five-minute bar closes with adverse slippage; ATR inputs end at the signal bar and position size targets about $100 risk.
- Solve stop/target for after-cost -1R/+3R, stop-first on same-bar ambiguity, worse gap stops, and no target improvement.
- Use non-overlapping outer OOS with embargoed nested selection; apply 1.5x-cost and neighbor checks without relabeling them as fresh.
- The exact Alpaca bracket artifact is non-submitting and ends in --dry-run.

## Limitations

IEX is not SIP. Five-minute OHLC requires the conservative stop-first rule when both stop and target touch within one bar. ETF short borrow is not reconstructed.
