# Attempt 012 — slow weekly cross-sectional ETF rotation

Attempts 008–011 show repeated-entry/tight-stop churn. Attempt 012 predeclares a slower allocation mechanism: evaluate only the final trading session of each week, rank 60- or 120-session ETF returns, then hold up to ten sessions with a wide 1.5- or 2.0-ATR stop.

Risk-on requires SPY above its 100-session SMA, SPY's 20-session return positive, and at least four of seven ETF 60/120-session returns positive. Risk-off is symmetric. Require at least five percentage points of cross-sectional dispersion; select the strongest ETF long or weakest ETF short. Enter next session open.

Variants are `wk_rs60_a150_h10`, `wk_rs60_a200_h10`, `wk_rs120_a150_h10`, and `wk_rs120_a200_h10`. All use $10,000 maximum notional, one bp adverse slippage per side, $0.005/share/side, cent-rounded after-cost target at least 3R, stop-first daily precedence, and maximum one position.

Screen only revealed 2023–2025. Require at least 60 trades, PF at least 2, expectancy at least +0.25R, drawdown at most 6R, positive 2024 and 2025 validation, and positive 1.5x-cost P&L before any fresh-outcome evaluation.
