# AFTERIMAGE — One-Go Implementation Blueprint

Status: **Pass 1 implementation completed; Pass 2 verification next**
Design: `docs/superpowers/specs/2026-09-04-afterimage-winning-system-design.md`

## Objective

Implement the complete modular AFTERIMAGE agent, evidence system, risk and warrant layer, Alpaca MCP execution path, strategy laboratory, and judge cockpit in one continuous build pass. Testing, strategy evaluation/refinement, and submission hardening happen as separate passes after the implementation exists end to end.

There are no per-component approval stops. The implementation pass ends only when every module is connected and the application can run a deterministic replay from market snapshot through broker-like reconciliation and cockpit visualization.

## Technology

- Python 3.11–3.14 with uv
- FastAPI, Pydantic 2, SQLAlchemy, SQLite WAL
- DuckDB, Parquet, PyArrow
- Python MCP client with official `alpaca-mcp-server` 2.3.1
- Featherless OpenAI-compatible API
- Ed25519 via `cryptography`
- Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts
- pytest, Hypothesis, pytest-asyncio, Ruff, mypy, Vitest, Testing Library, Playwright

## Non-negotiable invariants

- Use only the verified fresh $100,000 Alpaca paper account.
- Force `ALPACA_PAPER_TRADE=true`; never accept a live endpoint.
- Require effective and approved Options Level 3.
- Maximum modeled loss is $500 per position.
- One open strategy position; daily halt at $1,000 including worst open loss; high-water halt at 2%.
- Debit structures require structural and conservative operational reward/risk of at least 3:1 after modeled costs.
- No LLM may choose arbitrary contracts, set quantity, mint a warrant, change an order, bypass a gate, or determine whether a mathematical gate passed.
- Historical outcomes and decodable identities stay inaccessible until the cohort is committed durably.
- Every artifact includes all strategy, evidence, policy, model, prompt, data, and timestamp versions.
- Broker orders and positions override local memory after submission, ambiguity, or restart.
- Every order must be an exact warrant-bound Level 3 Mleg limit order.
- Secrets, recovery codes, authorization headers, and unredacted identifiers never enter Git, logs, prompts, screenshots, or exported evidence.

## Repository to create

```text
.
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── uv.lock
├── pnpm-workspace.yaml
├── configs/
│   ├── risk/hackathon-v1.yaml
│   ├── tournament-v1.yaml
│   └── strategies/
│       ├── opening_range_failure_v1.yaml
│       ├── momentum_continuation_v1.yaml
│       └── volatility_dislocation_v1.yaml
├── src/afterimage/
│   ├── cli.py
│   ├── contracts/{enums,models,hashing}.py
│   ├── storage/{db,models,repositories,audit}.py
│   ├── orchestration/{state_machine,coordinator}.py
│   ├── strategies/{base,registry,opening_range_failure,momentum_continuation,volatility_dislocation}.py
│   ├── data/{alpaca_market,snapshots,option_replay,fixtures}.py
│   ├── evidence/{vault,retrieval,commit_reveal,metrics,protocol}.py
│   ├── agents/{schemas,gateway,roles}.py
│   ├── risk/{payoff,governor,sizing,warrant}.py
│   ├── execution/{mcp_client,alpaca_gateway,client_ids,lifecycle,reconciler,watchdog}.py
│   ├── tournament/{manifests,promotion,runner}.py
│   └── api/{main,routes,stream}.py
├── apps/web/
│   ├── app/{layout,page,globals}.tsx
│   ├── components/
│   │   ├── proof-timeline.tsx
│   │   ├── market-claim.tsx
│   │   ├── sealed-jury.tsx
│   │   ├── ghost-paths.tsx
│   │   ├── risk-passport.tsx
│   │   ├── warrant-card.tsx
│   │   ├── broker-truth.tsx
│   │   ├── tournament.tsx
│   │   └── graveyard.tsx
│   └── lib/{api,event-types,format}.ts
├── tests/{contracts,storage,orchestration,strategies,data,evidence,agents,risk,execution,tournament,e2e}/
├── evidence/{replays,tournament,paper,submission}/
├── scripts/{run_mcp_data.sh,run_mcp_trade.sh,record_demo.sh,export_evidence.py}
└── docs/submission/{one-page.md,project-page.md,demo-script.md,judge-checklist.md}
```

