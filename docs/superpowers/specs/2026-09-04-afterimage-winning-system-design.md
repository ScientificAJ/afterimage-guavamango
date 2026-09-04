# AFTERIMAGE — Winning System Design

Status: **Approved; implementation authorized and completed**
Date: 2026-09-04
Target: Alpaca AI Trading Agents Hackathon, Options Alpha Agents track

## 1. Product decision

AFTERIMAGE is not one trading strategy and not a generic council of chatbots. It is an autonomous options research-and-execution system that requires a strategy to earn the right to trade through a sealed, reproducible proof process.

The current failed-opening-range setup remains a reference strategy named `opening_range_failure_v1`. It is not embedded in the orchestration, evidence, risk, execution, storage, or user-interface layers.

The system's judge-facing claim is:

> Most agents show why they traded after seeing the outcome. AFTERIMAGE pre-registers the strategy, seals the evidence cohort before outcomes are revealed, and issues a single-use execution warrant only when the proof and risk rules pass.

Winning is not guaranteed, and no trading system can guarantee profit. The design maximizes credible evidence for every judging category without inventing performance.

## 2. Competitive position

The crowded pattern in current submissions is: scan indicators, ask multiple agents to debate, apply a deterministic risk gate, execute on Alpaca, and show a dashboard. Another leading project already describes a discover-test-challenge-score-allocate research loop.

AFTERIMAGE must therefore win on a property competitors cannot add as a slogan: **verifiable non-cherry-picking**.

Its differentiators are:

1. Strategy rules and evaluation protocol are pre-registered and hashed before the final holdout is opened.
2. Historical analogues are selected while their outcomes are unavailable to the agents.
3. Every tested strategy, including failures, remains visible in an Alpha Graveyard; the winner cannot hide the search cost.
4. A deterministic promotion tribunal selects the only strategy version eligible for capital.
5. A short-lived, single-use warrant cryptographically binds the approved evidence to the exact Alpaca Mleg order.
6. Broker state, not the model or UI, is authoritative after submission.

## 3. Three approaches considered

### A. Implement the entire original blueprint literally

This preserves maximum feature count but creates a high chance that the order lifecycle, evidence chain, or judge demo is incomplete. Feature count is not judge evidence.

### B. Build one small strategy bot

This is fastest and could obtain a paper result, but it would resemble many existing submissions and underuse the strongest invention.

### C. Build the complete proof spine, then run a sealed strategy tournament — selected

This preserves the ambitious agent, cockpit, evidence, warrant, and execution system. It also supports multiple strategies, but only after one end-to-end vertical slice is working. Scope is controlled by time gates, not by deleting ambitious ideas in advance.

## 4. Judge-visible success contract

| Criterion | AFTERIMAGE must visibly prove |
| --- | --- |
| P&L Performance | Cost-aware option replay, untouched holdout, drawdown and distribution, paper broker P&L, and paper-versus-modeled slippage. |
| Technology Implementation | Official Alpaca MCP calls, Level 3 Mleg order, typed state machine, restart-safe reconciliation, deterministic risk decisions, and a verified warrant. |
| Creativity & Originality | Pre-registration, outcome-blind cohort selection, commit/reveal, Alpha Graveyard, promotion tribunal, and evidence-bound execution. |
| Presentation & Execution | A reliable 90-second story in which a candidate visibly earns or is denied permission to trade, with a recorded fallback and one-click evidence export. |

The main demo must be understandable without reading agent transcripts. Every headline claim is clickable to its underlying manifest, statistic, broker receipt, or rejection reason.

## 5. Scope policy: ambitious but gated

No feature is removed merely because it sounds ambitious. Features are divided by dependency:

### Proof spine — must be complete before expansion

1. Paper-account preflight and paper-only endpoint guard.
2. One strategy plugin producing deterministic replay candidates.
3. Frozen feature snapshot and sealed evidence manifest.
4. Outcome-blind retrieval, commit, reveal, and deterministic metrics.
5. Cost-aware option construction and structural/operational payoff passport.
6. Deterministic risk decision and single-use execution warrant.
7. Official Alpaca MCP Mleg submission, idempotency, reconciliation, and exit.
8. Judge cockpit showing the entire chain.

### Winning expansion — begin as soon as the proof spine passes

- Three-strategy promotion tournament.
- Multiple evidence witnesses plus a prosecutor.
- Ghost-path visualization.
- Alpha Graveyard and rejection museum.
- Strategy comparison and sensitivity views.
- Automated evidence bundle.
- A second recorded scenario.

### Freeze gates

