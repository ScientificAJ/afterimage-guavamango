# Attempt 016 — broad-state growth/cyclical execution

Attempt 015's revealed symbol decomposition showed positive development expectancy for QQQ, IWM, XLK, and XLY selections, while XLE, XLF, and XLV selections were negative. Attempt 016 tests a distinct state-versus-instrument hypothesis: all seven ETFs define broad risk-on, but execution rotates only among the growth/cyclical cluster.

Require SPY above its 50-session SMA and above its close ten sessions earlier, five or six of seven positive 20-session ETF returns, and at least 2% dispersion across all seven. Select the strongest completed 20-session return among QQQ, IWM, XLK, and XLY. Enter long next session.

Variants cross breadth five/six with stops 1.00/1.25 ATR: `gc_b5_a100_h05`, `gc_b5_a125_h05`, `gc_b6_a100_h05`, `gc_b6_a125_h05`. Hold five sessions with the established $10,000 cap, one-bp slippage, $0.005/share/side, after-cost 3R target, stop-first precedence, and one-position maximum.

Use revealed 2023–2025 for development. Require n>=60, PF>=2, expectancy>=+0.25R, DD<=6R, positive 2024 and 2025, positive at 1.5x costs, and >=60% positive neighbors before freezing for fresh outcomes.