## Pass 1 — Continuous implementation

This is one uninterrupted build. The order below is dependency order inside the pass, not a set of approval checkpoints.

### Foundation and typed contracts

Initialize Git and the Python/TypeScript workspaces. Lock dependencies. Define strict Pydantic contracts for strategy identity, frozen snapshots, candidate events, blinded evidence, committed and revealed trials, agent reports, option legs, payoff passports, risk decisions, execution intents, warrants, broker events, session events, and tournament results.

Canonical JSON must sort keys, serialize UTC timestamps consistently, and preserve decimal prices as strings. Canonical SHA-256 hashes become the identity for manifests, evidence packets, decisions, and intents.

Define the complete generic state machine:

```text
BOOTSTRAP → PRECHECKED → OBSERVING → SNAPSHOT_FROZEN → SIGNAL_CANDIDATE
→ EVIDENCE_COMMITTED → EVIDENCE_REVEALED → RISK_APPROVED → WARRANT_MINTED
→ SUBMITTING → WORKING → FILLED → EXITING → CLOSED → AUTOPSY
```

Branches are `NO_SIGNAL`, `REJECTED`, `INSUFFICIENT_EVIDENCE`, `AMBIGUOUS`, `PARTIAL_OR_ANOMALOUS`, `EXPIRED`, and `HALTED`. No terminal rejection can transition back to approval.

### Transactional truth and audit chain

Use SQLite WAL for live state and SQLAlchemy models for sessions, snapshots, evidence manifests, risk decisions, warrants, broker events, positions, paper/model ledgers, tournaments, and autopsies.

Every domain transaction appends a hash-chained audit record containing sequence, event type, canonical payload, previous hash, record hash, versions, and UTC timestamp. Uniqueness constraints cover session sequence, manifest hash, warrant nonce, client order ID, and broker order ID. Production code cannot update or delete audit records.

### Strategy plugin system

Create a `StrategyPlugin` protocol with these stable operations:

```python
class StrategyPlugin(Protocol):
    identity: StrategyIdentity
    def freeze(self, raw: MarketFrame) -> FrozenSnapshot: ...
    def detect(self, snapshot: FrozenSnapshot) -> CandidateEvent | None: ...
    def evidence_query(self, candidate: CandidateEvent) -> EvidenceQuery: ...
    def contract_policy(self, candidate: CandidateEvent) -> ContractPolicy: ...
    def exit_plan(self, candidate: CandidateEvent) -> ExitPlan: ...
```

Implement a registry loading immutable YAML configuration. Implement all three initial strategies in the same pass:

1. `opening_range_failure_v1`: failed opening-range breakout, debit vertical.
2. `momentum_continuation_v1`: completed 30-minute momentum with volume/volatility confirmation, debit vertical.
3. `volatility_dislocation_v1`: pre-registered realized-versus-implied expansion, bounded-debit long-volatility Mleg.

They produce candidates and policies only. They cannot access credentials, risk authority, warrants, or execution.

### Point-in-time market and option replay

Normalize all records to UTC and preserve event time, receipt time, source, and feed. Reject records newer than the declared cutoff, revised bars, stale/crossed/one-sided quotes, missing legs, and excessive leg timestamp skew.

Store immutable research snapshots as content-addressed Parquet. Build synchronized multi-leg replays using executable prices: buy at ask, sell at bid, include declared fees/slippage, never forward-fill past freshness limits, and retain target-first, stop-first, time-exit, and censored outcomes. Maintain broker-like P&L beside deliberately conservative P&L.

### Sealed Historical Twin Trial

Separate the feature vault from the outcome vault. The blind projection cannot contain dates, timestamps, future paths, returns, outcome labels, or reversible row identities.

Retrieval uses manifest-declared features, training-only median/MAD scaling, stable distance and tie-breaking, cluster caps, and normalized weights. The commit transaction stores the full selected cohort, weights, exclusions, query, schema, data hash, strategy hash, prompts, sanitized agent packets, and canonical commit hash before any reveal.

