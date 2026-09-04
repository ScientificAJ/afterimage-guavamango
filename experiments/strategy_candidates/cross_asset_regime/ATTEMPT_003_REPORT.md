# Attempt 003 — sector-to-index lead–lag catch-up

**REJECT**. `None`: n=0, net=$0.00, expectancy=0.000R, PF=0.00, max DD=0.00R.

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

## Neighborhood

| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
| `leadlag_b3_g05_s15` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b3_g05_s20` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b3_g05_s25` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b3_g10_s15` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b3_g10_s20` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b3_g10_s25` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b4_g05_s15` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b4_g05_s20` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b4_g05_s25` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b4_g10_s15` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b4_g10_s20` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |
| `leadlag_b4_g10_s25` | 0 | $0.00 | 0 | $0.00 | 0.000 | 0.00 | $0.00 |

## Limitations

- All May-Sep evidence is rolling/pseudo-OOS, not untouched.
- Trade-bar opens plus fixed slippage are not NBBO quote replay.
- Sparse synchronized option bars reduce the checkpoint sample.
- IEX is not the full SIP.
