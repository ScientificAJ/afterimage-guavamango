# Multi-day cross-index trend carry

## Rolling-OOS decision

**95 trades**, **$-1250.10 net**, **-0.5310R expectancy**, **PF 0.6872091277585948055847470350**, **83.1059R / $2602.00 max drawdown**.

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

- At 14:45 New York time, use only that completed five-minute bar and prior completed sessions. Require the configured N-session return direction in at least two of SPY/QQQ/IWM, then trade every confirming underlying.
- Construct a directional one-lot $5-wide debit vertical with the first weekday expiry at least seven calendar days out. Wait until the first entirely post-signal synchronized 15-minute option bar has closed before entry.
- Apply $0.03 adverse slippage per leg per side and $0.65/contract/side. Stop at -1R and target +3R after all costs; preserve worse stop gaps and grant no target improvement. Timeout may extend into following sessions.
- Outer OOS dates never overlap. Variant selection occurs only inside rolling, embargoed inner validation slices. The 1.5x cost and neighbor checks reuse frozen OOS only as stress diagnostics, never as fresh tuning data.
- The dry-run artifact is non-submitting and real paper execution remains parent-serialized behind repository risk/warrant gates.

## Limitations

IEX is not SIP, and Alpaca option trade bars lack NBBO. Sparse/missing synchronized leg bars are counted and excluded rather than imputed. Calendar construction skips weekends but unavailable holiday contracts naturally fail coverage.