After reveal, deterministic code calculates effective sample size, weighted target-first probability, declared Wilson lower bound, cost-aware EV in R, drawdown, chronological-fold stability, leave-one-cluster-out EV, placebo separation, coverage, censoring, and exact rejection reasons. The disclosed 29-event result cannot satisfy `n_eff >= 30`; the larger live twin archive and untouched performance holdout must remain distinct.

### Featherless agents

Implement a provider-neutral structured-output gateway using:

```dotenv
FEATHERLESS_BASE_URL=https://api.featherless.ai/v1
AFTERIMAGE_DEEP_MODEL=zai-org/GLM-5.3
AFTERIMAGE_FAST_MODEL=zai-org/GLM-5.3-Flash
```

The deep model handles the selected candidate's strategist/prosecutor pass. The fast model handles regime and options witnesses. Every request has a Pydantic output schema, compact packet, prompt hash, model ID, timeout, token/cost budget, latency record, secret redaction, one transport retry, and recorded-response fallback.

Roles receive genuinely different information:

- Strategist: frozen market evidence only.
- Regime witness: regime features only.
- Options witness: chain, Greeks, liquidity, and scenario prices only.
- Prosecutor: blinded reports and retrieval diagnostics.
- Outcome auditor: unlocks the committed outcome set.

Timeout, malformed JSON, provider failure, or missing evidence becomes abstention—not guessed output.

### Deterministic payoff, risk, and warrant authority

Calculate structural and operational payoff from executable synchronized leg prices. Floor position quantity so modeled full loss never exceeds $500, returning zero if one spread is already too expensive.

The ordered risk vector verifies account, paper endpoint, clock and cutoff, strategy manifest, candidate, evidence, quote freshness, leg synchronization, liquidity, structural 3R, operational 3R, quantity, per-position loss, daily loss, drawdown, position collision, and warrant eligibility. Persist every gate value.

Create a local Ed25519 key with mode `0600`. The warrant signs exact account hash, strategy and evidence versions, legs, ratios, side, quantity, maximum price, expected loss, quote timestamps, risk hash, TTL, and nonce. Consume the nonce transactionally before submission. Any modification or expiration invalidates it.

### Official Alpaca MCP boundary

Run two official MCP processes against the same paper account:

```bash
ALPACA_PAPER_TRADE=true ALPACA_TOOLSETS=assets,stock-data,options-data \
  uvx alpaca-mcp-server --transport stdio --env-file .env

ALPACA_PAPER_TRADE=true ALPACA_TOOLSETS=account,trading,assets \
  uvx alpaca-mcp-server --transport stdio --env-file .env
```

The Python MCP client initializes the sessions, lists tools, and persists tool names, input-schema hashes, enabled toolsets, and server version. The data process must not expose order tools. The trade process must expose `get_account_info`, `get_account_config`, `get_orders`, `get_order_by_client_id`, `get_all_positions`, `get_clock`, `place_option_order`, `replace_order_by_id`, and `cancel_order_by_id`.

Preflight verifies the allowlisted paper account, active status, trades not suspended, Level 3, expected reference equity, market clock, unknown orders, and unknown positions. The paper API key is stored only in ignored local `.env` with mode `0600`.

### Idempotent execution and broker reconciliation

Persist the exact intent before any MCP mutation. Derive client order ID from session, intent hash, and bounded attempt number. Submit `place_option_order` using `order_class="mleg"`, `type="limit"`, `time_in_force="day"`, and warrant-bound legs.

Allow at most two reprices; each needs synchronized fresh quotes, a new risk decision, and a new warrant. Repricing cannot modify legs, ratios, quantity, account, or expiration.

If submission times out, query by client order ID, order ID, all orders, and positions before any retry. On restart, rebuild from Alpaca truth. The watchdog manages target, stop, time exit, stale quotes, orphan orders, position mismatch, daily halt, and emergency close through bounded atomic closing limits.

### Coordinator, CLI, and API

