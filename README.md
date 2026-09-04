# AFTERIMAGE

AFTERIMAGE is a strategy-pluggable autonomous trading agent for Alpaca paper accounts. It combines deterministic signals, an adversarial multi-model decision desk, evidence-bound promotion, deterministic risk, signed single-use execution authority, and broker-truth lifecycle management. The active strategy can change without rewriting the orchestrator.

The default admitted strategy is **GuavaMango** (`shadow_clock_shock_reversal_v1`): a long-only, cross-sectional ETF shock-reversal system whose hidden state advances even when a Thursday or Friday setup is intentionally skipped. It scans 11 liquid ETFs after the close, selects the strongest qualifying countertrend shock inside an established uptrend, and—only on an allowed setup—constructs a next-session equity bracket with a modeled after-cost target of at least 3R.

This repository is paper-only, provides no investment advice, and makes no promise of future returns.

## Current evidence

The winning candidate was researched on authenticated Alpaca IEX daily history from 2018 through September 3, 2026. Its 2022–2026 chronological pseudo-out-of-sample record is:

- 95 trades and +48.05R net
- 2.253 profit factor and +0.506R expectancy per trade
- 4.746R maximum drawdown
- 72.34% positive active months and eight profitable underlyings
- all five annual folds net positive
- +46.88R and 2.222 profit factor at 1.5× modeled costs
- all 108 immediate parameter neighbors net positive
- minimum modeled after-cost target-to-stop ratio: 3.000013

These are backtest results, not broker P&L. The period was visible during iterative research, so it is labeled **pseudo-OOS**, not misrepresented as a sealed untouched holdout. IEX bars are not SIP data and historical daily bars do not reconstruct executable bid/ask quotes or market impact. The complete result, every prior failed attempt, costs, limitations, and hash chain are preserved in [the strategy report](experiments/strategy_candidates/event_flow/REPORT.md).

A real read-only Alpaca smoke run independently confirmed the bound paper account is active with $100,000 equity, Level 3 options permission, and no positions or orders. It fetched 2,783 current daily bars across the complete ETF universe. The latest session was Thursday, which is not an executable setup day for this frozen rule, so the agent correctly returned `NO_SIGNAL`; no order was sent and no paper P&L is claimed.

## What is technically original

- **Strategy socket:** YAML declares plugin, universe, timeframe, lookback, decision boundary, entry cutoff, asset class, and evidence manifest. The registry discovers it dynamically.
- **GuavaMango state clock:** skipped signals still consume the serialized strategy clock, preventing live behavior from silently diverging from the tested rule.
- **Adversarial AI desk:** strategist, regime witness, execution witness, and prosecutor receive explicit evidence packets and must cite packet paths. Unsupported claims, malformed output, abstentions, or fatal findings stop the trade.
- **Exact model routing:** `zai-org/GLM-5.3` runs the strategist and prosecutor; `zai-org/GLM-5.3-Flash` runs the two fast witnesses.
- **Evidence-to-code authority:** promotion binds the admitted result, every required gate, strategy YAML, actual plugin source bytes, global runtime manifest, and risk-policy version into one verifiable authority hash.
- **Cost-aware execution:** the live stop is rebased on the executable next-session quote, while fees, bid/ask entry, modeled exit slippage, cent rounding, risk sizing, and notional limits are included before the 3R gate can pass.
- **Broker-truth lifecycle:** the same intent proceeds from dry run to optional paper submission, reconciliation, bracket monitoring, time exit, and autopsy. Every mutation is client-ID idempotent and separately warranted.
- **Honest alpha graveyard:** rejected option, mean-reversion, volatility-premium, trend, and cross-asset families remain visible rather than disappearing after evaluation.

## Architecture

- `src/afterimage/strategies` — immutable strategy plugins, dynamic registry, runtime socket, and deployment-evidence loader
- `src/afterimage/agents` — strict-schema Featherless decision desk, prompts, evidence citations, and inference provenance
- `src/afterimage/evidence` — point-in-time records, commit/reveal research protocols, metrics, and stable exports
- `src/afterimage/risk` — deterministic payoff gates, sizing, portfolio limits, and Ed25519 warrants
- `src/afterimage/execution` — official Alpaca CLI/MCP gateways, exact order intents, reconciliation, watchdog, and exits
- `src/afterimage/orchestration` — strategy-agnostic end-to-end coordinator and durable state machine
- `experiments/strategy_candidates` — append-only hands-on strategy searches, real-data caches, tests, and reports
- `apps/web` — judge cockpit; visual redesign is intentionally deferred to the dedicated UI pass

## Run locally

Prerequisites are Python 3.11+, `uv`, Node.js, `pnpm`, and the pinned official Alpaca CLI.

```bash
uv sync --all-groups
pnpm --dir apps/web install
cp .env.example .env

alpaca profile login --paper --name afterimage-paper --scope data
uv run afterimage bind-account
uv run afterimage preflight
```

Provide `FEATHERLESS_API_KEY` through the environment or the ignored private file `.afterimage/featherless-api-key`. Never commit credentials, account identifiers, recovery codes, OAuth material, signing keys, or private evidence.

Run the admitted strategy against the bound real paper account and current Alpaca data without submitting:

```bash
uv run afterimage shadow --strategy-id shadow_clock_shock_reversal_v1
```

Run the local API and cockpit:

```bash
scripts/run_stack.sh
```

## Swap a strategy

A replacement strategy needs four explicit pieces: a `StrategyPlugin`, its YAML runtime contract, an admitted result bundle, and a deployment manifest. Once the config names the plugin, the registry and coordinator load it without strategy-specific orchestration changes. Select it with `AFTERIMAGE_ACTIVE_STRATEGY` or `--strategy-id`.

This boundary deliberately separates alpha research from the reusable product. A strategy cannot become executable merely by returning a signal: its exact code/config authority and evidence gates must match the deployment manifest.

## Paper execution

Shadow mode never submits. A paper order requires both the explicit execution command and the disabled-by-default environment gate:

```bash
AFTERIMAGE_ENABLE_PAPER_EXECUTION=true \
  uv run afterimage execute SESSION_ID WARRANT_ID
```

The order intent, account binding, quote vector, risk decision, evidence result, strategy authority, quantity, and expiry are all covered by the warrant. Entries use an equity limit bracket; a time-based close receives a new reduce-only market warrant. Ambiguous submissions are resolved by deterministic client order ID rather than blind resubmission.

## Verification

```bash
uv run pytest -q
uv run ruff check .
uv run mypy --strict src
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

The end-to-end integration suite includes the admitted equity winner reaching `SHADOW_READY` with a passing 3R payoff, signed bracket warrant, exact source-bound promotion evidence, and `submitted: false` Alpaca dry-run artifact. Separate tests cover the option adapter and all preserved research lanes.
