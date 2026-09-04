# Attempt 002 — overnight breadth confirmation

**REJECT**. Training selected `gap_b4_m10_s25`. Pseudo-OOS: n=21, net=$-475.60, expectancy=-0.482R, PF=0.44, hit=38.1%, max DD=$585.20 / 11.73R.

## Admission audit

| Criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | False |
| expectancy_at_least_0_25r | False |
| sample_adequate | False |
| max_drawdown_at_most_6r | False |
| cross_symbol_or_three_regime_support | False |
| positive_month_fraction_at_least_60pct | False |
| profitable_at_1_5x_costs | False |
| positive_neighbor_fraction_at_least_60pct | False |
| largest_win_at_most_25pct_gross_profit | False |

## Full predeclared neighborhood

| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gap_b4_m10_s15` | 22 | $-205.20 | 22 | $-551.20 | -0.809 | 0.39 | $-580.80 |
| `gap_b4_m10_s20` | 22 | $-282.20 | 22 | $-550.20 | -0.619 | 0.41 | $-687.80 |
| `gap_b4_m10_s25` | 22 | $-287.20 | 21 | $-475.60 | -0.482 | 0.44 | $-628.90 |
| `gap_b4_m20_s15` | 21 | $-242.60 | 18 | $-546.80 | -0.987 | 0.34 | $-573.20 |
| `gap_b4_m20_s20` | 21 | $-319.60 | 18 | $-545.80 | -0.754 | 0.36 | $-654.20 |
| `gap_b4_m20_s25` | 21 | $-324.60 | 17 | $-441.20 | -0.559 | 0.41 | $-565.30 |
| `gap_b5_m10_s15` | 22 | $-205.20 | 15 | $-243.00 | -0.595 | 0.51 | $-247.50 |
| `gap_b5_m10_s20` | 22 | $-282.20 | 15 | $-213.00 | -0.408 | 0.57 | $-328.50 |
| `gap_b5_m10_s25` | 22 | $-287.20 | 15 | $-278.00 | -0.396 | 0.50 | $-387.50 |
| `gap_b5_m20_s15` | 21 | $-242.60 | 12 | $-281.20 | -0.893 | 0.39 | $-263.80 |
| `gap_b5_m20_s20` | 21 | $-319.60 | 12 | $-251.20 | -0.617 | 0.45 | $-344.80 |
| `gap_b5_m20_s25` | 21 | $-324.60 | 12 | $-286.20 | -0.532 | 0.41 | $-373.80 |

## Honesty and limitations

- May-Sep is pseudo-OOS rather than untouched because attempt 001 already revealed Aug-Sep.
- Option trade-bar opens are not NBBO quotes; fixed adverse per-leg slippage and 1.5x stress cannot reproduce queue position.
- Signals cluster in large overnight-gap regimes and may be sensitive to macro-event composition.
- The IEX feed is not the full SIP.
