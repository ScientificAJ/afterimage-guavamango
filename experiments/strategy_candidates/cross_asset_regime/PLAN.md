# Cross-asset Breadth Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, no-lookahead Alpaca-backed evaluation of the frozen cross-asset breadth rotation family and a non-submitting MLEG dry run.

**Architecture:** `candidate.py` owns pure signals, contract choice, conservative execution, metrics, and selection. `run_research.py` owns authenticated read-only acquisition, cache provenance, chronological orchestration, and reports. `dry_run.py` owns exact official CLI serialization and the hard non-submission boundary.

**Tech Stack:** Python 3.11 standard library, pytest, official Alpaca CLI 0.0.14.

**Spec:** `experiments/strategy_candidates/cross_asset_regime/SPEC.md`

## Global Constraints

- Work only below `experiments/strategy_candidates/cross_asset_regime/`.
- Keep the four original variants plus their four predeclared 3R/1R exit neighbors and fixed parameters in the spec.
- Development ends 2026-07-31; final holdout is 2026-08-03 through 2026-09-03.
- Alpaca access is authenticated and read-only except `order submit ... --dry-run`, which does not transmit.
- Never impute missing option bars and never permit overlapping positions.

---

### Task 1: Pure strategy and execution engine

**Files:**
- Create: `experiments/strategy_candidates/cross_asset_regime/candidate.py`
- Test: `experiments/strategy_candidates/cross_asset_regime/tests/test_candidate.py`

**Interfaces:**
- Produces: `signal_for_session`, `select_vertical`, `simulate_trade`, `summarize`, `select_on_training`, and frozen `VARIANTS`.

- [ ] Write failing tests with hand-derived fixtures proving completion-time causality, symmetric breadth, relative-strength instrument choice, lagged SPY regime filtering, exact $5 vertical choice, adverse two-leg fills, fixed exit, fees, max-one overlap exclusion, drawdown, and training-only selection.
- [ ] Run `pytest -q experiments/strategy_candidates/cross_asset_regime/tests/test_candidate.py` and confirm failures are missing imports/behavior.
- [ ] Implement immutable value objects and the minimal pure functions required by those tests.
- [ ] Re-run the candidate tests and confirm zero failures.

### Task 2: Safe data acquisition and research orchestration

**Files:**
- Create: `experiments/strategy_candidates/cross_asset_regime/run_research.py`
- Test: `experiments/strategy_candidates/cross_asset_regime/tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1 pure interfaces and official CLI JSON responses.
- Produces: `data/market_cache.json`, `results/backtest.json`, and `REPORT.md`.

- [ ] Write failing tests proving mutation-token rejection, pagination normalization, deterministic cache hashing, fixed date partitions, expanding folds, and serialization of all required metrics/limitations.
- [ ] Run the pipeline tests and confirm expected failures.
- [ ] Implement CLI reads for IEX 15-minute stock bars, active/inactive contract discovery, and 15-minute historical option bars; include command provenance and content hashes.
- [ ] Implement a single evaluation pass that selects from January–July only and touches the August–September holdout only after freezing the winner.
- [ ] Re-run both test files and confirm zero failures.

### Task 3: Exact MLEG dry run

**Files:**
- Create: `experiments/strategy_candidates/cross_asset_regime/dry_run.py`
- Test: `experiments/strategy_candidates/cross_asset_regime/tests/test_dry_run.py`

**Interfaces:**
- Produces: `build_debit_payload`, `build_cli_arguments`, `validate_dry_run_arguments`, and `results/alpaca_mleg_dry_run.json`.

- [ ] Write failing tests proving signed positive debit price, leg intents, one terminal `--dry-run`, rejection without it, and sanitized public account fields.
- [ ] Run the dry-run tests and confirm expected failures.
- [ ] Implement payload building, current contract/quote selection, account capability checks, and official CLI dry-run capture without POST.
- [ ] Re-run all isolated tests and confirm zero failures.

### Task 4: Acquire, evaluate once, and verify

**Files:**
- Create: `experiments/strategy_candidates/cross_asset_regime/data/market_cache.json`
- Create: `experiments/strategy_candidates/cross_asset_regime/results/backtest.json`
- Create: `experiments/strategy_candidates/cross_asset_regime/results/alpaca_mleg_dry_run.json`
- Create: `experiments/strategy_candidates/cross_asset_regime/REPORT.md`

**Interfaces:**
- Consumes: Tasks 1–3 runnable CLIs.
- Produces: complete reproducible evidence package.

- [ ] Run `python experiments/strategy_candidates/cross_asset_regime/run_research.py --fetch` once to fetch and evaluate the frozen development and holdout ranges.
- [ ] Generate the exact current MLEG artifact with `python experiments/strategy_candidates/cross_asset_regime/dry_run.py` using the frozen signal logic.
- [ ] Run `pytest -q experiments/strategy_candidates/cross_asset_regime/tests` and `python -m compileall -q experiments/strategy_candidates/cross_asset_regime`.
- [ ] Inspect hashes, result counts, exclusion accounting, report tables, and `submitted=false`; report negative or inconclusive results without suppression.