- At T-minus 8 hours: one deterministic replay must traverse the complete proof spine.
- At T-minus 5 hours: a paper Mleg dry run or controlled order lifecycle must reconcile without duplicate exposure.
- At T-minus 3 hours: freeze backend behavior and strategy manifests; work only on verification, judge experience, recording, and submission.
- At T-minus 90 minutes: no feature changes. Final recording, deployment verification, evidence export, and submission only.

If a gate is missed, unfinished expansion is disabled behind flags; the proof spine is never compromised.

## 6. System boundaries

### Immutable capital path

The following components are strategy-independent:

- Paper-account allowlist and endpoint guard
- Market-data freshness and provenance checks
- Broker gateway through official Alpaca MCP
- Deterministic risk governor
- Single-use warrant authority
- Idempotent order lifecycle and reconciliation
- Position watchdog and emergency halt
- Append-only audit and evidence ledger
- Model gateway with timeouts and schema validation

### Replaceable research path

The following components are plugins or versioned policies:

- Universe and observation schedule
- Feature builder
- Signal detector
- Evidence protocol configuration
- Option structure and contract candidate builder
- Target, stop, expiry, and exit policy
- Backtest and promotion criteria

Changing a strategy must not require changes to broker credentials, order code, warrants, reconciliation, core risk invariants, or the cockpit event schema.

## 7. Strategy plugin contract

Each strategy package declares a versioned `StrategySpec` containing:

- `strategy_id` and semantic `strategy_version`
- eligible symbols and market session
- observation, freeze, and final-entry cutoffs
- feature schema and data provenance requirements
- deterministic candidate rule
- direction and permitted option structures
- contract filters, including DTE, delta, spread, volume, and open interest
- underlying and option-space target/stop definitions
- maximum holding period and mandatory exit rules
- reward/risk policy
- evidence retrieval configuration
- research periods, embargoes, and untouched holdout
- invalidation conditions and no-trade reasons

The interface produces typed artifacts:

1. `FrozenSnapshot`
2. `CandidateEvent | NoSignal`
3. `EvidenceQuery`
4. `ContractCandidates`
5. `ScenarioPayoff`
6. `ExitPlan`

The strategy cannot submit orders or mint warrants.

## 8. Strategy Promotion Tournament

The tournament begins only after the proof spine works with the reference strategy.

### Initial candidate families

1. `opening_range_failure_v1`: failed opening-range breakout expressed as a directional debit vertical.
2. `momentum_continuation_v1`: a completed-window continuation signal expressed as a directional debit vertical.
3. `volatility_dislocation_v1`: realized-versus-implied expansion expressed as a defined-risk long-volatility Mleg structure.

These are hypotheses, not promises. A candidate can be replaced before pre-registration if data availability makes its test invalid.

### Tournament protocol

1. Define all parameters, costs, metrics, exclusions, and time windows.
2. Hash the strategy manifests and the promotion policy.
3. Run training and walk-forward development without accessing the final holdout.
4. Freeze each candidate version.
5. Evaluate every frozen candidate on the same untouched chronological holdout.
6. Record all results, including failed candidates, in the Alpha Graveyard.
7. Promote at most one champion through deterministic rules.
8. Bind the champion manifest hash to every live/paper decision and warrant.

No agent may change parameters after final-holdout reveal. A changed parameter creates a new strategy version and cannot reuse the same final holdout as untouched evidence.

### Promotion policy

A champion must satisfy all hard gates:

- sufficient raw and effective sample size for the declared inference method
- positive cost-aware expectancy
- positive lower confidence bound under the declared method
- maximum drawdown below the declared cap
- stability across chronological folds and major regimes
- leave-one-cluster-out stability
- acceptable liquidity coverage and no-trade rate
- stronger results than simple placebos and baselines
- viable structural payoff and conservative operational payoff
- no leakage, timestamp, or provenance violation

The ranking score breaks ties; it never overrides a failed gate. The score combines cost-aware expectancy, confidence-bound strength, drawdown, stability, liquidity coverage, and agreement between historical option replay and forward paper outcomes.

## 9. Evidence protocol

The Sealed Historical Twin Trial is a reusable `EvidenceProtocol`, not opening-range-specific code.

1. Freeze a canonical live or replay snapshot.
2. Give agents pseudonymous historical feature records without dates or outcomes.
3. Retrieve and challenge analogues.
4. Persist the selected cohort, weights, exclusions, prompts, tool calls, and canonical hash.
5. Reveal outcomes only after durable commitment.
6. Compute metrics in deterministic code.
7. Produce `PASS`, `REJECT`, or `INSUFFICIENT_EVIDENCE` with exact reasons.

