# Cross-asset breadth rotation debit-vertical design

## Objective

Test whether completed intraday breadth across seven liquid risk ETFs can select both direction and the stronger directional expression between QQQ and IWM, then execute that view with a defined-risk debit vertical. The result is research evidence, not authorization to trade.

## Frozen hypothesis family

At 10:30 New York time, after the 10:15–10:30 stock bar is complete, measure each symbol's return from its 09:30 bar open to its 10:15 bar close for QQQ, IWM, XLK, XLF, XLE, XLV, and XLY. A bullish regime requires a configured count of positive returns and a cross-sectional mean return of at least +0.10%. A bearish regime is the symmetric negative condition. If bullish, select the higher-return of QQQ and IWM; if bearish, select the lower-return one. Ties are resolved lexicographically.

The original four fixed-hold variants and their four predeclared 3R/1R exit neighbors are fixed before OOS is observed:

| Variant | Breadth | Lagged SPY regime | Hold |
|---|---:|---|---:|
| `b5_plain_h07` | 5 of 7 | none | 7 option bars |
| `b5_plain_h21` | 5 of 7 | none | 21 option bars |
| `b6_spy10_h07` | 6 of 7 | prior SPY close must be on the directional side of its trailing 10-session SMA | 7 option bars |
| `b6_spy10_h21` | 6 of 7 | prior SPY close must be on the directional side of its trailing 10-session SMA | 21 option bars |
| `b5_plain_h07_3r` | 5 of 7 | none | 3R target / 1R stop, 7-bar timeout |
| `b5_plain_h21_3r` | 5 of 7 | none | 3R target / 1R stop, 21-bar timeout |
| `b6_spy10_h07_3r` | 6 of 7 | prior SPY close must be on the directional side of its trailing 10-session SMA | 3R target / 1R stop, 7-bar timeout |
| `b6_spy10_h21_3r` | 6 of 7 | prior SPY close must be on the directional side of its trailing 10-session SMA | 3R target / 1R stop, 21-bar timeout |

For the 3R neighbors, nominal stop loss is 25% of entry debit and the target is the smallest cent price whose modeled net profit is at least three times the modeled net loss at the stop, after the full $2.60 round-trip fee. A stop is assumed first when an option bar's adverse paired-leg credit reaches the stop; a target is credited only when that adverse credit reaches the target. No threshold, universe, or exit changes are allowed after evaluation begins.

## Instrument and fills

Choose the earliest listed expiry from three through nine calendar DTE. Buy the nearest-strike call for bullish signals and nearest-strike put for bearish signals, then sell the same-expiry strike closest to $5 farther out of the money; require an exact $5 width. Enter at the first synchronized 15-minute option trade bar beginning at or after signal completion. Debit is the long-leg high minus short-leg low plus $0.06 spread slippage. Exit at the first synchronized bar at least the selected holding-bar count later using long-leg low minus short-leg high minus $0.06, floored at zero. Charge $0.65 per contract per side, or $2.60 round trip. Risk `R` is entry debit times 100 plus entry fees. Missing synchronized bars are excluded, never imputed. Permit at most one position at a time.

## Selection and holdout

Development covers 2026-01-02 through 2026-07-31. Expanding folds train through April, May, and June respectively and validate on the next month. Each fold chooses the highest training expectancy/R, then training net P&L, with at least eight scored training trades. The production candidate is frozen from pooled May–July validation results: highest expectancy/R, then net P&L, among variants with at least eight pooled validation trades. Robustness requires positive pooled validation expectancy and positive net P&L in at least two of three validation months; failing that criterion does not suppress the requested holdout measurement but forces a `REJECT` recommendation.

The final holdout is 2026-08-03 through 2026-09-03 and is evaluated once after code and family are frozen. Report every variant's full development diagnostic and the frozen candidate's untouched holdout trades, including sample count, net P&L, expectancy/R, hit rate, max drawdown, profit factor, fold stability, parameter sensitivity, exclusions, and limitations. Promotion requires operational target:stop at least 3.0 and aggregate rolling-OOS profit factor at least 3.0.

## Data, safety, and artifacts

All underlying bars, option contracts, option bars, current quotes, and account capability facts come from authenticated official Alpaca CLI reads. Cached market data contains no secrets and records commands, retrieval time, hashes, feed, adjustment, and date bounds. The exact MLEG artifact invokes the official CLI's `order submit ... --dry-run`; it must record `submitted=false` and validate that `--dry-run` is the sole terminal argument. No live or paper order submission is permitted.

The production integration contract consumes synchronized completed 15-minute bars and lagged daily state, emits a two-leg debit MLEG intent plus its precommitted exit mode, and remains subject to AFTERIMAGE's existing warrant, risk, max-position, and serialized execution gates.

## Adaptive attempt ledger

If the initial family fails, any materially distinct pivot must be appended to `results/attempt_ledger.json` before it is evaluated. Dates revealed by this initial attempt remain labeled revealed and can only be used as rolling/adaptive OOS for later attempts; they can never be relabeled untouched. With no later calendar data available, a pivot may be supported by nested or rolling walk-forward evidence but cannot manufacture another untouched holdout.
