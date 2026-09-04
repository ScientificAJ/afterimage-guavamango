# AFTERIMAGE cross-asset/regime strategy search — final report

## Verdict

**No candidate is admitted for production.** Seven predeclared/pivoted attempts were evaluated with completed-bar signals, next-bar execution, explicit exits, costs, and chronological evidence controls. Attempt 005 was the strongest 2026 result, but its exact frozen rule failed the previously unused 2025 backward validation. Attempt 006 had strong but inadequate 2024 evidence, and the exact higher-activity rule subsequently failed fresh 2023 validation in attempt 007. The defensible outcome is rejection, not a consolation winner.

## Attempt ledger summary

| Attempt | Family / instrument | Selected rule | Evaluation evidence | n | Net P&L | Exp/R | PF | Max DD/R | Final status |
|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 001 | Intraday breadth rotation / QQQ-IWM debit vertical | `b6_spy10_h07_3r` | Rolling OOS | 27 | $-1,997.20 | -0.363 | 0.00 | not admission-safe | REJECT |
| 001 | Same | same | Original untouched Aug-Sep holdout | 3 | $-183.80 | -0.266 | 0.00 | 0.80 | REJECT |
| 002 | Confirmed overnight gap / debit vertical | `gap_b4_m10_s25` | May-Sep pseudo-OOS | 21 | $-475.60 | -0.482 | 0.44 | 11.73 | REJECT |
| 003 | Sector-to-index lead-lag / debit vertical | none | May-Sep pseudo-OOS | 0 | $0.00 | 0.000 | 0.00 | 0.00 | REJECT: option-bar coverage |
| 004 | Sector-to-index lead-lag / ETF shares | `equity_b4_g10_s15` | May-Sep pseudo-OOS | 17 | $-55.96 | -0.201 | 0.58 | 5.18 | REJECT |
| 005 | Confirmed overnight gap / ETF shares | `equity_gap_b4_m10_s15` | 2026 rolling evidence | 37 | $581.48 | 0.930 | 2.82 | 4.00 | provisional 2026 pass only |
| 005 | Exact frozen rule | same | Fresh 2025 backward validation | 55 | $47.83 | 0.056 | 1.07 | 11.31 | **REJECT** |
| 005 | Provenance-labeled diagnostic pool | same | 2025 backward + 2026 rolling | 92 | $629.31 | 0.408 | 1.65 | 11.31 | REJECT; not untouched OOS |
| 006 | QQQ-only regime-conditioned sector-confirmed gap / shares | `qqq_regime_b5_m10_c4_s15` | Fresh 2024 outcome validation | 9 | $183.91 | 1.226 | 3.72 | 2.00 | **REJECT: inadequate sample/month stability** |
| 007 | Exact higher-activity QQQ regime rule / shares | `qqq_regime_b5_m10_c3_s15` | Fresh 2023 outcome validation | 40 | $108.75 | 0.160 | 1.23 | 9.00 | **REJECT** |
| 007 | Same exact rule | same | 2023 fresh + revealed 2024 diagnostic pool | 63 | $497.43 | 0.468 | 1.75 | 9.99 | REJECT; diagnostic only |

## Attempt 005 evidence reconciliation

The 2026 rolling sample is 37 trades: March-April expanding-fold validation plus the frozen May-September pseudo-OOS slice. The latter alone is 22 trades, +$221.18, +0.606R expectancy, PF 2.02, and 3.00R drawdown. Neither number is relabeled as untouched evidence.

Before any earlier bars were acquired, the exact selected rule was frozen under SHA-256 `fbf67ec3cefd371533ef83d57dc74939c97b52ac1c1b649ff5996b6568c2fd98`. Its first and only evaluation on previously unused 2025 bars produced 55 trades, +$47.83, +0.056R, PF 1.07, and 11.31R drawdown. It fails the PF, expectancy, drawdown, and positive-month floors.

Stress and stability on that fresh extension:

- 1.5x modeled costs: +$38.29, +0.045R, PF 1.06.
- Base fees with two additional bps of slippage per side: -$53.29, -0.041R, PF 0.93.
- One additional 15-minute entry delay: +$76.34, +0.082R, PF 1.12.
- QQQ: 22 trades, +$175.01, +0.477R, PF 1.81; IWM: 33 trades, -$127.18, -0.224R, PF 0.71.
- Seven of twelve 2025 months were positive (58.3%). Three of four lagged-SPY-regime/direction buckets were nominally profitable, but none reached PF 2; risk-on bullish trades lost $110.00 at PF 0.51.
- Largest winner was 7.63% of fresh-extension gross profit. The operational minimum target:stop was 3.00057 after modeled fees and slippage.

