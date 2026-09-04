# Attempt 004 — lead–lag catch-up in liquid ETF shares

Attempt 004 directly tests whether option microstructure, rather than the cross-asset lead–lag hypothesis, caused attempt 003's zero-sample failure. It uses the same sector-to-index signal family and checkpoints but executes QQQ or IWM shares long/short with a $10,000 maximum notional.

The frozen neighborhood remains sector breadth {3,4} and directional lag {0.05%,0.10%}. Stop distance is {0.15%,0.25%,0.35%} of entry notional. Each trade enters at the next completed-bar open with one basis point adverse slippage and $0.005/share/side modeled fees. The bracket target is the smallest cent price whose after-cost profit is at least three times the after-cost nominal stop loss. Stop is assumed first if both bracket prices occur inside one 15-minute bar. A trade times out after six bars using the terminal close with adverse slippage. Chronological signals that overlap an open position are rejected.

January–April selects one of 12 variants with at least 20 trades. May–September is a single rolling/pseudo-OOS pass, not untouched. All high-but-attainable admission floors remain unchanged, including 1.5× fees/slippage stress and neighborhood stability.
