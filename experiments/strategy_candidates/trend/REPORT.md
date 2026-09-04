# AFTERIMAGE trend-options candidate: research report

## Verdict

**No candidate. Do not paper-trade this strategy.** The frozen trend rule is runnable and its one holdout option trade won, but the evidence fails two predeclared promotion gates: full-training proxy expectancy was negative and the option holdout contained only one trade. Real Alpaca option bars also made the selected rule worse in training: **-$366.60, -0.281R expectancy, 38.1% hit rate, $377.40 maximum drawdown over 21 trades**.

The complete, machine-readable ledger is in `results.json`; the structurally exact but deliberately non-submittable historical MLEG example is in `order-payload.json`.

## Data and protocol

- Source: `.afterimage/research/spy-real-v1.json`, SHA-256 `9b21ff12ee88a19aa73f19f003836645d87c1dd61b4e6e1207ad3b5e5d1144f7`, embedded dataset hash `2439c1579d9f3fc4f0286d6eed5e1acf2787799a32658423a8a28c828b986534`.
- SPY 5-minute IEX bars: 367 training sessions from 2025-01-02 through 2026-06-23; five-session embargo; 46 untouched-for-selection sessions from 2026-07-01 through 2026-09-03.
- Thirty-six variants were fixed across three trend families. Selection used only three chronological blocks inside training: 2025-08-06–2025-11-18, 2025-11-19–2026-03-06, and 2026-03-09–2026-06-23. The first 146 training sessions supplied warm-up/history and remained included in full-training metrics.
- Signals use completed bars only. A 10:00 ET signal reads bars timestamped 09:30–09:55; the modeled stock and option entry uses the close of the next bar timestamped 10:00, available at 10:05. Stops, targets, and time exits also use completed closes, never intrabar highs/lows.
- Underlying screening used one trade per session, $500 nominal risk per trade, a 0.25% stop, 0.50% target, 60-minute hold, and 2 bps round-trip impact. Those dollars are a selection proxy, not an option-fill claim.
- The frozen rule alone was then validated on real Alpaca historical option trade bars. Each debit vertical uses the earliest 2–7 calendar-DTE expiry, nearest-to-spot long, and same-expiry short 5–10 points away and closest to six points. Entry/exit charge $0.02 slippage per leg per fill plus a deliberately conservative $0.65 reserve per contract-side ($2.60 per spread round trip). Stop is 25% of entry debit, target is 50%, and time exit is 60 minutes.
- Read-only Alpaca preflight on 2026-09-04 confirmed an active paper account with $100,000 cash/equity/options buying power, approved/effective options level 3, zero positions, zero open orders, and execution disabled (`alpaca-cli/0.0.14`). No order was placed, replaced, or cancelled.

## Frozen rule and measured result

Training-only selection chose `opening_drive_vwap-62dcb6d54f`: at 10:00 ET require an absolute 09:30–10:00 drive of at least 0.45%, path efficiency at least 0.70, cumulative volume at least 1.0x the median of the prior 20 sessions' matching window, and the close on the directional side of cumulative bar VWAP. Bearish logic is symmetric.

| Evaluation | N | Net P&L | Expectancy | Hit rate | Max drawdown | Notes |
|---|---:|---:|---:|---:|---:|---|
| Full training, underlying proxy | 21 | -$772.53 | -0.074R | 47.6% | $2,080.52 | 10 wins / 11 losses |
| Walk-forward block 1, proxy | 1 | +$546.84 | +1.094R | 100.0% | $0.00 | too sparse |
| Walk-forward block 2, proxy | 7 | +$1,751.68 | +0.500R | 71.4% | $772.91 | 5 wins / 2 losses |
| Walk-forward block 3, proxy | 3 | -$1,851.86 | -1.235R | 0.0% | $1,851.86 | unstable late fold |
| Full training, real option bars | 21 | -$366.60 | -0.281R | 38.1% | $377.40 | 8 wins / 13 losses; 100% coverage |
| Chronological OOS, proxy | 1 | +$432.52 | +0.865R | 100.0% | $0.00 | one signal, 2026-08-03 |
| Chronological OOS, real option bars | 1 | +$49.40 | +0.939R | 100.0% | $0.00 | time exit; 100% coverage |

The training-option mean's approximate 95% t interval is **[-0.639R, +0.077R]**. Its 21 observations are insufficient to rule out zero, while the point estimate and P&L are negative. Fourteen option trades time-exited, seven stopped, and none reached the 50%-of-debit target. Direction was balanced (10 bullish, 11 bearish).

