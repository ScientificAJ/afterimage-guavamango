# Strategy 2 — Volatility Premium / Defined-Risk Options

Date: 2026-09-04

## Outcome

No candidate was promoted. Nine immutable SPY/QQQ option attempts were tested and
all had negative after-cost rolling/OOS expectancy. The best result, a causal
volume-screened trade-VWAP opening-reversal sensitivity, closed 40 trades for
-$355.40, -0.01698R/trade, 40.0% hit rate, 0.894 PF, and 4.254R maximum drawdown.
It failed the mandatory PF >=2.0, expectancy >=+0.25R, cross-symbol/regime,
60%-positive-fold, 1.5x-cost, and 60%-positive-neighbor floors. It is not a
consolation winner.

The search covered trend-filtered put credit spreads, momentum debit verticals,
compression iron condors, expansion and compression long strangles, single-long
momentum, single-long reversal, reversal debit verticals, and the final causal VWAP
reversal check. Operational targets were at least three times modeled stop risk in
Attempts 02-09. Attempt 01's legacy target/stop was only 0.333 and also failed.

Historical quote fills are not claimed. Attempts 01-08 use adverse synchronized
option trade-bar extremes plus explicit $0.01 per contract-side slippage and $0.03
fees. Attempt 09 uses liquid trade VWAP with $0.02 per side and delays exits to the
next liquid bar after stop/target detection. Both SPY and QQQ and three of four months
were negative in that most favorable sensitivity; all three neighboring parameters
were negative.

The official Alpaca CLI fetched only read-only market/contract data. The paper
account's ACTIVE Level-3 capability and exact MLEG request shape were validated by
client-only `--dry-run`; no order was placed, canceled, replaced, or exercised.

Full evidence and implementation constraints are in
`experiments/strategy_candidates/volatility_premium/REPORT.md`. Machine-readable
Attempts 01-09 are indexed by `results/attempt-ledger.json`, ledger hash
`f4452ae1c30914dbf2b06868b7c9ed0622189da82c1d53e7f406ce7ec8545854`.
