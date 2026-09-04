# Attempt 004 — liquid ETF lead–lag execution

**REJECT**. `equity_b4_g10_s15`: n=17, net=$-55.96, expectancy=-0.201R, PF=0.58, hit=35.3%, max DD=5.18R.

## Admission audit

| Criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | False |
| expectancy_at_least_0_25r | False |
| sample_adequate | False |
| max_drawdown_at_most_6r | True |
| cross_symbol_or_three_regime_support | False |
| positive_month_fraction_at_least_60pct | False |
| profitable_at_1_5x_costs | False |
| positive_neighbor_fraction_at_least_60pct | False |
| largest_win_at_most_25pct_gross_profit | False |

## Full neighborhood

| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
| `equity_b3_g05_s15` | 42 | $21.45 | 37 | $-88.62 | -0.142 | 0.75 | $-119.40 |
| `equity_b3_g05_s25` | 42 | $10.85 | 37 | $-160.82 | -0.166 | 0.61 | $-199.29 |
| `equity_b3_g05_s35` | 42 | $-94.79 | 37 | $-200.08 | -0.152 | 0.56 | $-239.50 |
| `equity_b3_g10_s15` | 29 | $45.84 | 25 | $-58.24 | -0.136 | 0.75 | $-76.15 |
| `equity_b3_g10_s25` | 29 | $31.22 | 25 | $-110.01 | -0.169 | 0.60 | $-135.62 |
| `equity_b3_g10_s35` | 29 | $-36.16 | 25 | $-141.40 | -0.161 | 0.54 | $-167.97 |
| `equity_b4_g05_s15` | 31 | $166.04 | 25 | $-37.26 | -0.094 | 0.81 | $-64.74 |
| `equity_b4_g05_s25` | 31 | $125.77 | 25 | $-74.12 | -0.117 | 0.69 | $-101.57 |
| `equity_b4_g05_s35` | 31 | $55.80 | 25 | $-81.29 | -0.094 | 0.67 | $-108.74 |
| `equity_b4_g10_s15` | 20 | $156.77 | 17 | $-55.96 | -0.201 | 0.58 | $-74.90 |
| `equity_b4_g10_s25` | 20 | $141.52 | 17 | $-83.96 | -0.192 | 0.48 | $-102.88 |
| `equity_b4_g10_s35` | 20 | $109.81 | 17 | $-102.68 | -0.173 | 0.43 | $-121.60 |

## Production contract

- signal_time: 11:45, 13:15, or 14:15 America/New_York after named stock bar completes
- execution: next 15-minute QQQ/IWM bar open; $10,000 max notional; long/short shares
- bracket: one-cent prices with after-cost target:stop >=3; stop-first same-bar convention; six-bar timeout
- risk: global maximum one open strategy position; reject unavailable shorts and stale bars
- routing: existing AFTERIMAGE warrant, governor, serialized Alpaca executor, lifecycle reconciler, and evidence vault

## Limitations

- May-Sep is rolling/pseudo-OOS because prior attempts revealed part of the period.
- 15-minute OHLC cannot establish intrabar ordering, so same-bar stop is assumed first.
- IEX is not the full SIP.
- Short-sale borrow availability and live spread can differ from historical assumptions.
