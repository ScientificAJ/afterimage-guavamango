# Volatility Premium Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evaluate an isolated, runnable SPY put-credit-spread volatility-premium candidate on real Alpaca history, then validate its exact order shape with an official CLI dry run.

**Architecture:** Pure standard-library Python modules parse cached Alpaca records into immutable dataclasses, select contracts without future price information, apply an adverse trade-bar execution model, and produce deterministic JSON. Separate CLI scripts acquire read-only data, run the chronological evaluation, and perform only an order `--dry-run`.

**Tech Stack:** Python 3.11, standard library, pytest 8, official Alpaca CLI adapter already pinned by AFTERIMAGE.

**Spec:** `experiments/strategy_candidates/volatility_premium/SPEC.md`

## Global Constraints

- Do not modify shared production files or configuration.
- Do not submit, replace, or cancel any order.
- Keep the three declared families and 2026-07-01 through 2026-09-03 OOS split fixed.
- Call historical prices trade-bar bounds, not quotes or fills.
- Use $0.01 per leg per side slippage and $0.03 per contract per side fees.
- Exclude malformed or unsynchronized data; do not impute it.

---

### Task 1: Core price model and metrics

**Files:**
- Create: `experiments/strategy_candidates/volatility_premium/candidate.py`
- Create: `experiments/strategy_candidates/volatility_premium/tests/test_candidate.py`

**Interfaces:**
- Produces: `Family`, `Contract`, `OptionBar`, `Trade`, `adverse_entry_credit()`, `adverse_exit_debit()`, `simulate_trade()`, and `summarize()`.

- [ ] **Step 1: Write failing arithmetic and first-passage tests**

Create bars whose entry credit is `short.low - long.high - 0.02`, whose exit debit is `short.high - long.low + 0.02`, and assert round-trip fees are `$0.12` for two legs.

- [ ] **Step 2: Verify the tests fail**

Run: `uv run pytest experiments/strategy_candidates/volatility_premium/tests/test_candidate.py -q`

Expected: collection fails because `candidate` does not exist.

- [ ] **Step 3: Implement immutable records and deterministic arithmetic**

Use `Decimal` at all money boundaries. Reject non-positive credits, width violations, nonmatching timestamps, and missing exit observations with a named `DataExclusion`.

- [ ] **Step 4: Verify the focused tests pass**

Run the Task 1 pytest command and require zero failures.

### Task 2: Lagged selection and walk-forward freeze

**Files:**
- Modify: `experiments/strategy_candidates/volatility_premium/candidate.py`
- Modify: `experiments/strategy_candidates/volatility_premium/tests/test_candidate.py`

**Interfaces:**
- Produces: `daily_features()`, `select_contract_pair()`, `evaluate_family()`, and `freeze_family()`.

- [ ] **Step 1: Write failing no-lookahead and family-freeze tests**

Assert a session's trend/volatility feature uses closes through the prior session only, contract expiry/strike selection follows the fixed family, and changing OOS trades cannot alter `freeze_family()`.

- [ ] **Step 2: Verify the new tests fail for missing behavior**

Run the focused pytest command and inspect the expected assertion or import failure.

- [ ] **Step 3: Implement the minimum selection and walk-forward logic**

Score expanding folds ending 2026-03-31, 2026-04-30, 2026-05-29, and 2026-06-30; select on aggregate walk-forward R, then lower drawdown, larger sample, and declared family order.

- [ ] **Step 4: Verify all focused tests pass**

Run the focused pytest command and require zero failures.

### Task 3: Read-only acquisition and reproducible backtest runner

**Files:**
- Create: `experiments/strategy_candidates/volatility_premium/acquire.py`
- Create: `experiments/strategy_candidates/volatility_premium/run_backtest.py`
- Create: `experiments/strategy_candidates/volatility_premium/tests/test_pipeline.py`
- Create: `experiments/strategy_candidates/volatility_premium/data/manifest.json`

**Interfaces:**
- `acquire.py` emits normalized stock bars, contract metadata, option bars, source commands, retrieval timestamps, and hashes.
- `run_backtest.py` consumes those records and emits `results/backtest.json`.

- [ ] **Step 1: Write failing tests for CLI allowlisting, hashes, partitions, exclusions, and JSON schema**

Use a fake runner and assert every acquisition command starts with `data` or `option contracts`; assert no `order` token is accepted by acquisition; assert output carries all three variant summaries and separate walk-forward/OOS metrics.

- [ ] **Step 2: Verify the pipeline tests fail**

Run: `uv run pytest experiments/strategy_candidates/volatility_premium/tests/test_pipeline.py -q`

- [ ] **Step 3: Implement acquisition and orchestration**

Reuse the repo's authenticated official CLI gateway only as a read-only dependency. Cache responses before evaluation and hash canonical JSON. Make `run_backtest.py` deterministic over the cache.

- [ ] **Step 4: Fetch data and iterate without changing the declared families or split**

Run acquisition against real Alpaca. If coverage is poor, broaden retrieval/batching only; do not tune OOS strategy parameters.

- [ ] **Step 5: Run the backtest once on the frozen OOS partition**

Write the full trade/exclusion trail and variant summaries to `results/backtest.json`.

### Task 4: Exact Alpaca MLEG dry-run artifact

