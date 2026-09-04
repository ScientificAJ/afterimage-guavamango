# Cross-index trend: options versus direct ETF execution

This is explicitly a pseudo-OOS execution comparison against attempt 002's fixed signal family, not a newly untouched holdout.

## Direct-underlying result

**34 trades**, **$444.05 net**, **0.1114R expectancy**, **PF 1.308584493290432873056796781**, and **7.7177R / $851.00 max drawdown**.

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
| at_least_60pct_neighbors_positive | False |
| no_single_trade_gt_25pct_gross_profit | True |

## Implementation contract

- Use completed, aligned SPY/QQQ/IWM five-minute bars. Require trend direction from session return, recent return, and session VWAP in the configured number of indices; trade every confirming ETF.
- The entry is the close of the first fully post-signal five-minute bar plus adverse slippage. ATR uses bars completed no later than the signal bar. Position size targets about $100 initial risk.
- Stop and target prices are solved so the modeled after-cost loss is 1R and target profit is 3R. If both touch in a bar, record the stop first; stop gaps receive worse open fills; targets receive no improvement.
- Modeled costs are 1 bp per side plus $0.005/share; stress is 1.5x. The exact bracket payload in `order_dry_run.json` is non-submitting and ends with `--dry-run`.
- Outer pseudo-OOS dates are unique, with inner embargoed selection. This compares execution structures honestly; it does not relabel attempt 002's revealed dates as a fresh holdout.

## Limitations

IEX is not SIP. Five-minute OHLC cannot order intrabar stop versus target except by the conservative stop-first rule. Borrow availability for short ETF signals is not reconstructed.
