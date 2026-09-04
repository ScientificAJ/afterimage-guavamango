# Attempt 007 — exact active QQQ regime rule

**REJECT**. Frozen `qqq_regime_b5_m10_c3_s15` on the once-evaluated 2023 outcomes: n=40, net=$108.75, expectancy=0.160R, PF=1.23, hit=30.0%, max DD=9.00R.

Rule hash: `87a27dc2687918a04b6b5a5aa8e474ea88aec6381c71280fb5c38dd3dcea6844`. fresh 2023 outcome validation; no 2023 trade outcome or metric used in design; not untouched-data validation.

## Evidence kept separate

| Evidence | n | Net P&L | Exp/R | PF | Max DD/R |
|---|---:|---:|---:|---:|---:|
| Fresh 2023 outcome validation | 40 | $108.75 | 0.160 | 1.23 | 9.00 |
| Revealed 2024 neighbor sensitivity | 23 | $388.68 | 1.003 | 3.10 | 4.00 |
| 2023+2024 diagnostic pool | 63 | $497.43 | 0.468 | 1.75 | 9.99 |

The pool is diagnostic only and is not relabeled as untouched or rolling OOS.

## Admission audit on fresh 2023

| Criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | False |
| expectancy_at_least_0_25r | False |
| sample_adequate | True |
| max_drawdown_at_most_6r | False |
| cross_symbol_or_three_regime_support | False |
| positive_month_fraction_at_least_60pct | False |
| profitable_at_1_5x_costs | True |
| positive_neighbor_fraction_at_least_60pct | True |
| largest_win_at_most_25pct_gross_profit | True |
| base_net_positive_in_both_2023_and_2024 | True |
| one_and_half_cost_net_positive_in_both_2023_and_2024 | True |

## Execution stress

| Scenario | n | Net P&L | Exp/R | PF | Max DD/R |
|---|---:|---:|---:|---:|---:|
| 1.5x modeled costs | 40 | $50.82 | 0.070 | 1.10 | 9.44 |
| +2 bp slippage per side | 40 | $-86.55 | -0.104 | 0.85 | 10.06 |
| one extra 15-minute entry bar | 40 | $-90.03 | -0.135 | 0.82 | 12.22 |

## Month stability

| Month | n | Net P&L | Exp/R | PF |
|---|---:|---:|---:|---:|
| 2023-01 | 3 | $-51.65 | -1.000 | 0.00 |
| 2023-02 | 3 | $-51.29 | -1.000 | 0.00 |
| 2023-03 | 9 | $51.11 | 0.335 | 1.50 |
| 2023-04 | 2 | $34.85 | 1.006 | 3.07 |
| 2023-05 | 4 | $69.50 | 1.003 | 3.06 |
| 2023-06 | 2 | $34.68 | 1.006 | 3.06 |
| 2023-07 | 1 | $22.46 | 1.314 | Infinity |
| 2023-08 | 5 | $117.71 | 1.403 | 4.46 |
| 2023-09 | 2 | $-33.91 | -1.000 | 0.00 |
| 2023-10 | 4 | $-67.77 | -1.000 | 0.00 |
| 2023-11 | 4 | $0.03 | 0.003 | 1.00 |
| 2023-12 | 1 | $-16.97 | -1.000 | 0.00 |

## Regime stability

| Regime | n | Net P&L | Exp/R | PF |
|---|---:|---:|---:|---:|
| risk_off_bearish | 11 | $-51.65 | -0.272 | 0.66 |
| risk_off_bullish | 15 | $85.46 | 0.335 | 1.50 |
| risk_on_bearish | 14 | $74.94 | 0.311 | 1.49 |

## Limitations

- Late-2023 bars existed previously as warm-up inputs, though no 2023 trade outcome or metric was evaluated before the rule freeze.
- This is backward outcome validation, not chronological forward OOS.
- IEX 15-minute OHLC is not SIP and lacks intrabar ordering; stop-first is conservative.
- Historical QQQ short availability, borrow fees, market impact, and queue position are not modeled.
