# Cross-index VWAP trend-persistence option candidate

## Rolling OOS decision

Nested rolling OOS: **18 trades**, **$-268.80 net P&L**, **-1.1290 R expectancy**, **22.2% hit rate**, **0.1198428290766208251473477407 profit factor**, and **$279.60 max drawdown**.

Operational target:stop is 3.0 after modeled costs: **True**. Rolling-OOS profit factor target >=3.0: **False**.

## Outer rolling folds

| Fold | Train | Embargo | OOS | Selected | n | Net | Exp/R | PF | Hit | DD |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | 2025-05-01..2025-06-12 | 2025-06-13..2025-06-16 | 2025-06-17..2025-07-01 | t1130_m15_c2_l06_r10_h24 | 3 | $-6.80 | -0.1615 | 0.6136363636363636363636363636 | 66.7% | $17.60 |
| 2 | 2025-05-15..2025-06-27 | 2025-06-30..2025-07-01 | 2025-07-02..2025-07-16 | t1130_m15_c2_l06_r10_h24 | 3 | $-82.80 | -2.9664 | 0E+2 | 0.0% | $82.80 |
| 3 | 2025-05-30..2025-07-14 | 2025-07-15..2025-07-16 | 2025-07-17..2025-07-30 | t1230_m20_c2_l12_r10_h24 | 5 | $-61.00 | -0.8516 | 0.2939814814814814814814814815 | 20.0% | $86.40 |
| 4 | 2025-06-13..2025-07-28 | 2025-07-29..2025-07-30 | 2025-07-31..2025-08-13 | t1230_m20_c2_l12_r10_h24 | 5 | $-79.00 | -0.8254 | 0.005037783375314861460957178841 | 20.0% | $79.00 |
| 5 | 2025-06-30..2025-08-11 | 2025-08-12..2025-08-13 | 2025-08-14..2025-08-27 | t1230_m20_c2_l12_r10_h24 | 2 | $-39.20 | -1.2772 | 0E+2 | 0.0% | $39.20 |

## Implementation contract

- At each predeclared time, SPY must agree with the required count of SPY/QQQ/IWM on session return direction, recent return direction, and side of session VWAP. All inputs are completed, timestamp-aligned five-minute bars.
- The next synchronized SPY option bar is allowed to complete before entry. Both legs receive $0.03 adverse slippage on entry and exit plus $2.60 total contract fees.
- The stop credit encodes -1R and target credit +3R after total costs. Stop gaps use the worse observed close; target fills receive no price improvement. Timeout exits retain observed adverse-slippage credit.
- Each outer OOS slice is unique. Parameter selection uses only inner rolling validation dates inside the preceding rolling training window, separated by two-session inner and outer embargoes.
- `order_dry_run.json` is non-submitting and ends in `--dry-run`. Any eventual paper order must wait for parent selection and normal warrant/risk gates.

## Data limitations

IEX is not the consolidated SIP. Alpaca historical option trade bars contain no bid/ask NBBO, so close plus explicit adverse leg slippage is a conservative proxy rather than quote replay. Unsynchronized/missing legs are excluded and counted; prices are never imputed.
