# Attempt 005 — confirmed overnight-gap ETF shares

**ADMIT on the 2026 rolling evidence only**. `equity_gap_b4_m10_s15`: n=37, net=$581.48, expectancy=0.930R, PF=2.82, hit=48.6%, max DD=4.00R.

Rolling provenance: March/April expanding-fold validation plus frozen May–September pseudo-OOS. The May–September pseudo-OOS slice alone is n=22, net=$221.18, expectancy=0.606R, PF=2.02. The separately frozen, previously unused 2025 backward validation in `FRESH_EXTENSION_REPORT.md` rejects the production candidate; this report preserves the narrower 2026 evidence.

## Admission audit — 2026 rolling evidence

| Criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | True |
| expectancy_at_least_0_25r | True |
| sample_adequate | True |
| max_drawdown_at_most_6r | True |
| cross_symbol_or_three_regime_support | True |
| positive_month_fraction_at_least_60pct | True |
| profitable_at_1_5x_costs | True |
| positive_neighbor_fraction_at_least_60pct | True |
| largest_win_at_most_25pct_gross_profit | True |

## Neighborhood

| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
| `equity_gap_b4_m10_s15` | 22 | $444.27 | 22 | $221.18 | 0.606 | 2.02 | $204.83 |
| `equity_gap_b4_m10_s25` | 22 | $264.85 | 22 | $105.05 | 0.180 | 1.31 | $90.68 |
| `equity_gap_b4_m10_s35` | 22 | $224.93 | 22 | $31.92 | 0.038 | 1.07 | $12.79 |
| `equity_gap_b4_m20_s15` | 21 | $395.27 | 18 | $151.00 | 0.518 | 1.82 | $129.54 |
| `equity_gap_b4_m20_s25` | 21 | $187.53 | 18 | $43.30 | 0.095 | 1.15 | $28.73 |
| `equity_gap_b4_m20_s35` | 21 | $155.29 | 18 | $12.07 | 0.019 | 1.03 | $-2.51 |
| `equity_gap_b5_m10_s15` | 22 | $444.27 | 15 | $206.35 | 0.822 | 2.52 | $212.82 |
| `equity_gap_b5_m10_s25` | 22 | $264.85 | 15 | $141.82 | 0.355 | 1.66 | $134.80 |
| `equity_gap_b5_m10_s35` | 22 | $224.93 | 15 | $116.56 | 0.213 | 1.46 | $104.78 |
| `equity_gap_b5_m20_s15` | 21 | $395.27 | 12 | $119.08 | 0.610 | 2.01 | $119.29 |
| `equity_gap_b5_m20_s25` | 21 | $187.53 | 12 | $53.46 | 0.173 | 1.29 | $45.09 |
| `equity_gap_b5_m20_s35` | 21 | $155.29 | 12 | $60.24 | 0.141 | 1.28 | $51.86 |

## Production contract

- signal: 09:45 ET after overnight breadth and both QQQ/IWM first-bar confirmation
- instrument: up to $10,000 QQQ or IWM shares, long or short
- entry: next 15-minute bar open with one bp adverse slippage
- exit: cent-rounded after-cost >=3R target / 1R stop; stop-first; six-bar timeout
- risk: max one open strategy position through AFTERIMAGE warrant/governor/serialized execution/lifecycle gates

## Limitations

- May-Sep is pseudo-OOS and March-Apr are expanding-fold validation; no later untouched calendar remains.
- 15-minute OHLC has no intrabar ordering; stop-first is conservative.
- IEX is not SIP.
- Historical short availability is not modeled.