**Files:**
- Create: `experiments/strategy_candidates/volatility_premium/dry_run.py`
- Modify: `experiments/strategy_candidates/volatility_premium/tests/test_pipeline.py`
- Create: `experiments/strategy_candidates/volatility_premium/results/alpaca_mleg_dry_run.json`

**Interfaces:**
- Produces: `build_entry_payload()` and an artifact containing account capability facts, selected active symbols, exact CLI arguments, and official dry-run response.

- [ ] **Step 1: Write a failing payload and mutation-boundary test**

Assert `order_class=mleg`, `type=limit`, `time_in_force=day`, two Level-3 legs with opening intents, and a mandatory terminal `--dry-run`; reject command construction without it.

- [ ] **Step 2: Verify the test fails**

Run the pipeline pytest command and inspect the expected missing import/behavior.

- [ ] **Step 3: Implement the payload and dry-run command**

Select live contracts from read-only chain data, derive the live limit from current quote fields only, and invoke the pinned CLI with `--dry-run`. Never call a mutation API without that flag.

- [ ] **Step 4: Run official dry-run and save the response**

Require account options level at least 3 and save no account identifier or credential.

### Task 5: Report and fresh verification

**Files:**
- Create: `experiments/strategy_candidates/volatility_premium/REPORT.md`
- Create: `experiments/strategy_candidates/volatility_premium/README.md`

**Interfaces:**
- Documents reproducible commands and the implementation contract for parent integration.

- [ ] **Step 1: Generate report tables from `results/backtest.json`**

Report every variant's sample count, net P&L, expectancy/R, hit rate, max drawdown, exclusions, parameter-neighbor stability, and OOS result. Explicitly state whether a candidate is supported.

- [ ] **Step 2: Run all candidate tests**

Run: `uv run pytest experiments/strategy_candidates/volatility_premium/tests -q`

- [ ] **Step 3: Run lint and deterministic rerun checks**

Run: `uv run ruff check experiments/strategy_candidates/volatility_premium`

Run the backtest twice and compare the canonical result hashes.

- [ ] **Step 4: Inspect candidate-only diff and artifact parseability**

Run: `git status --short experiments/strategy_candidates/volatility_premium` and parse every JSON artifact with `python -m json.tool`.

### Task 6: Freeze Attempt 01 and add immutable ledger

**Files:**
- Create: `experiments/strategy_candidates/volatility_premium/ledger.py`
- Create: `experiments/strategy_candidates/volatility_premium/tests/test_ledger.py`
- Create: `experiments/strategy_candidates/volatility_premium/results/attempt-01-vrp-put-credit.json`
- Create: `experiments/strategy_candidates/volatility_premium/results/attempt-ledger.json`

**Interfaces:**
- Produces: `append_attempt()` with a previous-ledger-hash chain and duplicate-ID refusal.

- [ ] Write and observe failing immutability/hash-chain tests.
- [ ] Implement minimal ledger behavior and make focused tests green.
- [ ] Copy Attempt 01 bytes to its permanent filename and record file hash, expectancy, operational target:stop, profit factor, and rejection verdict.

### Task 7: SPY+QQQ pivot engine and nested rolling evaluator

**Files:**
- Create: `experiments/strategy_candidates/volatility_premium/pivots.py`
- Create: `experiments/strategy_candidates/volatility_premium/tests/test_pivots.py`

**Interfaces:**
- Produces fixed momentum-debit and compression-condor family declarations, adverse multi-leg simulators, lagged signals, monthly family selection, per-symbol metrics, profit factor, operational target:stop, and promotion gates.

- [ ] Write failing tests for debit/condor arithmetic, 3:1 post-cost exits, lag-only signals, monthly selection boundaries, cross-symbol summaries, and every promotion gate.
- [ ] Implement the minimal pure engine and make focused tests green.

### Task 8: Acquire and score real pivot data

**Files:**
- Create: `experiments/strategy_candidates/volatility_premium/acquire_pivots.py`
- Create: `experiments/strategy_candidates/volatility_premium/run_pivots.py`
- Create: `experiments/strategy_candidates/volatility_premium/data/pivot_market_cache.json`
- Create: `experiments/strategy_candidates/volatility_premium/results/attempt-02-directional-debit.json`
- Create: `experiments/strategy_candidates/volatility_premium/results/attempt-03-iron-condor.json`

**Interfaces:**
- Read-only official CLI data acquisition for SPY and QQQ; deterministic result artifacts consumed by the ledger.

- [ ] Write and observe failing cache/evaluation contract tests.
- [ ] Implement acquisition with only stock/option read paths.
- [ ] Fetch real records, run expanding monthly folds, and record all variants/exclusions/stability/gates.
- [ ] Append both immutable attempt artifacts to the ledger without rewriting Attempt 01.

### Task 9: Pivot report and verification

**Files:**
- Modify: `experiments/strategy_candidates/volatility_premium/REPORT.md`
- Modify: `experiments/strategy_candidates/volatility_premium/README.md`

**Interfaces:**
- Reports the strongest statistically defensible candidate or explicitly exhausts the approved ideas.

- [ ] Report pooled/per-symbol/per-month/all-neighbor results, operational target:stop, profit factor, and every gate.
- [ ] Re-run full tests, lint, format, deterministic hashes, JSON embedded hashes, and ledger-chain checks.
