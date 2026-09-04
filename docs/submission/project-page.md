# AFTERIMAGE — The trade is the last step of the proof

Most trading agents explain a decision. AFTERIMAGE proves the decision process was not quietly rewritten after seeing the answer.

When a strategy finds a setup, AFTERIMAGE freezes the exact point-in-time market snapshot. In the live path, a sealed twin trial retrieves comparable rows from a hash-validated Alpaca training partition without exposing their dates or outcomes. The cohort, weights, exclusions, strategy version, dataset, prompts, and model versions are durably committed. Only then are outcomes revealed. Deterministic code—not an LLM—checks effective sample size, a declared confidence bound, expectancy, drawdown, chronological stability, leave-one-cluster-out stability, placebo edge, and data coverage. The recorded judge controls use a separately labeled synthetic engineering fixture and make no performance claim.

Passing evidence is still not permission to trade. The proposed Alpaca options structure must clear structural and conservative operational reward/risk of at least 3:1, use executable bid/ask prices, fit a $500 modeled-loss ceiling, and satisfy account, clock, liquidity, exposure, daily-loss, and drawdown gates. Only then does a local Ed25519 authority issue a short-lived, single-use warrant bound to the exact Level 3 Mleg intent. One changed price, leg, quantity, account, strategy configuration, evidence hash, or deadline makes the warrant invalid. After a fill, a durable broker-truth loop requires an exact position match and fresh executable closing quotes; target, stop, or time exits receive a separate signed risk-reducing warrant.

## P&L Performance

AFTERIMAGE separates an underlying-path proxy, historical option trade-bar validation, shadow decisions, and Alpaca paper fills into explicit evidence levels. It reports distributions, R expectancy, drawdown, confidence bounds, censoring, and modeled-versus-broker slippage instead of promoting one screenshot. No 3:1 payoff is claimed unless both the structural payoff and the operational target/stop payoff clear 3R after modeled costs.

The implementation includes deterministic accepted and rejected synthetic controls,
plus a live shadow path verified against the dedicated Alpaca paper account and
current Alpaca market data. The current research artifact contains 32,346 real SPY
IEX bars. Twelve chronological opening-range signals were matched without exclusion
to real expired-contract metadata and synchronized option trade bars; after $0.01
one-way slippage per leg, the disclosed one-lot sequence is -$126. This is a trade-bar
study, not bid/ask replay or broker P&L. Controlled paper execution is now authorized,
but L5 P&L remains empty until a naturally qualifying setup fills and exits.

## Technology Implementation

- Python typed contracts, generic strategy plugins, a deterministic state machine, SQLite WAL persistence, and a hash-chained audit ledger.
- The checksum-pinned official Alpaca CLI 0.0.14 with OAuth, positive paper-endpoint
  attestation, account-and-endpoint binding, live bars,
  bounded option-chain retrieval, local order dry-run, and an optional separated MCP
  transport.
- Provider-neutral structured-output agents backed by exact Featherless routes
  `zai-org/GLM-5.3` and `zai-org/GLM-5.3-Flash`, with strict schemas, redaction,
  deterministic sampling, timeouts, abstention, and recorded controls.
- Outcome and feature vault separation, content-addressed evidence, and commit/reveal verification.
- Deterministic payoff, sizing, durable daily-loss/high-water state, Ed25519 entry and exit warrants, idempotent client-order IDs, restart reconciliation, exact-position watchdog, and broker-fill autopsy.
- FastAPI, resumable SSE, CLI operations, evidence export, and a responsive Next.js judge cockpit.

## Creativity & Originality

The novelty is not another multi-agent debate. It is a chain of custody for trading authority:

**pre-register → retrieve blind → commit → reveal → challenge → verify risk → sign exact intent → reconcile broker truth.**

The strategy tournament runs every registered implementation against the same real Alpaca chronological partition. Every loser remains visible in the Alpha Graveyard. A ranking score cannot override a failed hard gate. The current reveal correctly promotes no champion. Because this partition has now been revealed to the developer, it is described as chronological and hash-bound—not untouched.

## Presentation & Execution

The cockpit tells the entire story in six visible moments: Market Claim, Sealed Jury,
Ghost Paths, 3R Passport, Execution Warrant, and Broker Truth. It supports accepted
and rejected recorded controls plus a real live-shadow action. Ghost paths are
computed from revealed observations, broker panels never manufacture P&L, and the
audit timeline is replayed over SSE.

## Safety and scope

AFTERIMAGE is paper-only, positively verifies Alpaca's paper endpoint, forces an allowlisted account with effective Options Level 3, and disables paper order submission by default. The exact Featherless routes are `zai-org/GLM-5.3` and `zai-org/GLM-5.3-Flash`; neither model owns execution authority. It does not provide investment advice or guarantee returns. Real credentials are excluded from Git, exported artifacts, screenshots, and prompts.

## Judge package

- Cover: `docs/submission/assets/afterimage-cover.png`
- Editable deck: `docs/submission/AFTERIMAGE_Judge_Deck_v3.pptx`
- Rendered deck: `output/pdf/AFTERIMAGE_Judge_Deck_v3.pdf`
- Captioned demo: `output/video/AFTERIMAGE_Judge_Demo.mp4`
- Real-data receipts: `evidence/research/`
- Tournament receipt: `evidence/tournament/spy-real-v1-results.json`

The public web build uses immutable recorded engineering replays only. Live broker
and model work remains in the authenticated local operator cockpit.
