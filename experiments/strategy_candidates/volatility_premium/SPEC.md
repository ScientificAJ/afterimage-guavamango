# Volatility Premium Candidate Design

Date: 2026-09-04

## Goal and decision rule

Build and test one runnable, defined-risk SPY put-credit-spread candidate using only
historical information available before each signal. The candidate is eligible for
handoff only if the untouched chronological out-of-sample period has positive net
expectancy after conservative modeled costs and the result is not dependent on one
trade or one parameter family. A negative or underpowered result produces no
implementation-ready recommendation.

## Research partition and variants

Use real Alpaca SPY stock and option data. January through June 2026 is the research
period. Within it, use expanding walk-forward folds so that every scored training
trade was generated after the data used to choose its family. Freeze the family before
opening the untouched OOS period of 2026-07-01 through 2026-09-03.

Exactly three parameter families are declared before OOS:

1. `defensive`: 20-session close above SMA, short strike one daily-volatility unit
   below spot with a 1.0% floor, $5 wing, 5-9 DTE.
2. `balanced`: 20-session close above SMA, short strike 0.75 volatility units below
   spot with a 0.75% floor, $5 wing, 5-9 DTE.
3. `tight`: 10-session close above SMA, short strike 0.50 volatility units below spot
   with a 0.50% floor, $3 wing, 3-7 DTE.

Each family may emit at most one trade per session. The signal is evaluated at 10:00
ET from lagged daily features and intraday spot data ending no later than 10:00. Entry
uses the first synchronized option bar starting at or after 10:00 and therefore becomes
known only at that bar's end. Exit occurs on a 50% credit capture, a loss of 1.5 times
entry credit, or the last synchronized bar no later than 15:45 ET. No position is held
overnight.

The family freeze rule is highest aggregate walk-forward expectancy in R, with ties
broken by lower drawdown, greater sample size, then the fixed order above. No OOS data
may affect family selection.

## Historical execution model

Historical option quotes are not asserted. Contract selection uses Alpaca's present-day
inactive-contract metadata, which is disclosed as not a point-in-time chain snapshot.
Only contracts confirmed by the API and option trade bars are used.

For each synchronized 5-minute bar, entry credit is modeled with the short leg at its
bar low and the long leg at its bar high. Exit debit uses the short leg at its bar high
and the long leg at its bar low. Subtract $0.01 per leg per side and $0.03 per contract
per side. Reject non-positive entry credit, crossed synthetic values, missing bars, and
contracts without enough synchronized observations. This is deliberately adverse and
is labeled a trade-bar bound, not an executable quote reconstruction.

One R is the defined maximum loss: spread width minus entry credit, times 100, plus
round-trip fees and slippage. Quantity is one spread throughout the research comparison.

## Components and data flow

- `candidate.py`: pure feature, contract-selection, fill, P&L, metrics, walk-forward,
  and MLEG payload functions.
- `acquire.py`: authenticated read-only official Alpaca CLI acquisition with deterministic
  JSON caching. It never exposes a mutation command.
- `run_backtest.py`: reproducible orchestration that reads the cache, freezes a family,
  scores OOS once, and emits `results/backtest.json`.
- `dry_run.py`: selects a currently active two-leg structure and invokes only the
  official CLI `order submit ... --dry-run`, emitting `results/alpaca_mleg_dry_run.json`.
- `tests/`: unit and integration-contract tests, written before implementation.
- `REPORT.md`: assumptions, all variants, OOS metrics, limitations, feasibility, and
  implementation contract.

Raw cache records include source command, retrieval time, requested interval, and a
SHA-256 content hash. Results include the frozen family, partition boundaries, exclusions,
trade-level records, net P&L, expectancy/R, hit rate, maximum drawdown, and stability
checks.

## Alpaca feasibility contract

The live entry is a two-leg `mleg` day limit order with integer quantity: sell short put
to open and buy lower-strike put to open. Closing reverses the sides and uses
`buy_to_close` / `sell_to_close`. The candidate requires paper status ACTIVE, effective
options level at least 3, no trading block, fresh option quotes for live selection, and
policy-compliant liquidity. Historical bar prices are never reused as live limits.

No command in the candidate can submit or cancel an order. The sole validation path
ends in the official CLI's `--dry-run` option. Real paper execution remains serialized
by the parent after winner selection.

## Test and failure handling

Tests cover timestamp cutoffs, lagged feature construction, strike/expiry selection,
adverse price arithmetic, cost accounting, first-passage exits, family freeze isolation,
metric/drawdown calculations, payload schema, and the prohibition on non-dry-run order
commands. Malformed, missing, non-finite, or unsynchronized market data is excluded with
a machine-readable reason; it is never imputed.

## Approved pivot after Attempt 01 reveal

Attempt 01 is frozen as a rejected SPY put-credit-spread test. Its July-September
segment has been revealed and must never again be described as untouched. Preserve
its exact result bytes in a unique attempt artifact and an append-only hash-chained
ledger before scoring another idea.

