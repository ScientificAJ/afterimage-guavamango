# Frozen attempt-005 backward validation

Rule hash: `fbf67ec3cefd371533ef83d57dc74939c97b52ac1c1b649ff5996b6568c2fd98`. This exact rule was frozen before the 2025 cache was acquired or evaluated.

## Evidence kept separate

| Evidence | n | Net P&L | Expectancy/R | PF | Max DD/R |
|---|---:|---:|---:|---:|---:|
| 2025 fresh backward validation | 55 | $47.83 | 0.056 | 1.07 | 11.31 |
| 2026 rolling evidence | 37 | $581.48 | 0.930 | 2.82 | 4.00 |
| Provenance-labeled pool | 92 | $629.31 | 0.408 | 1.65 | 11.31 |

The 2025 slice is genuinely unseen during design, but because it precedes the design period it is a fresh backward validation—not forward OOS. The pooled row is diagnostic only.

## Frozen-rule stress

| Scenario | n | Net P&L | Expectancy/R | PF |
|---|---:|---:|---:|---:|
| 1.5x modeled costs | 55 | $38.29 | 0.045 | 1.06 |
| +2 bp slippage per side | 55 | $-53.29 | -0.041 | 0.93 |
| one extra 15-minute entry bar | 55 | $76.34 | 0.082 | 1.12 |

## Decision: REJECT_AFTER_FRESH_EXTENSION

The frozen rule fails the fresh-extension PF, expectancy, drawdown, and positive-month admission floors. The prior 2026 result is therefore not promoted as a robust production candidate.

| Admission criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | False |
| expectancy_at_least_0_25r | False |
| sample_adequate | True |
| max_drawdown_at_most_6r | False |
| cross_symbol_or_three_regime_support | True |
| positive_month_fraction_at_least_60pct | False |
| profitable_at_1_5x_costs | True |
| positive_neighbor_fraction_at_least_60pct | True |
| largest_win_at_most_25pct_gross_profit | True |

## 2025 stability

| Symbol | n | Net P&L | Expectancy/R | PF |
|---|---:|---:|---:|---:|
| IWM | 33 | $-127.18 | -0.224 | 0.71 |
| QQQ | 22 | $175.01 | 0.477 | 1.81 |

| Month | n | Net P&L | Expectancy/R | PF |
|---|---:|---:|---:|---:|
| 2025-01 | 5 | $35.62 | 0.440 | 1.70 |
| 2025-02 | 1 | $50.27 | 3.011 | Infinity |
| 2025-03 | 8 | $1.01 | 0.003 | 1.01 |
| 2025-04 | 11 | $15.98 | 0.092 | 1.12 |
| 2025-05 | 5 | $-86.44 | -1.000 | 0.00 |
| 2025-06 | 2 | $-33.80 | -1.000 | 0.00 |
| 2025-07 | 4 | $2.48 | 0.027 | 1.07 |
| 2025-08 | 6 | $80.94 | 0.789 | 3.34 |
| 2025-09 | 3 | $-50.72 | -1.000 | 0.00 |
| 2025-10 | 5 | $-17.25 | -0.199 | 0.75 |
| 2025-11 | 4 | $66.59 | 1.001 | 2.96 |
| 2025-12 | 1 | $-16.85 | -1.000 | 0.00 |

| Lagged SPY regime × direction | n | Net P&L | Expectancy/R | PF |
|---|---:|---:|---:|---:|
| risk_off_bearish | 12 | $68.52 | 0.336 | 1.50 |
| risk_off_bullish | 14 | $41.13 | 0.178 | 1.27 |
| risk_on_bearish | 13 | $48.18 | 0.222 | 1.35 |
| risk_on_bullish | 16 | $-110.00 | -0.393 | 0.51 |

## Limitations

- Backward validation is fresh to strategy design but is not chronological forward OOS.
- IEX 15-minute OHLC is not SIP and does not reveal intrabar path; stop-first ordering is conservative.
- Short availability, borrow fees, market impact, and queue position are not modeled.
- The plus-two-bps and one-bar-delay diagnostics were not used to select or alter the rule.
