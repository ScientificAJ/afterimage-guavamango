# Attempt 017 — frozen low-noise consensus validation

**REJECT**. Fresh 2021–2022: n=40, net=$-58.47, expectancy=-0.057R, PF=0.99, max DD=6.93R.

Rule hash: `472fcf2bdfb48791faa8e50e15190fc5060c0df886b9e76cadf0a80098d5dbdc`. No 2021–2022 outcome was used in design.

## Admission audit

| Criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | False |
| expectancy_at_least_0_25r | False |
| sample_adequate | True |
| max_drawdown_at_most_6r | False |
| cross_symbol_or_three_regime_support | True |
| positive_month_fraction_at_least_60pct | False |
| profitable_at_1_5x_costs | False |
| positive_neighbor_fraction_at_least_60pct | True |
| largest_win_at_most_25pct_gross_profit | True |
| fresh_2021_and_2022_both_profitable | False |
| development_2023_2024_2025_all_profitable | True |

## Year stability

| Year | n | P&L | Exp/R | PF | DD/R |
|---:|---:|---:|---:|---:|---:|
| 2021 | 28 | $-553.89 | -0.089 | 0.83 | 5.93 |
| 2022 | 12 | $495.42 | 0.017 | 1.32 | 2.00 |

## Cost and delay stress

| Scenario | n | P&L | Exp/R | PF | DD/R |
|---|---:|---:|---:|---:|---:|
| 1.5x costs | 40 | $-124.28 | -0.064 | 0.97 | 6.96 |
| +2 bp/side | 40 | $-217.43 | -0.074 | 0.96 | 7.03 |
| one-session delay | 39 | $-60.58 | -0.056 | 0.99 | 6.63 |

## Symbol stability

| Symbol | n | P&L | Exp/R | PF |
|---|---:|---:|---:|---:|
| IWM | 3 | $412.77 | 0.394 | 2.77 |
| QQQ | 1 | $174.02 | 1.228 | Infinity |
| XLE | 8 | $-14.45 | -0.014 | 0.99 |
| XLF | 9 | $-185.71 | -0.179 | 0.83 |
| XLK | 6 | $-553.38 | -0.391 | 0.30 |
| XLV | 3 | $-271.14 | -0.618 | 0.07 |
| XLY | 10 | $379.42 | 0.124 | 1.33 |

## Month stability

| Month | n | P&L | Exp/R | PF |
|---|---:|---:|---:|---:|
| 2021-01 | 2 | $-656.03 | -1.000 | 0.00 |
| 2021-02 | 3 | $391.71 | 0.394 | 2.54 |
| 2021-03 | 1 | $240.53 | 0.949 | Infinity |
| 2021-04 | 4 | $355.11 | 0.420 | 2.98 |
| 2021-06 | 5 | $-289.99 | 0.004 | 0.59 |
| 2021-08 | 5 | $-339.73 | -0.479 | 0.51 |
| 2021-10 | 3 | $-16.45 | -0.048 | 0.93 |
| 2021-11 | 4 | $-92.18 | -0.196 | 0.74 |
| 2021-12 | 1 | $-146.86 | -1.000 | 0.00 |
| 2022-01 | 2 | $417.15 | 0.428 | 3.86 |
| 2022-04 | 2 | $-253.08 | -0.428 | 0.08 |
| 2022-07 | 2 | $607.21 | 0.945 | 7.35 |
| 2022-08 | 4 | $170.84 | 0.080 | 1.29 |
| 2022-11 | 1 | $-192.41 | -1.000 | 0.00 |
| 2022-12 | 1 | $-254.29 | -1.000 | 0.00 |

## Limitations

- Fresh block is backward validation, not chronological forward OOS.
- Alpaca IEX daily OHLC is not SIP and has no intraday path; stop-first is conservative.
- Historical liquidity, market impact, and queue position are not modeled.