The approved pivot adds QQQ and uses researcher-visible expanding monthly
walk-forward folds. For each May-August 2026 evaluation month, choose a parameter
family using pooled SPY+QQQ trades from April through the prior month, then score
only that family in the next month. Report pooled, per-symbol, per-month, and all
neighbor-family results. These are pseudo-OOS folds, not developer-blind evidence.

Three materially distinct structures are fixed before pivot scoring:

1. `directional_debit_momentum`: trend-aligned call debit vertical after a positive
   09:30-10:00 move or put debit vertical after a negative move. The three families
   use opening thresholds 0.75%/0.50%/0.30%, 20/20/10-session trends, $5/$5/$3
   wings, and 5-9/3-7/2-5 DTE respectively.
2. `compression_iron_condor`: four-leg iron condor only after lagged 5-session
   realized volatility is below a fixed fraction of 20-session volatility and the
   09:30-10:00 absolute move is below a fixed cap. The wide/balanced/tight families
   fix their compression ratio, opening cap, volatility-scaled short distance,
   wing, DTE, target, and stop before scoring.
3. `expansion_long_strangle`: buy a same-expiry OTM put and call after a large
   09:30-10:00 absolute move and a fixed lagged 5-day/20-day volatility-ratio
   floor. Conservative/balanced/fast families use 0.75%/0.50%/0.30% opening
   thresholds, 1.10/1.00/0.90 volatility-ratio floors, 0.25%/0.15%/ATM strike
   distance, 5-9/3-7/2-5 DTE, and 20%/25%/30% debit stops. This hypothesis was
   declared and tested before the shared pivot cache was acquired.

Debit entry pays the long-leg bar high and receives the short-leg bar low; debit
exit receives the long low and pays the short high. Iron-condor entry receives both
short lows and pays both long highs; exit reverses those adverse extremes. Every leg
side also incurs the original $0.01 slippage and $0.03 fee model.

Each pivot defines its stop-risk unit on net P&L after modeled fees/slippage and
requires an operational target exactly three times that stop. The final admission
floors, fixed before retrieval of the pivot cache, are: aggregate rolling pseudo-OOS
profit factor at least 2.0, expectancy at least +0.25R per trade, at least 30 closed
trades, maximum drawdown no greater than 6R, positive results on both underlyings or
in at least three distinct monthly regimes, positive expectancy in at least three of
four monthly folds (the integer threshold implied by 60%), positive net P&L after
raising all modeled fees and slippage to 1.5 times base, at least two of three (60%)
neighboring families positive, and no single trade above 25% of gross profit. These
are floors only: all attempts are ranked for stronger robust after-cost evidence and
the search does not stop at the first pass. Failure of any floor means no candidate.

## Post-failure extension hypotheses

After Attempts 02-04 were frozen and rejected, two further materially distinct
hypotheses were declared before scoring them. Because they were conceived after the
shared May-August cache had been used, their folds are explicitly exploratory
pseudo-OOS and are not reset or described as untouched.

1. `directional_long_momentum` buys only the ATM long leg from each predeclared
   momentum signal. It keeps the original three signal, DTE, and stop families but
   removes the capped vertical payoff and one leg of synthetic-bar execution noise.
2. `compression_long_strangle` buys the two inner strikes from each predeclared
   compression-condor signal, testing volatility expansion after a quiet open rather
   than selling the same regime. The three source families retain their fixed
   compression, strike, DTE, and 10%/15%/20% debit-stop settings.

Single-leg entry pays bar high plus $0.01, exit receives bar low minus $0.01, and
charges $0.03 per contract side. The long pair applies the same adverse two-leg
extremes and costs as the expansion strangle. Targets remain exactly three times
after-cost stop risk. No new market data or new family selection is used for these
two extensions; their inputs are the immutable pivot cache.

The equity 10:00-to-close control then showed a small positive mean-reversion signal
after large opening moves in all three fixed families, while the option momentum
attempt was negative. This motivated two more options attempts, declared before their
supplemental option bars were fetched: `directional_long_reversal` buys the nearest
ATM option opposite the opening move, and `directional_debit_reversal` buys the same
ATM option while selling the original fixed-width farther OTM option. Signals,
families, expirations, stops, targets, monthly walk-forward rule, and gate policy are
unchanged; only direction is reversed. The supplemental cache is hash-linked to the
original pivot cache and uses the same official read-only bar endpoint.

After Attempts 07-08 also failed, the final bounded sensitivity keeps the reversal
signal but fixes `momentum_fast` for all four monthly folds to avoid a sparse-family
selector. Entry must have at least 10 contracts and 5 trades in its 5-minute bar and
is modeled at trade VWAP plus $0.02. Stop/target detection uses a liquid bar close;
execution is delayed to the next liquid bar at trade VWAP minus $0.02, preventing a
same-bar hindsight fill. Time exits use the last liquid bar. Fees remain $0.03 per
contract side. All three fixed families are still scored as neighbor checks. This is
a causal fill sensitivity only: trade VWAP is not a historical bid/ask quote and the
May-August folds remain researcher-visible.