Cost stress does not rescue training: at $0.00/$0.01/$0.02/$0.03/$0.04 slippage per leg per fill, with the fee reserve held constant, training option P&L is respectively **-$198.60 / -$282.60 / -$366.60 / -$450.60 / -$534.60** and expectancy is **-0.153R / -0.218R / -0.281R / -0.343R / -0.404R**. The lone OOS winner remains positive under this range, but one observation has no stability value.

## Every tried variant

`D` is the drive threshold, `E` path efficiency, `RV` relative volume, and `B` breakout/reclaim buffer. All metrics below are full-training underlying-proxy results; `WF` lists each chronological block as `sample/expectancy R`. `results.json` contains every exact parameter and trade row.

| ID | Family | D | E | RV | B | N | Net $ | Exp R | Hit | Max DD $ | WF n/exp R |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| opening_drive_vwap-d1c978933e | opening_drive_vwap | 0.0025 | 0.55 | 0.8 | 0.0000 | 75 | -9766.89 | -0.260 | 45.3% | 9920.78 | 10/-0.514; 17/0.204; 18/-0.641 |
| opening_drive_vwap-ec92b2d0c7 | opening_drive_vwap | 0.0025 | 0.55 | 1.0 | 0.0000 | 61 | -10277.92 | -0.337 | 41.0% | 11249.61 | 8/-0.690; 14/-0.012; 16/-0.622 |
| opening_drive_vwap-844e3d8cb7 | opening_drive_vwap | 0.0025 | 0.70 | 0.8 | 0.0000 | 52 | -2258.41 | -0.087 | 51.9% | 4258.01 | 7/-0.146; 13/0.226; 10/-0.592 |
| opening_drive_vwap-491e26f2f0 | opening_drive_vwap | 0.0025 | 0.70 | 1.0 | 0.0000 | 43 | -3111.72 | -0.145 | 48.8% | 4803.04 | 5/-0.280; 12/0.062; 9/-0.462 |
| opening_drive_vwap-8418c1bb15 | opening_drive_vwap | 0.0035 | 0.55 | 0.8 | 0.0000 | 45 | -7182.83 | -0.319 | 42.2% | 7182.83 | 5/-0.636; 12/0.634; 9/-1.229 |
| opening_drive_vwap-e474dcce1c | opening_drive_vwap | 0.0035 | 0.55 | 1.0 | 0.0000 | 38 | -8774.35 | -0.462 | 36.8% | 8774.35 | 4/-0.757; 9/0.440; 9/-1.229 |
| opening_drive_vwap-924812f91f | opening_drive_vwap | 0.0035 | 0.70 | 0.8 | 0.0000 | 30 | -852.13 | -0.057 | 50.0% | 3006.74 | 2/0.472; 9/0.661; 5/-1.203 |
| opening_drive_vwap-2d0ce73899 | opening_drive_vwap | 0.0035 | 0.70 | 1.0 | 0.0000 | 25 | -1715.58 | -0.137 | 48.0% | 3006.74 | 1/1.094; 8/0.469; 5/-1.203 |
| opening_drive_vwap-e230ad6245 | opening_drive_vwap | 0.0045 | 0.55 | 0.8 | 0.0000 | 34 | -6152.82 | -0.362 | 38.2% | 6152.82 | 3/-0.086; 7/0.500; 6/-1.273 |
| opening_drive_vwap-0c291e82c5 | opening_drive_vwap | 0.0045 | 0.55 | 1.0 | 0.0000 | 30 | -5920.62 | -0.395 | 36.7% | 5920.62 | 2/-0.053; 7/0.500; 6/-1.273 |
| opening_drive_vwap-45eb6f3e57 | opening_drive_vwap | 0.0045 | 0.70 | 0.8 | 0.0000 | 25 | -1004.74 | -0.080 | 48.0% | 2588.31 | 2/0.472; 7/0.500; 3/-1.235 |
| opening_drive_vwap-62dcb6d54f | opening_drive_vwap | 0.0045 | 0.70 | 1.0 | 0.0000 | 21 | -772.53 | -0.074 | 47.6% | 2080.52 | 1/1.094; 7/0.500; 3/-1.235 |
| opening_range_breakout-55f1775fd6 | opening_range_breakout | 0.0020 | 0.45 | 0.8 | 0.0000 | 55 | 95.38 | 0.003 | 52.7% | 3091.98 | 14/-0.071; 13/-0.309; 7/0.136 |
| opening_range_breakout-7bb0361a55 | opening_range_breakout | 0.0020 | 0.45 | 0.8 | 0.0005 | 46 | -832.63 | -0.036 | 50.0% | 3341.29 | 12/-0.148; 12/-0.319; 4/0.102 |
| opening_range_breakout-b727bc5b55 | opening_range_breakout | 0.0020 | 0.45 | 1.0 | 0.0000 | 42 | 174.88 | 0.008 | 52.4% | 3489.31 | 11/0.106; 12/-0.507; 6/0.138 |
| opening_range_breakout-95858508e8 | opening_range_breakout | 0.0020 | 0.45 | 1.0 | 0.0005 | 34 | -689.95 | -0.041 | 50.0% | 3508.37 | 9/0.044; 11/-0.535; 4/0.102 |
| opening_range_breakout-bc933e1756 | opening_range_breakout | 0.0020 | 0.60 | 0.8 | 0.0000 | 32 | -3785.70 | -0.237 | 37.5% | 4068.79 | 5/-0.639; 9/-0.346; 4/0.004 |
| opening_range_breakout-6cb158b90c | opening_range_breakout | 0.0020 | 0.60 | 0.8 | 0.0005 | 27 | -4008.14 | -0.297 | 37.0% | 4336.76 | 5/-0.639; 8/-0.364; 3/0.036 |
| opening_range_breakout-56789a84a6 | opening_range_breakout | 0.0020 | 0.60 | 1.0 | 0.0000 | 24 | -3963.19 | -0.330 | 33.3% | 3972.17 | 3/-0.358; 8/-0.647; 4/0.004 |
| opening_range_breakout-de932a04f7 | opening_range_breakout | 0.0020 | 0.60 | 1.0 | 0.0005 | 19 | -4185.64 | -0.441 | 31.6% | 4240.14 | 3/-0.358; 7/-0.711; 3/0.036 |
| opening_range_breakout-c0e7591991 | opening_range_breakout | 0.0030 | 0.45 | 0.8 | 0.0000 | 43 | -866.12 | -0.040 | 48.8% | 3731.13 | 9/-0.281; 12/-0.321; 5/0.064 |
| opening_range_breakout-1d1b1ecaeb | opening_range_breakout | 0.0030 | 0.45 | 0.8 | 0.0005 | 38 | -1088.56 | -0.057 | 50.0% | 3632.63 | 9/-0.281; 11/-0.332; 4/0.102 |
| opening_range_breakout-59286c3fd8 | opening_range_breakout | 0.0030 | 0.45 | 1.0 | 0.0000 | 34 | -883.32 | -0.052 | 47.1% | 3702.22 | 7/-0.058; 11/-0.538; 5/0.064 |
| opening_range_breakout-3c971b2672 | opening_range_breakout | 0.0030 | 0.45 | 1.0 | 0.0005 | 29 | -1105.76 | -0.076 | 48.3% | 3603.72 | 7/-0.058; 10/-0.572; 4/0.102 |
| opening_range_breakout-337ba96c7f | opening_range_breakout | 0.0030 | 0.60 | 0.8 | 0.0000 | 29 | -3677.14 | -0.254 | 37.9% | 3960.23 | 4/-0.869; 9/-0.346; 4/0.004 |
| opening_range_breakout-9a362309ce | opening_range_breakout | 0.0030 | 0.60 | 0.8 | 0.0005 | 24 | -3899.58 | -0.325 | 37.5% | 4228.20 | 4/-0.869; 8/-0.364; 3/0.036 |
| opening_range_breakout-cc40a06cfc | opening_range_breakout | 0.0030 | 0.60 | 1.0 | 0.0000 | 22 | -4020.96 | -0.366 | 31.8% | 4029.93 | 2/-0.676; 8/-0.647; 4/0.004 |
| opening_range_breakout-46ce500da7 | opening_range_breakout | 0.0030 | 0.60 | 1.0 | 0.0005 | 17 | -4243.40 | -0.499 | 29.4% | 4297.91 | 2/-0.676; 7/-0.711; 3/0.036 |
| vwap_pullback_reclaim-af27b8ad1d | vwap_pullback_reclaim | 0.0025 | 0.40 | 0.8 | 0.0005 | 13 | -5680.47 | -0.874 | 15.4% | 5954.58 | 2/-1.345; 2/-1.354; 1/-1.344 |
| vwap_pullback_reclaim-f5f8f033f2 | vwap_pullback_reclaim | 0.0025 | 0.40 | 1.0 | 0.0005 | 9 | -5177.47 | -1.151 | 0.0% | 5177.47 | 1/-1.420; 2/-1.354; 1/-1.344 |
| vwap_pullback_reclaim-64e456d749 | vwap_pullback_reclaim | 0.0025 | 0.55 | 0.8 | 0.0005 | 8 | -2955.13 | -0.739 | 12.5% | 3229.24 | 2/-1.345; 1/-1.173; 0/0.000 |
| vwap_pullback_reclaim-855f988511 | vwap_pullback_reclaim | 0.0025 | 0.55 | 1.0 | 0.0005 | 5 | -2306.62 | -0.923 | 0.0% | 2306.62 | 1/-1.420; 1/-1.173; 0/0.000 |
| vwap_pullback_reclaim-50f214f1c7 | vwap_pullback_reclaim | 0.0035 | 0.40 | 0.8 | 0.0005 | 8 | -4817.22 | -1.204 | 0.0% | 4817.22 | 2/-1.345; 2/-1.354; 1/-1.344 |
| vwap_pullback_reclaim-38ac920f61 | vwap_pullback_reclaim | 0.0035 | 0.40 | 1.0 | 0.0005 | 7 | -4181.95 | -1.195 | 0.0% | 4181.95 | 1/-1.420; 2/-1.354; 1/-1.344 |
| vwap_pullback_reclaim-6b396e5675 | vwap_pullback_reclaim | 0.0035 | 0.55 | 0.8 | 0.0005 | 4 | -1946.37 | -0.973 | 0.0% | 1946.37 | 2/-1.345; 1/-1.173; 0/0.000 |
| vwap_pullback_reclaim-3cba6d76b3 | vwap_pullback_reclaim | 0.0035 | 0.55 | 1.0 | 0.0005 | 3 | -1311.10 | -0.874 | 0.0% | 1311.10 | 1/-1.420; 1/-1.173; 0/0.000 |

