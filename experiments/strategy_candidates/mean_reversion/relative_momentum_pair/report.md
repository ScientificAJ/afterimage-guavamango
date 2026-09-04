# Fresh cross-index relative-momentum pair

Fresh nested rolling OOS; family frozen before January-April 2024 acquisition.

Rolling OOS: **48 trades**, **$-1163.86 net**, **-0.2425R**, **PF 0.4441026718760448210311129792**, **12.0489R max drawdown**.

Admitted: **False**.

## Admission matrix

| Criterion | Pass |
|---|---:|
| target_stop_gte_3 | True |
| profit_factor_gte_2 | False |
| expectancy_gte_quarter_r | False |
| closed_oos_trades_gte_30 | True |
| max_drawdown_lte_6r | False |
| positive_on_two_pair_compositions_or_three_month_regimes | False |
| positive_in_60pct_folds | False |
| positive_in_60pct_months | False |
| profitable_at_1_5x_costs | False |
| at_least_60pct_neighbors_positive | False |
| no_single_trade_gt_25pct_gross_profit | True |

## Implementation contract

- At a predeclared time, rank completed SPY/QQQ/IWM returns since the regular-session open. Long the leader and short the laggard only above the selected inner-validation divergence threshold.
- Wait for the next aligned pair bar to close. Use about $20,000 per leg with 1 bp/side plus $0.005/share; apply a 1.5x cost stress.
- Monitor combined pair P&L on completed aligned closes, stop at -$100 or worse, and cap the target at +$300 (3R). No asynchronous high/low combination is permitted.
- Outer OOS dates are unique and embargoed; inner validation alone chooses time, divergence, and horizon. Neighbor/stress checks never become fresh training data.
- The dry run contains two non-submitting legs. Live paper use would require parent-approved serialization, borrow confirmation, and a combined-PnL monitor because Alpaca does not offer atomic equity pairs here.

## Limitations

IEX is not SIP. Close-confirmed exits can lag intrabar thresholds. Short borrow and legging risk are not reconstructed and remain deployment blockers even if statistical gates pass.
