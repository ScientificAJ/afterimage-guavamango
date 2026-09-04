# Evidence levels

- `replays/`: deterministic synthetic engineering fixtures used for the judge demo (L3/L4 controls, not performance evidence).
- `research/`: hash-bound Alpaca bars, derived strategy outcomes, and historical option trade-bar validation. Trade bars are not historical bid/ask quotes or broker P&L.
- `tournament/`: strategy-derived chronological evaluation results. The current partition has been revealed and is not described as developer-blind or untouched.
- `paper/`: sanitized Alpaca paper receipts created only during controlled validation (L5).
- `submission/`: independently verifiable export envelopes.

Current research receipts:

- `research/spy-real-v1-manifest.json`: 32,346 real SPY IEX bars, train/embargo/evaluation partitions, raw-row hashes, and strategy-derived results.
- `research/spy-option-trade-bars-v2.json`: 12/12 real historical option paths with the disclosed trade-bar/slippage boundary, -$126 aggregate result, outcome distribution, 95% mean-return interval, coverage, censoring, and drawdown.
- `research/spy-live-model-receipt-v1.json`: exact live Featherless model routes, response hashes, abstentions, and prosecutor challenge over an outcome-hidden real candidate.
- `research/forward-paper-trial-v1.json`: risk, code/configuration, data, model, time-window, and no-bypass commitments frozen before the controlled paper window.
- `tournament/spy-real-v1-results.json`: chronological evaluation with `NO_CHAMPION`, not a hand-written +3R/-1R sequence.

Recorded fixtures are not live returns. Secrets and unredacted account identifiers must never be placed here.
