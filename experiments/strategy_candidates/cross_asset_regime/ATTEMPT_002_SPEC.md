# Attempt 002 — overnight breadth confirmation

## Why this is materially distinct

Attempt 001 used same-session 09:30–10:30 relative strength. Attempt 002 uses the prior regular-session close, the overnight gap, and independent first-bar confirmation from both QQQ and IWM. It predicts gap continuation rather than same-session cross-sectional leadership. Attempt 001's August–September holdout is already revealed, so all May–September evidence here is labeled rolling/pseudo-OOS, never untouched.

## Frozen signal

At 09:45 New York time, after the first 15-minute bar completes, calculate each ETF's gap from its prior regular-session close to its 09:30 open for QQQ, IWM, XLK, XLF, XLE, XLV, and XLY. Require either four or five of seven gaps in one direction and a cross-sectional mean absolute gap of 0.10% or 0.20%. Require both QQQ and IWM's 09:30–09:45 candles to close in the gap direction. Select the one with the larger direction-adjusted overnight gap. One signal and at most one position are allowed per session.

## Frozen execution neighborhood

Buy the nearest-strike, exact $5-wide call debit vertical for bullish signals or put debit vertical for bearish signals, using the earliest listed expiry from three through nine calendar DTE. Enter on the first synchronized option bar beginning at or after 09:45 using the paired-leg open plus $0.03 adverse slippage per leg. Evaluate exits only on later synchronized bar opens, with $0.03 adverse slippage per leg. The nominal 1R stop is 15%, 20%, or 25% of entry debit; the target is the smallest cent credit whose after-$2.60-fee net profit is at least three times the nominal after-fee stop loss. Stop evaluation precedes target evaluation. Time out after six 15-minute bars.

This is a 2 × 2 × 3 predeclared family: breadth {4,5}, mean-gap threshold {0.10%,0.20%}, stop fraction {15%,20%,25%}. January–April option trades select the single variant by expectancy/R, then net P&L, with at least 12 closed trades. May–September is evaluated once as rolling/pseudo-OOS. Neighbor stability is the fraction of all 12 variants with positive pseudo-OOS net P&L.

## Admission and ranking

Admission requires: after-cost operational target:stop at least 3.0; pseudo-OOS profit factor at least 2.0; expectancy at least +0.25R/trade; at least 30 closed trades (20 only if exceptionally broad/stable and flagged); max drawdown at most 6R; profitability on both QQQ and IWM or across three named market regimes; positive in at least 60% of pseudo-OOS months; positive at 1.5× fees and slippage; at least 60% positive neighboring settings; and largest winner no more than 25% of gross profit. Clearing the floors does not end the search; admitted attempts are ranked by robust after-cost P&L, PF, expectancy, stability, sample size, drawdown, and concentration.
