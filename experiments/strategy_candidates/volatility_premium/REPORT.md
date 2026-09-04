# Defined-Risk Options Strategy Search Report

Date: 2026-09-04

## Decision

**No implementation-ready candidate is supported. Do not promote or paper-trade
any tested options strategy.**

Nine immutable attempts were evaluated. All had negative rolling/OOS expectancy
after modeled costs. The strongest result was the final causal, volume-screened
trade-VWAP reversal sensitivity: 40 closed SPY+QQQ trades, -$355.40 net,
-0.01698R/trade, 40.0% hit rate, 0.894 profit factor, and 4.254R maximum drawdown.
It met the 3:1 operational target/stop, sample, drawdown, and profit-concentration
floors, but failed the mandatory PF, expectancy, cross-symbol/regime, monthly,
1.5x-cost, and neighboring-parameter floors. Its mean-R 95% t interval was
[-0.13649, 0.10253], so it is also statistically inconclusive rather than a near
promotion.

The original SPY volatility-risk-premium attempt and every materially distinct
pivot remain in the hash-chained ledger. There is no consolation winner.

## Admission floors

The final policy required all of the following after costs: operational target/stop
at least 3.0, rolling pseudo-OOS PF at least 2.0, expectancy at least +0.25R/trade,
at least 30 closed trades, maximum drawdown no greater than 6R, positive evidence
on both liquid underlyings or at least three monthly regimes, positive expectancy
in at least three of four monthly folds, positive net P&L at 1.5 times modeled
fees/slippage, at least two of three neighboring settings positive, and no single
trade above 25% of gross profit. These were floors, not a stopping rule.

## All immutable attempts

Attempts 02-09 use researcher-visible May-August 2026 monthly pseudo-OOS folds on
SPY and QQQ; they are not developer-blind or untouched. Attempt 01's originally
untouched July-September segment was revealed before the pivots and was never reset.

| Attempt | Structure/signal | n | Net P&L | Exp./R | Hit | PF | Max DD | Max DD/R | 1.5x-cost net | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 01 | SPY put credit spread / trend VRP | 32 | -$673.84 | -0.04718 | 25.0% | 0.128 | $674.72 | n/a | n/a | reject |
| 02 | directional debit vertical / momentum | 8 | -$900.96 | -0.44404 | 0.0% | 0.000 | $900.96 | 3.552 | -$917.44 | reject |
| 03 | compression iron condor | 45 | -$1,606.80 | -0.10724 | 2.2% | 0.009 | $1,606.80 | 4.826 | -$1,792.20 | reject |
| 04 | expansion long strangle | 12 | -$1,179.44 | -0.08030 | 41.7% | 0.326 | $1,392.96 | 1.200 | -$1,204.16 | reject |
| 05 | single long option / momentum | 21 | -$2,641.26 | -0.19800 | 23.8% | 0.159 | $2,772.96 | 4.217 | -$2,662.89 | reject |
| 06 | compression long strangle | 47 | -$1,469.64 | -0.08782 | 10.6% | 0.188 | $1,753.92 | 4.776 | -$1,566.46 | reject |
| 07 | single long option / reversal | 16 | -$1,439.96 | -0.14747 | 18.8% | 0.371 | $1,439.96 | 2.360 | -$1,456.44 | reject |
| 08 | debit vertical / reversal | 9 | -$758.08 | -0.38943 | 0.0% | 0.000 | $758.08 | 3.505 | -$776.62 | reject |
| 09 | causal VWAP single-long / reversal | 40 | -$355.40 | -0.01698 | 40.0% | 0.894 | $2,096.08 | 4.254 | -$436.60 | reject |

Attempt 09 is the only adequate-sample result close to break-even, but both
underlyings were negative: QQQ n=25, -$220.50, -0.02047R, PF 0.908; SPY n=15,
-$134.90, -0.01118R, PF 0.857. Only June was positive (n=11, +$993.34,
+0.12515R, PF 3.894); May, July, and August lost $264.36, $523.78, and $560.60.
All three neighbors were negative: conservative -0.03632R/PF 0.967,
balanced -0.04389R/PF 0.848, and fast -0.01698R/PF 0.894. Its largest winning
trade was 17.39% of gross profit and its 1.5x-cost result was -$436.60.

## Data, fills, and leakage controls

The original cache contains 8,617 SPY contract records and 99,270 option bars.
The SPY+QQQ pivot cache contains 332 stock sessions, 55,244 contract records,
437 predeclared structures, and 336,078 option bars. Its SHA-256 content hash is
`06b8ff76a2d12f3142aa1e976e621c815c71da4a1e313f7e11a3d4b215435aa9`.
The reversal supplement contains 75 structures and 22,279 option bars, is linked
to that base cache, and has content hash
`d2917a987aa94de0901e420879f469da80c87922dc8e99616b475dfb20628c25`.
All were acquired through authenticated read-only commands from the pinned official
Alpaca CLI 0.0.14. No order was submitted, replaced, canceled, or exercised.

Attempts 01-08 use synchronized 5-minute option trade-bar extremes: debit entries
pay long highs and receive short lows; exits receive long lows and pay short highs.
Credit structures reverse those adverse extremes. Each contract side adds $0.01
slippage and $0.03 fees. These are deliberately adverse bounds, not historical
quotes or guaranteed executable combo fills.

Attempt 09 checks whether the conclusion is solely an artifact of independent bar
extremes. Entry and exit bars require at least 10 contracts and 5 trades. Entry is
trade VWAP plus $0.02; stop/target detection occurs on a later liquid bar close;
execution is delayed to the next liquid bar at trade VWAP minus $0.02. This avoids
same-bar hindsight. Trade VWAP is still not a bid/ask quote or guaranteed fill.
Its continued negative result is the most favorable honest sensitivity available.

Contract metadata is a present-day active/inactive catalog, not a point-in-time
chain snapshot. Historical quoted spread, open interest, tradability, and market
depth are therefore not asserted. The monthly pivots use April-to-prior-month
training information for selection except Attempt 09, whose fast family was fixed
before scoring that final sensitivity. Because the researcher had already seen the
shared period, every pivot is labeled researcher-visible pseudo-OOS.

## Alpaca Level-3 feasibility

Structural feasibility is confirmed; efficacy is not. The authenticated paper
account was ACTIVE, had effective options level 3, and was not trading-blocked. The
official CLI serialized a two-leg `mleg` day-limit credit-spread request with opening
position intents and terminal `--dry-run`; its artifact explicitly records
`submitted: false`. Alpaca's supported multi-leg shape is therefore implementable,
but the tested strategies do not justify execution. The saved example symbols and
prior-close quote-derived limit must never be reused as a live order.

Long-option attempts are structurally simpler Level-3-compatible day limit orders.
They likewise remain disabled because none met efficacy gates. A production caller
would still require fresh live quotes, quote-age and spread limits, contract status,
buying-power checks, and serialized execution, none of which converts these negative
historical results into a recommendation.

## Implementation contract

There is deliberately no production integration contract. The isolated package is
runnable research evidence only. `verdict: rejected` and every failed gate in each
attempt artifact are hard disables. `results/attempt-ledger.json` is the authoritative
immutable index; its ledger hash is
`f4452ae1c30914dbf2b06868b7c9ed0622189da82c1d53e7f406ce7ec8545854`.

The exact client-only MLEG serialization remains in
`results/alpaca_mleg_dry_run.json`. Any future options work should begin with a new
data period or genuinely new information set, append a new attempt ID, and never
rename these revealed folds as untouched.