The disclosed 29-event out-of-sample study cannot by itself satisfy `n_eff >= 30`. The implementation must declare whether the live twin archive is a larger pre-cutoff research set and must keep that archive distinct from the untouched performance holdout.

No UI copy may imply that underlying-bar results are executable option P&L. Evidence levels are always labeled:

- L0: invariant/property tests
- L1: underlying replay
- L2: timestamped option quote replay
- L3: sealed trial replay
- L4: shadow decision
- L5: Alpaca paper execution

## 10. Agent topology

Agents have different information and authority, not merely different system prompts.

- **Strategist**: converts a deterministic candidate packet into a falsifiable thesis; cannot see historical outcomes.
- **Regime Witness**: evaluates regime compatibility from its limited feature view.
- **Options Witness**: evaluates chain quality, Greeks, liquidity, and scenario behavior; cannot authorize capital.
- **Prosecutor**: searches for leakage, instability, placebo similarity, and missing counter-evidence.
- **Outcome Auditor**: reveals the committed cohort and computes no metrics itself.
- **Risk Governor**: deterministic service, not an LLM.
- **Warrant Authority**: deterministic signer with no model access.
- **Execution Agent**: deterministic state machine using the Alpaca MCP; cannot alter the warrant.
- **Reconciler/Watchdog**: treats Alpaca orders and positions as truth and can halt entry.

An agent timeout, schema failure, disagreement, or missing evidence becomes an explicit abstention or rejection. LLM confidence is never averaged into a risk decision.

## 11. Model policy

The model layer is provider-neutral. The intended Featherless routing is:

- `zai-org/GLM-5.3` for the selected candidate's deep strategist/prosecutor pass.
- `zai-org/GLM-5.3-Flash` for low-latency witness calls and summaries.
- deterministic Python for retrieval, statistics, pricing, risk, warrants, orders, and reconciliation.

Every model call has a typed JSON schema, compact evidence packet, timeout, retry budget, token/cost budget, model identifier, prompt hash, and fail-closed fallback. The app remains demonstrable with recorded model packets if the provider is unavailable.

## 12. Runtime architecture

### Experience plane

A single judge cockpit presents the session as a sequence of evidence events using server-sent events. It does not become an alternative source of truth.

### Coordination plane

A small FastAPI service owns the typed state machine and invokes strategies, evidence workers, models, risk, and execution.

### Evidence plane

- DuckDB/Parquet for immutable research snapshots and option replays
- SQLite in WAL mode for sessions, decisions, warrants, broker events, and autopsies
- canonical JSON and SHA-256 for reproducible manifests

### Broker plane

Two least-privilege official Alpaca MCP processes target the same allowlisted paper account:

- market/reference data toolsets
- account/order/position toolsets

The trading process accepts only exact payloads backed by a valid warrant. Credentials never enter prompts, browser exports, logs, screenshots, or evidence bundles.

## 13. Authoritative state machine

The generic session states are:

`BOOTSTRAP -> PRECHECKED -> OBSERVING -> SNAPSHOT_FROZEN -> SIGNAL_CANDIDATE -> EVIDENCE_COMMITTED -> EVIDENCE_REVEALED -> RISK_APPROVED -> WARRANT_MINTED -> SUBMITTING -> WORKING -> FILLED -> EXITING -> CLOSED -> AUTOPSY`

Terminal or branch states are:

- `NO_SIGNAL`
- `REJECTED`
- `INSUFFICIENT_EVIDENCE`
- `AMBIGUOUS`
- `PARTIAL_OR_ANOMALOUS`
- `EXPIRED`
- `HALTED`

Any safety component may move the system to `HALTED`. No component may turn a rejection into approval. An ambiguous submission is reconciled by client order ID and broker state before any retry.

## 14. Deterministic risk and execution

The active hackathon risk profile requires:

- fresh $100,000 paper account and allowlisted account identifier
- paper endpoint and paper flag
- Level 3 options capability for spreads/Mleg
- one open strategy position
- maximum modeled loss of $500 per position
- daily loss halt at $1,000 including worst-case open loss
- high-water drawdown halt at 2%
- no averaging down, martingale, or Kelly sizing
- fresh, synchronized quotes and declared liquidity thresholds
- structural reward/risk of at least 3:1 for bounded debit structures
- conservative operational reward/risk of at least 3:1 after spreads and modeled costs
- mandatory strategy-specific time exit before the submission deadline on contest day

A warrant binds account, strategy and evidence versions, legs, ratios, side, quantity, maximum debit/credit, expected loss, quote timestamps, risk-vector hash, expiry, and nonce. It is consumed once.

