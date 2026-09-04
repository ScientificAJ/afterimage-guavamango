# Multi-day trend: options versus direct ETF execution

This is a pseudo-OOS execution comparison on attempt 004's fixed signal dates, not a fresh holdout.

Result: **118 trades**, **$249.71 net**, **0.0157R**, **PF 1.027162024724393175501857321**, **39.7601R max drawdown**.

Admitted: **False**.

## Admission matrix

| Criterion | Pass |
|---|---:|
| target_stop_gte_3 | True |
| profit_factor_gte_2 | False |
| expectancy_gte_quarter_r | False |
| closed_oos_trades_gte_30 | True |
| max_drawdown_lte_6r | False |
| positive_on_two_underlyings | True |
| positive_in_60pct_folds | False |
| positive_in_60pct_months | False |
| profitable_at_1_5x_costs | True |
| at_least_60pct_neighbors_positive | True |
| no_single_trade_gt_25pct_gross_profit | True |

## Implementation contract

- Use the completed 14:45 New York five-minute bar and only completed prior sessions. Trade each ETF whose N-session direction participates in the required SPY/QQQ/IWM agreement.
- Enter after the next five-minute bar closes with adverse slippage. Set an ATR-scaled after-cost -1R stop and +3R target, conservatively resolving same-bar ambiguity to the stop and retaining gap-through losses.
- Hold across subsequent sessions up to the configured horizon. Base costs are 1 bp/side plus $0.005/share and stress is 1.5x.
- OOS slices do not overlap; nested selection uses only earlier embargoed validation. This is an execution comparison, not a relabeled fresh holdout.
- `order_dry_run.json` contains an exact non-submitting Alpaca bracket command ending in `--dry-run`.

## Limitations

IEX is not SIP. Five-minute OHLC requires a stop-first assumption for same-bar stop/target touches. ETF short borrow is not reconstructed.
