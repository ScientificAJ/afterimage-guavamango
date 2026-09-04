# Multi-underlying compression-to-gap expansion

## Rolling-OOS result

Closed OOS trades: **0**; net: **$0**; expectancy: **0.0000R**; PF: **None**; max drawdown: **0R / $0**.

Admitted: **False**.

## Fixed admission bar

| Criterion | Pass |
|---|---:|
| target_stop_gte_3 | False |
| profit_factor_gte_2 | False |
| expectancy_gte_quarter_r | False |
| closed_oos_trades_gte_30 | False |
| max_drawdown_lte_6r | True |
| positive_on_two_underlyings | False |
| positive_in_60pct_folds | False |
| positive_in_60pct_months | False |
| profitable_at_1_5x_costs | False |
| at_least_60pct_neighbor_variants_positive | False |
| no_single_trade_gt_25pct_gross_profit | False |

## Per-underlying OOS

| Underlying | n | Net | PF | Exp/R | DD R |
|---|---:|---:|---:|---:|---:|
| SPY | 0 | $0 | None | 0.0000 | 0 |
| QQQ | 0 | $0 | None | 0.0000 | 0 |
| IWM | 0 | $0 | None | 0.0000 | 0 |

## Implementation contract

- Read only completed, aligned IEX bars. Prior-day compression uses only sessions ending before the signal day; gap uses the opening print; impulse uses the completed 09:30-09:35 New York bar.
- Require at least two of SPY/QQQ/IWM to align, then trade each confirming underlying. Use the first weekday expiry at least three calendar days out and a directional $5 debit spread.
- Wait for the first synchronized option bar after signal completion to itself close. Apply adverse leg slippage and per-contract fees on entry and exit.
- Stop is -1R and target +3R after modeled total costs. Gap-through stops retain the worse close; targets are capped at the threshold. Missing leg bars are excluded, never imputed.
- Outer test dates are unique. Selection occurs only on embargoed inner validation slices. Double-cost and parameter-neighbor checks use the same frozen outer dates and do not relabel them as fresh.
- `order_dry_run.json` cannot submit and ends with `--dry-run`; real paper execution remains parent-serialized behind normal gates.

## Limitations

IEX is not SIP and historical option trade bars have no NBBO. Close-plus-adverse-slippage is a conservative proxy, not quote replay. Standard weekday expiry construction records holiday/unavailable contracts as missing.