Orders use `order_class=mleg`, limit pricing, deterministic client order IDs, at most two bounded reprices, and broker reconciliation. The position watchdog produces conservative executable exit limits and never fabricates fills.

## 15. Current Alpaca preflight

Verified manually in the signed-in Alpaca dashboard on 2026-09-04:

- Paper Trading account selected
- Options configuration: Level 3
- Cash: $100,000
- Equity: $100,000
- Options buying power: $100,000
- Position market value: $0
- Trades are not suspended

The official Alpaca MCP server version 2.3.1 is cached. Creating the paper API key, storing it outside the repository, and proving authenticated MCP capabilities remain pre-implementation steps.

## 16. Judge cockpit

The primary screen is a vertical proof timeline with six synchronized panels:

1. **Market Claim** — frozen snapshot, strategy version, deterministic trigger, and provenance.
2. **Sealed Jury** — pseudonymous twins, witness challenges, and visible outcome lock.
3. **Reveal** — ghost paths racing toward target/stop plus confidence and stability tests.
4. **3R Passport** — exact option legs, live/replay quotes, payoff, costs, loss cap, and all gates.
5. **Execution Warrant** — evidence hash, strategy hash, expiry, and consumed/unused state.
6. **Broker Truth** — sanitized MCP trace, order receipt, fills, position, exit, and paper/model P&L gap.

Secondary drawers provide the tournament bracket, Alpha Graveyard, rejection museum, test evidence, and architecture. The default view never starts as a wall of chat bubbles.

## 17. Ninety-second demo

1. **0–10s:** Show the verified $100,000 paper-only Level 3 account and the thesis.
2. **10–25s:** Select the promoted strategy and freeze a known replay event.
3. **25–40s:** Show blinded twins and agents cross-examining evidence; seal the cohort hash.
4. **40–55s:** Reveal ghost paths and the deterministic promotion/evidence result.
5. **55–70s:** Show exact Mleg, conservative 3R passport, $500 cap, and warrant.
6. **70–82s:** Submit/replay the Alpaca MCP order and reconcile broker truth.
7. **82–90s:** Open the tournament/Alpha Graveyard and finish: “Agreement is insufficient; only pre-registered evidence earns capital.”

The live path may correctly produce no trade. A deterministic recorded replay and sanitized prior paper order make the invention demonstrable regardless of that day's signal.

## 18. Acceptance criteria

### Strategy isolation

- A second strategy can be registered without modifying risk, warrant, execution, reconciliation, or event schemas.
- Replaying the same immutable dataset and manifest produces identical candidates and hashes.
- Every artifact identifies strategy, evidence, policy, model, and data versions.

### Evidence integrity

- Outcome fields, dates, and decodable row identities are inaccessible before commit.
- Altering a cohort, weight, parameter, prompt, quote, or order leg changes the relevant hash and invalidates downstream authorization.
- All tested final-holdout candidates appear in the Alpha Graveyard.
- Statistical gates name the confidence method, sample size, effective sample size, costs, censoring, and failure reason.

### Capital safety

- Live endpoints, wrong accounts, stale data, excessive loss, expired warrants, changed payloads, duplicate requests, and unknown positions fail closed.
- Timeout-after-submit is reconciled without duplicate exposure.
- Zero unauthorized orders are possible in property and lifecycle tests.
- Broker positions and orders override local state after restart.

### P&L credibility

- Performance uses timestamped option data or is explicitly labeled as underlying-only evidence.
- Results include every candidate, chronological split, costs, fill assumptions, drawdown, distribution, coverage, no-trade rate, and baselines.
- Paper P&L and conservative modeled P&L are displayed together.
- No claim implies guaranteed returns or confuses structural maximum payoff with expected return.

### Presentation

- A clean environment can run the deterministic 90-second replay from one command.
- The cockpit remains understandable without reading raw prompts.
- The project page, one-page AI/risk/infrastructure note, public repository, slides, video, account proof, and evidence bundle are ready before cutoff.

## 19. Non-goals for the hackathon release

- Live-money trading
- Automatic same-day strategy mutation after seeing holdout or paper outcomes
- Unbounded LLM authority
- Pretending correlated personas are independent evidence
- Claims based on hidden, selected, or unverifiable tests
- Production-scale cloud infrastructure unrelated to judge evidence

## 20. Approval boundary

Approval of this document authorized the implementation pass. It did not authorize live-money access or use of exposed recovery material. Paper order submission remains separately gated by credentials, the verified allowlisted account, deterministic risk, a valid single-use warrant, and the explicit execution feature flag.
