# Attempt 011 — credit-duration impulse with equity breadth

This materially distinct family tests whether weekly credit-versus-duration risk appetite leads multi-day equity continuation. The family is declared before HYG/TLT development data is acquired.

At each final trading session of a calendar week, compute the five-session change in the HYG/TLT close ratio. Risk-on requires that change to exceed the predeclared positive threshold, SPY's 20-session return to be positive, and at least four of seven equity ETFs to have positive 20-session returns. Risk-off uses the symmetric negative conditions. Trade QQQ long in risk-on and IWM short in risk-off at the next session open.

The family crosses ratio thresholds of 0.25% and 0.50% with ATR(14) stop multipliers of 0.75 and 1.00: `cd_t25_a75_h05`, `cd_t25_a100_h05`, `cd_t50_a75_h05`, and `cd_t50_a100_h05`. Maximum hold is five sessions. Execution uses maximum $10,000 notional, one bp adverse slippage per side, $0.005/share/side, cent-rounded after-cost target at least 3R, stop-first daily precedence, and maximum one position.

Acquire authenticated Alpaca HYG/TLT daily development bars for already-revealed 2023–2025 only. Require at least 60 trades, PF at least 2, expectancy at least +0.25R, drawdown at most 6R, positive 2024 and 2025 expanding validation, and positive 1.5x-cost P&L before freezing a rule and consuming a fresh outcome partition.