Create one coordinator that runs precheck, freeze, detect, retrieve, agents, commit, reveal, evidence metrics, contract construction, payoff, risk, warrant, optional execution, reconciliation, closing, and autopsy. Each stage emits one persisted event and can resume safely.

Expose:

- `GET /health`
- `POST /api/preflight`
- `POST /api/replays`
- `GET /api/sessions/{id}`
- `GET /api/sessions/{id}/events`
- `POST /api/risk/{id}`
- `POST /api/execute/{id}` accepting only a warrant ID
- `POST /api/reconcile/{id}`
- `GET /api/stream/{session_id}` using resumable SSE

CLI commands are `preflight`, `replay`, `shadow`, `tournament develop`, `tournament reveal`, `execute`, `reconcile`, `export-evidence`, and `serve`.

### Sealed strategy tournament and Alpha Graveyard

The tournament pre-registers candidate manifests, code revision, dataset hashes, chronological folds, embargo, costs, baselines, metrics, hard gates, and tie-break formula before final-holdout access.

All three strategies use the same untouched chronological holdout. Parameter changes after sealing invalidate the candidate. Every evaluated candidate remains visible in the Alpha Graveyard. At most one champion is promoted; a failed hard gate cannot be overridden by a ranking score. `NO_CHAMPION` is valid.

Every subsequent decision and warrant includes the champion's exact manifest hash.

### Judge cockpit

Build a polished dark evidence-desk interface with cyan verified facts, amber pending/insufficient states, red rejections, and green only for completed proof. Pair color with text and icons.

The primary timeline contains:

1. Market Claim
2. Sealed Jury
3. Reveal and Ghost Paths
4. 3R Passport
5. Execution Warrant
6. Broker Truth

Secondary drawers show the tournament bracket, Alpha Graveyard, rejection museum, raw metric evidence, sanitized MCP trace, architecture, and tests. Raw LLM prose is collapsed. Every important claim links to its source artifact.

Support live SSE, reconnect by `Last-Event-ID`, keyboard navigation, reduced motion, responsive 1440×900 demo layout, provider-down states, and deterministic autoplay using `?session=<fixture>&autoplay=1`.

### Evidence export and demo fixtures

Create one accepted and one rejected deterministic replay. Each bundle contains strategy/data manifests, frozen snapshot, blind cohort, commit, reveal, agent hashes, risk decision, warrant/public key, sanitized MCP trace, broker-like lifecycle, dual P&L ledgers, autopsy, and audit verification.

The export command recomputes every hash before writing. Running the same fixture twice must produce identical content hashes aside from explicitly excluded run timestamps.

## Pass 1 completion condition

Implementation is complete only when:

- All modules exist and are connected.
- The API and cockpit start together.
- A deterministic accepted replay reaches `AUTOPSY`.
- A deterministic rejection reaches its exact terminal reason without calling execution.
- A changed manifest, quote, warrant, order leg, price, quantity, or account invalidates authorization.
- The tournament can produce a champion or `NO_CHAMPION` and populate the Alpha Graveyard.
- The UI renders the complete proof and broker-like lifecycle.

No claim that testing is finished is made at this point.

## Pass 2 — Testing and verification

Testing starts after the complete implementation exists. Failures are fixed across the system, then the full suite restarts.

### Contract and property verification

- Canonical hashing and strict schema rejection
- Timezone and Decimal serialization
- Every legal and illegal state transition
- Hash-chain tamper detection
- Strategy determinism and cutoff enforcement
- Position sizing never exceeding $500 modeled loss
- Rejections never becoming approvals
- Changed/expired/consumed warrants failing verification

### Leakage and statistics verification

- Outcome/date/future fields absent from blind stores
- Row IDs not reversible to date
- Feature scalers trained only on allowed history
- Commit mismatch on any changed cohort, weight, prompt, parameter, or dataset
- Correct `n`, `n_eff`, confidence method, EV, drawdown, stability, placebo, coverage, and censoring
- Insufficient samples returning `INSUFFICIENT_EVIDENCE`

### MCP and lifecycle verification