Family-level stability is poor. Zero of 12 opening-drive variants and zero of eight pullback/reclaim variants had positive full-training expectancy. Only two of 16 breakout variants were positive, and their expectancies were economically negligible (+0.003R and +0.008R) with two of three forward blocks negative. The selected rule's apparent median forward score is driven by blocks with only one and seven trades, then fails in the latest training block.

## Exact implementation contract

1. At 10:00 ET, read only completed SPY 5-minute bars timestamped 09:30 through 09:55. Require six bars, the frozen drive/efficiency/relative-volume/VWAP conditions above, and at most one signal per session.
2. At runtime, query the active Alpaca chain and reject unless both legs are tradable, share expiry 2–7 calendar days away, have fresh two-sided quotes, and pass the production liquidity policy. Buy the nearest-to-SPY call for bullish signals or put for bearish signals; sell the same-expiry strike approximately six points farther OTM. Use a single MLEG limit order with `buy_to_open` and `sell_to_open` intents.
3. Backtest entry is the next synchronized 5-minute trade-bar close. Live entry must use current quote-derived net debit and must not reuse the historical example price. Quantity is one spread and must additionally satisfy worst-case debit plus costs no greater than $500 (0.5% of the fresh account). Never size from the modeled stop alone.
4. Monitor synchronized spread marks. Exit at -25% or +50% of entry debit, or at 11:05 ET after the final 11:00–11:05 bar. A live implementation needs quote-based executable limits; bar-close differences are research-only.
5. `order-payload.json` is intentionally non-executable: it includes `dry_run: true`, expired historical symbols, `submission_forbidden: true`, and no API call. A future autonomous cycle may construct a fresh payload only after a new signal and all production risk gates.

