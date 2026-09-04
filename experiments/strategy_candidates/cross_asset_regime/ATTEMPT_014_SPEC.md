# Attempt 014 — low-noise broad-consensus long rotation

Attempt 013 was close on expectancy but failed PF and drawdown. Attempt 014 predeclares a different regime state: participate only when broad long momentum coincides with low recent SPY noise.

Require SPY above its 50-session SMA and above its close ten sessions earlier, at least six of seven ETF 20-session returns positive, cross-sectional dispersion at least 2%, and the mean absolute SPY daily return over the last 20 sessions no greater than 1.2% or 1.6%. Select the strongest ETF and enter long next session.

Variants cross the two noise ceilings with 1.00 or 1.25 ATR stops: `lv_v12_a100_h05`, `lv_v12_a125_h05`, `lv_v16_a100_h05`, and `lv_v16_a125_h05`. Hold five sessions; use the same $10,000 cap, one-bp adverse slippage, $0.005/share/side, after-cost 3R target, stop-first daily precedence, and one-position limit.

Screen only revealed 2023–2025. Require at least 60 trades, PF at least 2, +0.25R expectancy, drawdown at most 6R, positive 2024 and 2025 validation, positive 1.5x-cost P&L, and 60% positive neighbors before any fresh evaluation.
