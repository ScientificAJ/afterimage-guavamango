# Cross-asset breadth rotation option candidate

## Verdict

**REJECT**. Frozen variant `b6_spy10_h07_3r` produced 3 untouched OOS trades, $-183.80 net P&L, -0.2655 expectancy/R, 0.0% hit rate, $183.80 max drawdown, and 0.00 profit factor.

Aggregate rolling-OOS profit factor was **0.00** versus the 3.00 target. The operational target:stop is **3:1** after modeled fees and slippage.

## Expanding walk-forward selection

| Fold | Training | Validation | Selected | n | Net P&L | Exp/R | PF | Hit | Max DD |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | 2026-01-02..2026-04-30 | 2026-05-01..2026-05-29 | b5_plain_h07_3r | 8 | $-567.80 | -0.3172 | 0.00 | 12.5% | $567.80 |
| 2 | 2026-01-02..2026-05-29 | 2026-06-01..2026-06-30 | b5_plain_h07_3r | 9 | $-768.40 | -0.4395 | 0.00 | 0.0% | $768.40 |
| 3 | 2026-01-02..2026-06-30 | 2026-07-01..2026-07-31 | b5_plain_h07_3r | 7 | $-477.20 | -0.3594 | 0.00 | 0.0% | $477.20 |

## Every predeclared variant

The per-variant holdout rows were computed together in the sole holdout pass after the winner was frozen; only the frozen row is selection OOS, while the rest are sensitivity diagnostics.

| Variant | Exit | Dev n | Dev P&L | OOS n | OOS P&L | OOS Exp/R | OOS PF | OOS hit | OOS max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `b5_plain_h07` | fixed | 79 | $-6571.40 | 11 | $-583.60 | -0.2318 | 0.05 | 9.1% | $583.60 |
| `b5_plain_h21` | fixed | 39 | $-3900.40 | 3 | $-187.80 | -0.1903 | 0.15 | 33.3% | $220.20 |
| `b6_spy10_h07` | fixed | 20 | $-2034.00 | 4 | $-244.40 | -0.2517 | 0.00 | 0.0% | $244.40 |
| `b6_spy10_h21` | fixed | 11 | $-1045.60 | 2 | $-220.20 | -0.3911 | 0.00 | 0.0% | $220.20 |
| `b5_plain_h07_3r` | target_stop_3r | 62 | $-4916.20 | 9 | $-481.40 | -0.2941 | 0.00 | 0.0% | $481.40 |
| `b5_plain_h21_3r` | target_stop_3r | 29 | $-2843.40 | 2 | $-201.20 | -0.4834 | 0.00 | 0.0% | $201.20 |
| `b6_spy10_h07_3r` | target_stop_3r | 17 | $-1562.20 | 3 | $-183.80 | -0.2655 | 0.00 | 0.0% | $183.80 |
| `b6_spy10_h21_3r` | target_stop_3r | 9 | $-835.40 | 1 | $-119.60 | -0.4344 | 0.00 | 0.0% | $119.60 |

## Production integration contract

- Input synchronized completed 15-minute IEX bars for QQQ, IWM, XLK, XLF, XLE, XLV, and XLY plus SPY daily closes; evaluate once at 10:30 New York time.
- Require the frozen breadth/magnitude/regime rules; select QQQ/IWM from completed-bar relative strength only.
- Resolve the earliest listed 3–9 DTE exact $5 debit vertical from the live contract catalog. Reject missing legs, stale quotes, non-positive debit, or an unattainable 3R target.
- Emit one-lot `order_class=mleg`, limit debit, buy-to-open long leg and sell-to-open short leg. Enforce global max one open strategy position.
- Attach the precomputed net-of-cost 3R target and 1R stop to lifecycle state; stop evaluation precedes target evaluation within a bar. Time out after the frozen hold count and close both legs as one MLEG.
- Route only through AFTERIMAGE warrant, risk-governor, serialized executor, lifecycle reconciliation, and evidence-vault gates. The included artifact is `--dry-run` only and submits nothing.

## Limitations

- Alpaca option trade bars are not contemporaneous NBBO quotes; paired-leg extrema are deliberately adverse but not executable quote replay.
- IEX stock bars are not the full SIP and can differ from consolidated prices.
- Historical contract discovery depends on Alpaca's retained inactive-contract catalog.
- The final holdout is short and contains one market regime; confidence intervals remain wide.
- A 3R target can be skipped when it exceeds the $5 vertical's achievable value.
