# Attempt 013 — broad-consensus long-only ETF rotation

Revealed development diagnostics show that short legs consistently destroy cross-sectional momentum performance. Attempt 013 predeclares an asymmetric causal policy: hold cash in risk-off and rotate long only when broad risk-on evidence agrees.

At each completed daily bar, require SPY above its 50-session SMA and above its close ten sessions earlier, at least five or six of seven ETF 20-session returns positive, and at least two percentage points of cross-sectional dispersion. Select the strongest ETF by completed 20-session return and enter next session open.

The fixed family crosses breadth 5/7 or 6/7 with stop 0.75 or 1.00 ATR(14): `lo_b5_a75_h05`, `lo_b5_a100_h05`, `lo_b6_a75_h05`, and `lo_b6_a100_h05`. Hold at most five sessions. Use $10,000 maximum notional, one bp adverse slippage per side, $0.005/share/side, net target at least 3R, stop-first daily precedence, and maximum one position.

Screen revealed 2023–2025 first. Require at least 60 trades, PF at least 2, expectancy at least +0.25R, drawdown at most 6R, positive 2024 and 2025 evidence, positive 1.5x costs, and at least 60% positive neighboring rules before freezing for a fresh partition.
