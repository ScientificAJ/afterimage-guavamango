# Event/flow strategy-search specification

This lane searches multiple causal, liquid-ETF strategy families against authenticated
Alpaca market data.  Every signal is computed from completed bars, entries use the next
bar's open, fills include adverse slippage and per-share fees, and ambiguous OHLC exits
take the stop first.  Every position has an after-cost target of at least 3R for 1R risk.

Research chronology is fixed before scoring: development through 2024, monthly expanding
walk-forward validation during 2025, and a final pseudo-out-of-sample window from January
through September 2026.  A final pseudo-OOS result is never called untouched after it has
been viewed.  Failed attempts remain in an append-only, hash-chained ledger.

The search begins with two materially different ideas:

1. **Opening flow leadership** — after completed opening bars, require market breadth and
   trade the strongest aligned sector ETF on unusual opening participation.
2. **Compression release** — after a multi-day contraction inside an established trend,
   trade a completed range breakout on the next bar.

If neither survives, the implementation permits further predeclared attempts without
rewriting history.  Admission floors are PF >= 2.0, expectancy >= 0.25R, normally >= 30
validation trades, drawdown <= 6R, breadth across at least two underlyings or three regimes,
positive >= 60% of months/folds, positive at 1.5x costs, >= 60% profitable neighboring
settings, and no single trade above 25% of gross profit.  These are floors, not objectives.
