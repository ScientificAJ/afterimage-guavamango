# Attempt 009 — breadth-confirmed multi-day ETF channel breakout

Attempt 008 showed that ranking existing momentum was not sufficient, especially in 2025. Attempt 009 is a materially different daily time-series hypothesis: trade only a newly completed channel breakout, aligned with SPY and broad ETF participation.

At each completed daily bar, classify risk-on when SPY is above its prior-inclusive 50-session SMA and at least five of seven tradable ETFs are above their own 50-session SMA; classify risk-off symmetrically. In risk-on, select the ETF with the largest close above its prior 10- or 20-session high. In risk-off, select the largest close below its prior 10- or 20-session low. Do nothing without a new breakout.

Enter at the next session open. Use ATR(14), maximum $10,000 notional, one bp adverse slippage per side, $0.005/share/side, a 0.50 or 0.75 ATR stop, a cent-rounded after-cost target of at least 3R, stop-first daily precedence, five-session timeout, and maximum one position.

The fixed development family is `bo_n10_a50_h05`, `bo_n10_a75_h05`, `bo_n20_a50_h05`, and `bo_n20_a75_h05`. Evaluate only already-revealed 2023–2025 for expanding selection and final screening. Do not consume a fresh year unless a rule first clears the economic gates in development with at least 60 trades and positive 2024 and 2025 validation evidence.