- Exact tool inventory and least privilege
- Wrong/live endpoint rejection
- Wrong account or non-Level-3 rejection
- Stale/crossed/one-sided/unsynchronized quote rejection
- Timeout after accepted submission
- Duplicate retry
- Cancel/replace race
- Partial/anomalous state
- Restart with working order or position
- Orphan and mismatch halt
- Target, stop, time exit, and emergency close

### Agent verification

- Valid structured output
- Malformed JSON
- Provider timeout/rate limit/outage
- Token/cost budget
- Secret and identifier redaction
- Recorded-response fallback
- Proof that model output cannot mutate risk or execution fields

### UI and end-to-end verification

- Accepted replay
- Rejected replay
- `NO_CHAMPION`
- Broker ambiguity and recovery
- SSE disconnect/reconnect
- Keyboard and color-independent status
- 1440×900 and 1920×1080 demo layouts
- Production frontend build
- One-command clean-start rehearsal

The release gate is:

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
pnpm --dir apps/web test
pnpm --dir apps/web typecheck
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Run the full gate twice from clean processes. Zero unauthorized orders and a valid audit chain are mandatory.

## Pass 3 — Strategy testing and refinement

After software verification, build the largest valid point-in-time dataset obtainable through Alpaca within the remaining time. Preserve an untouched final holdout and declare every data limitation.

Run the three sealed candidates through development folds, robustness checks, operational option replay, and the final reveal. Compare:

- net P&L and EV after costs
- lower confidence bounds
- maximum drawdown
- hit rate and payoff distribution
- `n` and `n_eff`
- chronological and regime stability
- sensitivity to nearby parameters
- leave-one-cluster-out stability
- liquidity coverage and no-trade rate
- option replay versus underlying-only evidence
- simple and shuffled-label placebos

Refinement is allowed only before a new sealed final evaluation. Every change creates a new version. Previously opened final holdouts cannot be relabeled untouched. Failed versions remain in the Alpha Graveyard.

Promote the strongest strategy that passes all hard gates—not the strategy with the prettiest isolated backtest. If none pass, use the most defensible strategy for deterministic replay and show `NO_TRADE` or `NO_CHAMPION` honestly in live mode.

## Pass 4 — Paper validation and submission hardening

Run read-only authenticated MCP preflight, then live shadow mode with order tools disabled. Rehearse ambiguity and emergency behavior against fake MCP first.

Before the first paper order, display the exact OCC legs, ratios, quantity, maximum debit, modeled maximum loss, quote timestamps, strategy hash, evidence hash, warrant expiry, and paper account hash. A paper order is submitted only with explicit action-time approval.

Capture one bounded Level 3 paper Mleg lifecycle if market conditions and gates permit. Reconcile order, fills, position, exit, broker P&L, and conservative modeled P&L. A no-trade day does not justify weakening gates.

Create:

- Public repository and reproducible quickstart
- Deployed cockpit
- 90-second primary demo plus fallback recording
- One-page AI/risk/infrastructure explanation
- Project page mapped to the exact four criteria
- Slides and screenshots
- Sanitized self-verifying evidence bundle
- Account proof and required paper account ID
- Limitations and evidence-level disclosure

The 90-second story is:

1. Verified $100,000 paper-only Level 3 account.
2. Promoted strategy and frozen market claim.
3. Outcome-blind twins and adversarial cross-examination.
4. Commit seal, reveal, and ghost paths.
5. Cost-aware 3R passport and $500 cap.
6. Evidence-bound execution warrant and Alpaca Mleg receipt.
7. Tournament/Alpha Graveyard: the system shows what failed as well as what won.

Freeze backend and strategy behavior at T-minus 3 hours. At T-minus 90 minutes, perform only final deployment verification, recording, evidence export, and submission.

## Final definition of done

- The complete modular agent works end to end.
- Strategies can be replaced without touching the capital path.
- Multiple strategies were evaluated under a sealed common protocol.
- Performance evidence is cost-aware and labels every evidence level honestly.
- Official Alpaca MCP is visibly central to data, account verification, and Level 3 execution.
- Featherless models are useful but cannot control capital.
- Every trade and refusal is reproducible, explainable, and audit-verifiable.
- The judge can understand the novelty and proof within 90 seconds.
- The submitted revision matches the public repository and evidence bundle.
