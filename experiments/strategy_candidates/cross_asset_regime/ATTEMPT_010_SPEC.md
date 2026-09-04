# Attempt 010 — broad-trend pullback resumption

This fixed family tests continuation after a controlled one-session countertrend pullback, rather than buying an extended rank or a new breakout. It is evaluated first on already-revealed 2023–2025 only.

At each completed daily bar, require SPY and at least five of seven tradable ETFs to be on the same side of their 50-session SMAs. Rank the ETFs by the prior session's 20-session return and require at least two percentage points of cross-sectional dispersion. In risk-on, select the prior-session leader and require the current close to pull back while remaining above its 20-session SMA. In risk-off, select the prior-session laggard and require the symmetric rebound while remaining below its 20-session SMA.

The four predeclared variants combine minimum pullback depth of 0 or 0.25 ATR(14) with stop distance 0.50 or 0.75 ATR: `pb_d00_a50_h05`, `pb_d00_a75_h05`, `pb_d25_a50_h05`, and `pb_d25_a75_h05`. All use next-session entry, five-session maximum hold, $10,000 maximum notional, one bp adverse slippage per side, $0.005/share/side, a cent-rounded after-cost target of at least 3R, stop-first daily precedence, and maximum one position.

Require at least 60 development trades, PF at least 2, expectancy at least +0.25R, drawdown at most 6R, positive 2024 and 2025 validation, and positive 1.5x-cost P&L before spending an unused outcome partition.
