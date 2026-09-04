# Verification suite

The suite covers the official Alpaca CLI adapter, account binding and preflight,
live-shadow orchestration, exact-model Featherless routing and fail-closed schema
validation, option selection, sealed evidence integrity, reproducible exports,
independent tournament scoring, deterministic risk, Ed25519 warrant tampering and
replay, ambiguous-order reconciliation, executable-quote watchdog logic, and
recorded/live evidence labeling. It also covers paper-endpoint attestation,
subprocess secret isolation, remote API authorization, durable high-water risk state,
and a complete fake-broker entry/fill/signed-exit/autopsy lifecycle.

Run the full release gate from the repository root:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
pnpm --dir apps/web lint
pnpm --dir apps/web build
```
