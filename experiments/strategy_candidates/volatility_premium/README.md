# Defined-Risk Options Search (No Candidate)

This isolated package contains nine immutable real-data SPY/QQQ options attempts.
Every attempt failed the admission policy. Nothing here is authorized for paper or
live execution.

## Verify

From `/home/john/Alpacaman`:

```bash
XDG_CACHE_HOME=/tmp/volatility-premium-uv-cache \
  uv run pytest experiments/strategy_candidates/volatility_premium/tests -q

XDG_CACHE_HOME=/tmp/volatility-premium-uv-cache \
  uv run ruff check experiments/strategy_candidates/volatility_premium
```

The result runners are deterministic over their saved caches:

```bash
uv run python experiments/strategy_candidates/volatility_premium/run_backtest.py
uv run python experiments/strategy_candidates/volatility_premium/run_pivots.py
uv run python experiments/strategy_candidates/volatility_premium/run_extensions.py
uv run python experiments/strategy_candidates/volatility_premium/run_reversal.py
uv run python experiments/strategy_candidates/volatility_premium/run_vwap.py
```

Do not rerun an earlier result writer against a ledger that already contains its
attempt unless the artifact bytes are unchanged; the ledger rejects changed attempt
hashes. Acquisition scripts call only official Alpaca read paths. The sole order
command in `dry_run.py` is hard-gated to end in `--dry-run`.

## Evidence map

- `REPORT.md`: decision, all attempts, robustness, limitations, and feasibility.
- `SPEC.md`: strategy families, leakage labels, fills, and admission floors.
- `results/attempt-ledger.json`: hash-chained index of Attempts 01-09.
- `results/attempt-*.json`: complete trade, fold, symbol, month, neighbor, stress,
  concentration, and failed-gate evidence.
- `results/alpaca_mleg_dry_run.json`: exact non-submitting Level-3 MLEG serialization.
- `data/pivot_market_cache.json`: immutable SPY+QQQ shared pivot cache.
- `data/reversal_cache.json`: immutable hash-linked reversal supplement.
- `candidate.py`, `pivots.py`, `vwap.py`: pure fill, trade, metric, and fold engines.
- `acquire*.py`, `run_*.py`: read-only acquisition and reproducible scoring entrypoints.

The strongest attempt was the final causal VWAP reversal sensitivity (n=40,
-$355.40, -0.01698R/trade, PF 0.894). It still failed six mandatory floors. There
is no implementation-ready candidate.
