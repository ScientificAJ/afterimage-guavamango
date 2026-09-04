# Failed-auction mean-reversion option candidate

## Decision-grade result

Chronological walk-forward OOS produced **17 trades**, **$-204.20 net P&L**, **-0.0491 R expectancy**, **35.3% hit rate**, and **$213.00 max drawdown**.

This result is reported as measured, including if it is negative. It is a research candidate, not approval to submit an order.

The punitive bar-extreme stress case produced **17 trades**, **$-1338.20 net P&L**, **-0.3076 R expectancy**, and **$1338.20 max drawdown**.

## Walk-forward folds

| Fold | Train | Embargo | OOS | Selected | n | Net P&L | Exp/R | Hit | Max DD |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | 2025-01-02..2025-02-07 | 2025-02-10..2025-02-12 | 2025-02-13..2025-02-27 | lb06_z1.50_w35_v100_r125_h03 | 3 | $-24.80 | -0.0189 | 33.3% | $33.60 |
| 2 | 2025-01-02..2025-02-27 | 2025-02-28..2025-03-04 | 2025-03-05..2025-03-19 | lb06_z1.50_w35_v100_r125_h03 | 7 | $-106.20 | -0.0570 | 42.9% | $106.20 |
| 3 | 2025-01-02..2025-03-19 | 2025-03-20..2025-03-24 | 2025-03-25..2025-04-07 | lb06_z1.50_w35_v100_r125_h03 | 5 | $-36.00 | -0.0362 | 40.0% | $62.80 |
| 4 | 2025-01-02..2025-04-07 | 2025-04-08..2025-04-10 | 2025-04-11..2025-04-25 | lb12_z1.75_w40_v110_r100_h06 | 2 | $-37.20 | -0.0988 | 0.0% | $37.20 |

## Variant robustness (full-sample diagnostic only)

Full-sample rows below are parameter-sensitivity diagnostics and were not used as OOS results.

| Variant | Signals | Scored | Missing/illiquid | Net P&L | Exp/R | Hit | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| lb06_z1.50_w35_v100_r125_h03 | 57 | 50 | 7 | $-264.00 | -0.0166 | 38.0% | $369.60 |
| lb06_z1.75_w40_v110_r100_h06 | 31 | 27 | 4 | $-227.20 | -0.0360 | 33.3% | $245.80 |
| lb12_z1.50_w35_v100_r125_h03 | 37 | 32 | 5 | $-410.20 | -0.0575 | 28.1% | $443.40 |
| lb12_z1.75_w40_v110_r100_h06 | 13 | 10 | 3 | $-82.00 | -0.0342 | 30.0% | $105.80 |
| lb18_z1.75_w35_v100_r125_h06 | 15 | 12 | 3 | $-121.20 | -0.0421 | 33.3% | $123.60 |
| lb18_z2.00_w45_v120_r100_h12 | 2 | 2 | 0 | $-95.20 | -0.2346 | 0.0% | $95.20 |

## Implementation contract

- Input: completed SPY 5-minute regular-session bars. Signal evaluation occurs only after the candidate bar closes.
- Signal: first daily failed auction between 10:00 and 14:30 New York time; the bar must breach a trailing same-session z-band, close back inside it, and show the configured rejection wick.
- Instrument: one-lot SPY $5-wide call debit spread for bullish signals or put debit spread for bearish signals; expiry is the first weekday at least three calendar days out.
- Fill model: wait for the next synchronized option bar to complete, use both leg closes with $0.03 adverse slippage per leg and $0.65/contract/side fees. Missing paired bars are not imputed. A separate punitive stress case uses adverse high/low extremes on every leg.
- Validation: expanding chronological training, three complete-session embargo, parameter selection on training trades only, then untouched ten-session OOS slices.
- Execution: `order_dry_run.json` is non-submitting (`submission_allowed=false`, CLI ends in `--dry-run`). Any live paper submission remains serialized behind parent selection and the repository warrant/risk gates.

## Limitations

Alpaca option trade bars do not provide contemporaneous bid/ask or NBBO. The adverse high/low fill model is deliberately punitive, but it is not a substitute for quote-level replay. IEX stock bars are not the full SIP. Contract selection assumes standard weekday expiries and naturally records unavailable/holiday contracts as unscored rather than fabricating prices.
