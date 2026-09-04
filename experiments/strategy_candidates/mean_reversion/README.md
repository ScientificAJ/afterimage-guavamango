# Isolated strategy-candidate laboratory

This directory contains a completed, read-only Alpaca historical research search. It does not modify production strategy code and does not place orders.

Key artifacts:

- `FINAL_REPORT.md`: consolidated decision and implementation contract.
- `leaderboard.json`: machine-readable ranked results and admission floors.
- `attempts/ledger.json`: append-only attempt ledger with SHA-256 hashes.
- `attempts/<attempt>/`: immutable result, report, and order dry-run artifacts.
- `tests/`: timing, embargo, fill, metric, contract, ledger, and dry-run tests.

All live/paper submission remains disabled. The generated commands use `--dry-run`, and pair attempts additionally require coordinated two-leg execution that is intentionally not implemented here.
