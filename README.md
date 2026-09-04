# AFTERIMAGE

AFTERIMAGE is an evidence-gated autonomous options agent for Alpaca paper trading. A
strategy cannot reach execution until its point-in-time evidence has been selected
blindly, committed durably, revealed, evaluated by deterministic policy, and bound to
the exact Mleg order by a short-lived single-use warrant.

The system is paper-only. It does not provide investment advice or promise returns.

## Architecture

- `src/afterimage/strategies`: replaceable signal and option-structure policies
- `src/afterimage/evidence`: outcome-blind twin selection and commit/reveal
- `src/afterimage/agents`: Featherless strategist, witnesses, and prosecutor
- `src/afterimage/risk`: deterministic payoff, limits, and warrant authority
- `src/afterimage/execution`: least-privilege Alpaca MCP and reconciliation
- `src/afterimage/tournament`: sealed strategy promotion and Alpha Graveyard
- `apps/web`: judge cockpit

## Local setup

```bash
uv sync --all-groups
cp .env.example .env
uv run afterimage demo --fixture accepted
uv run afterimage serve
```

Run the cockpit separately with the bundled pnpm runtime:

```bash
pnpm --dir apps/web install
pnpm --dir apps/web dev
```

Keep all credentials in the ignored `.env`. `ALPACA_PAPER_TRADE=true` is mandatory.

## Operational commands

```bash
uv run afterimage replay --fixture accepted
uv run afterimage replay --fixture rejected
uv run afterimage preflight
uv run afterimage shadow
uv run afterimage tournament develop
uv run afterimage tournament reveal
uv run afterimage export-evidence --fixture accepted
```

Paper execution is deliberately disabled by default. Enabling it does not bypass any
gate: `execute` accepts only a persisted, unexpired warrant ID, re-runs account
preflight, verifies the bound account hash, consumes the nonce, and submits the exact
Mleg intent. Never enable it for a live account.

The deterministic replays prove system behavior and are labeled recorded-paper. They
are not claimed live returns. Full tests, historical strategy refinement, forward
paper validation, and submission hardening are separate follow-on passes.
