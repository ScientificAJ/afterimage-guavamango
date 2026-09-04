# Cross-index relative-value convergence

Fresh nested rolling OOS; family frozen before September-December 2024 acquisition.

Rolling OOS: **26 trades**, **$-138.57 net**, **-0.0533R**, **PF 0.8446785854396682172280446113**, **4.2018R max drawdown**.

Admitted: **False**.

## Admission matrix

| Criterion | Pass |
|---|---:|
| target_stop_gte_3 | True |
| profit_factor_gte_2 | False |
| expectancy_gte_quarter_r | False |
| closed_oos_trades_gte_30 | False |
| max_drawdown_lte_6r | True |
| positive_on_two_pair_compositions_or_three_month_regimes | True |
| positive_in_60pct_folds | False |
| positive_in_60pct_months | False |
| profitable_at_1_5x_costs | False |
| at_least_60pct_neighbors_positive | False |
| no_single_trade_gt_25pct_gross_profit | True |

## Implementation contract

- At one predeclared New York time, compute each completed ETF return since its own regular-session open. Long the laggard and short the leader only when dispersion exceeds the selected inner-validation threshold.
- Wait for the next aligned five-minute pair bar to close, use roughly $10,000 per leg, and apply 1 bp per side plus $0.005/share (1.5x stress separately).
- Monitor combined after-cost pair P&L only on completed aligned closes. Stop at -$100 or worse and target exactly +$300, ensuring a 3R operational ratio without asynchronously combining leg extremes.
- Outer OOS dates are unique and embargoed; only inner validation selects time/divergence/horizon. Neighbor and cost stress reuse frozen OOS solely as diagnostics.
- Alpaca has no atomic equity-pair order in this CLI. The dry-run artifact therefore contains two non-submitting serialized entry payloads; any real paper pair requires parent-approved pairing and a combined-PnL monitor.

## Limitations

IEX is not SIP. Close-confirmed exits may react later than intrabar thresholds but avoid impossible asynchronous leg extremes. Short borrow and legging risk are not reconstructed and count against deployment readiness.
