# Attempt 006 — QQQ regime-conditioned gap continuation

**REJECT**. Frozen focal `qqq_regime_b5_m10_c4_s15` on the once-evaluated 2024 outcomes: n=9, net=$183.91, expectancy=1.226R, PF=3.72, hit=55.6%, max DD=2.00R.

Family hash: `45227af6bc0598473d4e37a4faa20bd67350727a85bbbfc67fbbbbc8ed65c437`. fresh 2024 outcome validation; no 2024 trade outcome or metric used in design; not untouched-data validation.

## Admission audit

| Criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | True |
| expectancy_at_least_0_25r | True |
| sample_adequate | False |
| max_drawdown_at_most_6r | True |
| cross_symbol_or_three_regime_support | True |
| positive_month_fraction_at_least_60pct | False |
| profitable_at_1_5x_costs | True |
| positive_neighbor_fraction_at_least_60pct | True |
| largest_win_at_most_25pct_gross_profit | True |

## Frozen focal and predeclared neighbors

| Role | Variant | n | Net P&L | Exp/R | PF | Hit | Max DD/R | 1.5x-cost P&L |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| focal | `qqq_regime_b5_m10_c4_s15` | 9 | $183.91 | 1.226 | 3.72 | 55.6% | 2.00 | $142.68 |
| neighbor_only_no_selection | `qqq_regime_b4_m10_c4_s15` | 11 | $150.48 | 0.821 | 2.49 | 45.5% | 2.00 | $107.10 |
| neighbor_only_no_selection | `qqq_regime_b5_m15_c4_s15` | 9 | $183.91 | 1.226 | 3.72 | 55.6% | 2.00 | $142.68 |
| neighbor_only_no_selection | `qqq_regime_b5_m10_c3_s15` | 23 | $388.68 | 1.003 | 3.10 | 52.2% | 4.00 | $353.86 |

## Focal execution stress

| Scenario | n | Net P&L | Exp/R | PF | Max DD/R |
|---|---:|---:|---:|---:|---:|
| 1.5x modeled costs | 9 | $142.68 | 0.899 | 2.98 | 2.00 |
| +2 bp slippage per side | 9 | $162.04 | 0.882 | 2.90 | 2.00 |
| one extra 15-minute entry bar | 9 | $115.66 | 0.782 | 2.37 | 2.00 |

## Month stability

| Month | n | Net P&L | Exp/R | PF |
|---|---:|---:|---:|---:|
| 2024-01 | 1 | $-16.84 | -1.000 | 0.00 |
| 2024-02 | 1 | $50.94 | 3.012 | Infinity |
| 2024-04 | 1 | $50.21 | 3.013 | Infinity |
| 2024-05 | 1 | $-17.17 | -1.000 | 0.00 |
| 2024-08 | 1 | $-16.93 | -1.000 | 0.00 |
| 2024-09 | 1 | $49.95 | 3.004 | Infinity |
| 2024-10 | 1 | $50.27 | 3.003 | Infinity |
| 2024-11 | 1 | $50.25 | 3.000 | Infinity |
| 2024-12 | 1 | $-16.77 | -1.000 | 0.00 |

## Regime stability

| Regime | n | Net P&L | Exp/R | PF |
|---|---:|---:|---:|---:|
| risk_off_bearish | 2 | $33.18 | 1.002 | 2.98 |
| risk_off_bullish | 4 | $66.36 | 1.003 | 2.95 |
| risk_on_bearish | 3 | $84.37 | 1.672 | 6.01 |

## Limitations

- Some late-2024 bars existed previously as warm-up inputs, though no 2024 trade outcome or metric was evaluated before the family freeze.
- This is a backward outcome validation, not chronological forward OOS.
- IEX 15-minute OHLC is not SIP and lacks intrabar ordering; stop-first is conservative.
- Historical QQQ short availability, borrow fees, market impact, and queue position are not modeled.
