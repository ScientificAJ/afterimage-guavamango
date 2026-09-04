# Strategy-candidate search: final disposition

## Outcome

No strategy is admitted for paper execution. Nine frozen attempts covered failed-auction mean reversion, cross-index VWAP trend, compression/gap expansion, multi-day trend, direct-ETF execution comparisons, pullback/resumption, relative-value convergence, and relative momentum. Four date partitions were reserved for fresh family evaluations, while the two direct-ETF comparisons are explicitly labeled pseudo-OOS and never presented as untouched holdouts.

The strongest honest result was attempt 005, cross-index VWAP trend executed directly in SPY/QQQ/IWM shares: 34 pseudo-OOS trades, +$444.05 net, +0.1114R expectancy, PF 1.3086, and 7.7177R max drawdown. It remained profitable at 1.5x costs (+$219.68, PF 1.1426), but failed the fixed floors of PF >=2, expectancy >=+0.25R, and drawdown <=6R. It was positive in only 2/5 folds and 1/3 months; just 1/6 parameter neighbors was positive. IWM generated +$596.68, while QQQ lost $167.87 and SPY contributed only $15.24. That is not a deployable edge.

## Ranked evidence

| Rank | Attempt | Structure | n | Net P&L | Exp/R | PF | Max DD R | Disposition |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 | 005 | Cross-index trend, direct ETFs | 34 | $444.05 | 0.1114 | 1.3086 | 7.7177 | Reject |
| 2 | 006 | Multi-day trend, direct ETFs | 118 | $249.71 | 0.0157 | 1.0272 | 39.7601 | Reject |
| 3 | 008 | Relative-value convergence pair | 26 | -$138.57 | -0.0533 | 0.8447 | 4.2018 | Reject |
| 4 | 009 | Relative-momentum pair | 48 | -$1,163.86 | -0.2425 | 0.4441 | 12.0489 | Reject |
| 5 | 007 | Pullback/resumption, direct ETFs | 69 | -$2,051.07 | -0.2823 | 0.5302 | 26.7960 | Reject |
| 6 | 004 | Multi-day trend, option verticals | 95 | -$1,250.10 | -0.5310 | 0.6872 | 83.1059 | Reject |
| 7 | 001 | Failed-auction option verticals | 17 | -$204.20 | -0.0491 | 0.2341 | n/a | Reject |
| 8 | 002 | Cross-index trend, option verticals | 18 | -$268.80 | -1.1291 | 0.1198 | n/a | Reject |
| 9 | 003 | Compression/gap option verticals | 0 | $0.00 | 0.0000 | n/a | 0.0000 | Reject: sparse |

## Options versus direct ETFs

The like-for-like implementation comparisons consistently favored direct ETF execution, but did not create an admissible signal:

- Cross-index VWAP trend: options lost $268.80 at PF 0.1198; direct ETFs made $444.05 at PF 1.3086 on the fixed pseudo-OOS comparison.
- Multi-day trend: options lost $1,250.10 at PF 0.6872; direct ETFs made $249.71 at PF 1.0272 on the fixed pseudo-OOS comparison.

Historical option trade bars have no contemporaneous NBBO, synchronized legs are sparse, and adverse per-leg fills plus fees dominated the short-horizon verticals. Direct execution removed that drag but still left weak, unstable signal quality.

## Validation and execution contract

- Signals use completed bars only. Entries wait for the next stock/option bar to complete.
- Rolling outer test slices are chronological and non-overlapping, with embargoes before OOS. Parameter selection occurs only in earlier training or nested validation dates.
- Every explicit bracket strategy solves its target and stop after modeled costs for an operational target:stop of at least 3.0. Gapped stops retain worse fills; targets receive no improvement; same-bar stock ambiguity resolves to the stop.
- Base costs and 1.5x cost stress are recorded for the later candidates. Option candidates additionally preserve a punitive bar-extreme stress where applicable.
- Raw Alpaca CLI caches, results, reports, dry-run payloads, and SHA-256 hashes are retained. Missing synchronized option legs are excluded and counted, never imputed.
- Every order artifact is non-submitting (`submission_allowed=false`) and its CLI arguments end in `--dry-run`. Pair candidates explicitly flag non-atomic legging risk. No paper or live order was placed.

## Reproducibility

Run the scoped test suite:

```bash
PYTHONPATH=.:src UV_CACHE_DIR=/tmp/alpacaman-mean-reversion-uv-cache uv run pytest -q experiments/strategy_candidates/mean_reversion/tests
```

Each `run_*.py` file reproduces its candidate from the retained cache. Passing `--fetch` refreshes only the authenticated, read-only Alpaca historical inputs for runners that expose that flag. The append-only attempt index and immutable artifact hashes are in `attempts/ledger.json`; the complete ranked metrics are in `leaderboard.json`.

## Recommendation

Do not submit even a paper order from these candidates. The next research cycle should start with a new, predeclared hypothesis and a new date partition or higher-fidelity quote data; it should not tune attempt 005 against its revealed pseudo-OOS folds.