Reproduce the underlying ledger without network access:

```bash
./.venv/bin/python experiments/strategy_candidates/trend/backtest.py --option-scope none
```

Reproduce the real option validation with authenticated read-only Alpaca access:

```bash
./.venv/bin/python experiments/strategy_candidates/trend/backtest.py --option-scope all
```

Run the isolated tests and lint:

```bash
./.venv/bin/python -m unittest discover -s experiments/strategy_candidates/trend/tests -v
./.venv/bin/ruff check experiments/strategy_candidates/trend
./.venv/bin/ruff format --check experiments/strategy_candidates/trend
```

## Leakage and realism caveats

- The grid compares 36 variants without a multiple-testing correction. The holdout was not used to choose or revise the frozen parameters, but one positive OOS trade cannot establish an edge.
- All records were acquired on 2026-09-04, so this is backfilled historical research rather than a contemporaneously captured feed. The stock source is IEX, not consolidated SIP.
- Expired contract metadata was queried after expiration. It is not a point-in-time chain snapshot and cannot prove contemporaneous tradability, open interest, or spread quality.
- Synchronized option trade-bar closes are not bid/ask quotes. Subtracting two closes can create a net price that was never executable, and the fixed slippage reserve cannot fully model wide or asynchronous markets.
- Training parameters were selected with an underlying-return proxy, while options introduce volatility, skew, decay, and liquidity effects. The real training option result is materially worse, demonstrating that mapping risk.
- Close-only stops avoid same-bar path ambiguity but can understate gap loss and cannot guarantee live stop execution. The vertical remains defined-risk only at expiry; early-exit slippage can be larger.
- The account preflight proves paper/Level-3 state at one timestamp only. No forward paper P&L was generated, and the dry-run payload is not evidence of a fill.