## Final sequential pivot: attempt 006

After attempt 005 failed, its revealed 2025 QQQ strength and weak risk-on-bullish cell were used only to form a new hypothesis. Before any 2024 outcome was evaluated or any new 2024 acquisition, the QQQ-only family and three one-factor neighbors were frozen under hash `45227af6bc0598473d4e37a4faa20bd67350727a85bbbfc67fbbbbc8ed65c437`.

The focal rule required 5/7 aligned overnight gaps, 0.10% direction-adjusted mean gap, a confirming QQQ first bar, 4/5 confirming sector first bars, and exclusion of only lagged-SPY risk-on bullish entries. Its once-evaluated 2024 outcome result was 9 trades, +$183.91, +1.226R, PF 3.72, 2.00R drawdown, and after-cost target:stop 3.00024. It remained profitable at 1.5x costs (+$142.68, PF 2.98), two additional bps per side (+$162.04, PF 2.90), and one-bar entry delay (+$115.66, PF 2.37).

The focal nevertheless fails admission: only 9 trades versus the 30-trade floor and only 5/9 represented months positive (55.6% versus 60%). Each allowed regime was positive, all three predeclared neighbors were positive, and the largest win was 20.24% of gross profit, but these do not cure sample inadequacy. The most active neighbor had 23 trades and PF 3.10; it is not substituted or promoted because 2024 was not a selection set.

## Final temporal validation: attempt 007

The revealed most-active 2024 neighbor was used only to generate one final hypothesis. Its exact parameters were frozen without modification under hash `87a27dc2687918a04b6b5a5aa8e474ea88aec6381c71280fb5c38dd3dcea6844` before any 2023 outcome was computed or any new 2023 acquisition.

Fresh 2023 evidence was adequate in count but failed robustness: 40 trades, +$108.75, +0.160R, PF 1.23, and 9.00R drawdown. Seven of twelve months were positive (58.3%), and only two of three allowed regime cells were profitable. At 1.5x costs it retained only +$50.82 and PF 1.10; two additional bps per side produced -$86.55/PF 0.85, while one extra entry bar produced -$90.03/PF 0.82.

The separately labeled 2024 sensitivity was n=23, +$388.68, +1.003R, PF 3.10, and 4.00R drawdown. Combining it with the fresh 2023 outcome gives n=63, +$497.43, +0.468R, PF 1.75, and 9.99R drawdown—still below the PF floor and above the drawdown ceiling. The pool is diagnostic only and does not overwrite the failed fresh result.

## Complete variant audit

Every predeclared variant, including sample count, net P&L, expectancy/R, PF, hit rate where applicable, drawdown, and cost stress, remains preserved in the following research outputs:

| Attempt | Variants | Human-readable audit | Machine-readable result |
|---:|---:|---|---|
| 001 | 8 | `REPORT.md` | `results/backtest.json` |
| 002 | 12 | `ATTEMPT_002_REPORT.md` | `results/gap_backtest.json` |
| 003 | 12 | `ATTEMPT_003_REPORT.md` | `results/leadlag_backtest.json` |
| 004 | 12 | `ATTEMPT_004_REPORT.md` | `results/equity_backtest.json` |
| 005 | 12 | `ATTEMPT_005_REPORT.md` | `results/equity_gap_backtest.json` |
| 005 frozen extension | 1 exact rule + 3 execution stresses | `FRESH_EXTENSION_REPORT.md` | `results/frozen_extension_2025.json` |
| 006 | 4 | `ATTEMPT_006_REPORT.md` | `results/attempt006_backtest.json` |
| 007 | 1 exact rule + 3 execution stresses | `ATTEMPT_007_REPORT.md` | `results/attempt007_backtest.json` |

`results/attempt_ledger.json` preserves all seven attempts. It marks attempts 005 through 007 rejected at their final evidence stages. The attempt-005 neighboring grid was not evaluated on the newly revealed 2025 extension, preventing post-freeze tuning; its 100% positive-neighbor statistic is explicitly limited to the earlier 2026 rolling diagnostic. Attempt-006 neighbors were predeclared and evaluated simultaneously in 2024 as sensitivity only. Attempt 007 evaluated only the exact frozen rule on 2023.

## Production integration contract

Nothing should be integrated or enabled from this search because no rule clears the complete evidence bar. If new forward data later revalidates the frozen attempt-005 rule, its dormant contract is:

1. Consume only completed 15-minute regular-session bars for QQQ, IWM, XLK, XLF, XLE, XLV, and XLY. At 09:45 New York time, compare each 09:30 open with the prior completed regular-session close.
2. Require at least four of seven gaps in one direction, absolute direction-adjusted mean gap at least 0.10%, and both QQQ and IWM 09:30-09:45 candles confirming that direction. Select whichever of QQQ/IWM has the larger direction-adjusted overnight gap.
3. Emit at most one long/short ETF-share intent, capped at $10,000 notional. The research fill is the next 15-minute bar open with one bp adverse slippage and $0.005/share/side.
4. Compute a 0.15% raw-price stop. Cent-round the target outward until net target profit is at least 3.0 times the net stop loss after entry/exit slippage and fees. Stop wins any same-bar ambiguity; otherwise target, then six-bar timeout.
5. Route only through AFTERIMAGE's warrant, risk governor, serialized executor, short-availability check, lifecycle reconciler, and evidence vault. Block stale/missing bars, incomplete universe, invalid buying power, existing strategy exposure, and brackets that do not clear net 3R.
6. Preserve the frozen rule hash in every decision record. Any rule change requires a new attempt ID and new forward evidence; it must not inherit this validation label.

## Exact Alpaca MLEG dry-run artifact

`results/alpaca_mleg_dry_run.json` is an official Alpaca CLI 0.0.14 request-serialization dry run and submitted no order. Artifact SHA-256 is `6e1180d846494fb0c5cfbbe6a8cc5515f088649fb0e9a08bbe77e33cd3ea7fc6`.

- Quantity 1, day limit debit $2.76, `order_class=mleg`.
- Buy-to-open `IWM260908C00293000`; sell-to-open `IWM260908C00298000`.
- Net modeled stop -$68.60, target +$206.40, after-cost target:stop 3.00875.
- CLI arguments end in `--dry-run`; artifact field `submitted` is `false`.

This artifact validates the exact MLEG request shape required by the original options research mandate. It is not a recommendation to trade the rejected option strategy or the rejected share strategy.

## Data and reproducibility

- Real data source: authenticated official Alpaca CLI read-only endpoints; 15-minute IEX bars and Alpaca historical option trade bars/contracts.
- The 2025 cache contains 61,310 raw rows and has content hash `b1c23daec0c3743086b476a79a8fd3406bd1eb14aca6cb5b5d621a2135931a23`.
- Frozen-extension result hash: `50f081fbacea13bcc5889a169502da2189465389b428f8997a8a28ddf3d5e662`.
- Reproduce the cached extension with `.venv/bin/python experiments/strategy_candidates/cross_asset_regime/validate_frozen_extension.py`; add `--fetch` only to reacquire data from Alpaca.
- The attempt-006 2024 cache contains 60,793 raw rows with hash `aaa56b7c57ad6d32398547c507d24d4b05017d318427d8b054eecad1f1b5ef32`; its result hash is `18a0901f1408cf08a6b0bab118a3669339aa41c45947a0f3fc8143ad79510f0f`.
- Reproduce attempt 006 from cache with `.venv/bin/python experiments/strategy_candidates/cross_asset_regime/run_qqq_regime_extension.py`.
- Attempt 007's 2023 cache hash is `75928f42e5d4d4fbed6fb616355620c0c0e030ce96af4621626cec782e8f0c2a`; its result hash is `f761cbae24f6a8b73fd1c59f44fe3c678888893a76fa533eb6437f8125bbe5b9`.
- Reproduce attempt 007 from cache with `.venv/bin/python experiments/strategy_candidates/cross_asset_regime/run_attempt007_validation.py`.

## Limitations

- The fresh extension is backward validation, not chronological forward OOS. Pooling it with 2026 is clearly labeled diagnostic.
- IEX is not SIP. Option trade bars are not NBBO quote replay. Fifteen-minute OHLC cannot determine intrabar path, so stop-first ordering is conservative.
- Equity short availability, borrow fees, market impact, queue position, and live spread are not modeled.
- Confidence intervals remain wide and regime buckets are small. Attempt 005's 2026 strength did not generalize sufficiently to 2025.
- Attempt 006 is especially sparse: each represented month has one focal trade. Late-2024 bars had existed only as warm-up inputs for the 2025 study, so 2024 is labeled fresh outcome validation rather than untouched data.
- Late-2023 bars likewise existed only as warm-up inputs for the 2024 study. Attempt 007 is labeled fresh outcome validation, not untouched-data validation.
