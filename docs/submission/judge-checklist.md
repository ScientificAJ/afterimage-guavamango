# Judge-proof checklist

## P&L Performance

- [x] Separate L1 underlying, L2 historical option trade-bar, L3 sealed-trial, L4 shadow, and L5 Alpaca paper evidence without relabeling levels.
- [ ] Show timestamped option quotes, executable bid/ask assumptions, fees, and slippage.
- [x] Show expectancy distribution, 95% t-interval, drawdown, coverage, censoring, and sample size without hiding the negative result.
- [ ] Compare conservative modeled P&L with broker paper P&L; never call a fixture live P&L.
- [x] Freeze the controlled forward-paper window, exact models, config hashes, data hash, source/config tree hash, and no-bypass rules before market open.
- [x] Ship a deterministic verifier for the precommit self-hash, complete tracked-file manifest, source/config tree, and dataset binding.

## Technology Implementation

- [x] Demonstrate official Alpaca CLI 0.0.14 OAuth connectivity and current status.
- [x] Show one-way paper-account binding, ACTIVE state, Level 3, zero unknown exposure,
      and execution disabled.
- [x] Positively attest the CLI paper endpoint and pin its verified binary checksum.
- [x] Reconcile restart state through exact-position watchdog, signed close, and autopsy.
- [x] Run a full source security review and a separate bypass review; remediate every validated finding.
- [x] Demonstrate accepted replay reaching SHADOW_READY and rejection ending before warrant.
- [x] Test foreign-key, tamper, replay, account, freshness, position, and idempotency controls.
- [x] Export and independently recompute a stable evidence-core hash.

## Creativity & Originality

- [x] Make blind retrieval and commit-before-reveal visible within 30 seconds of the scripted cockpit demo.
- [x] Show one rejected candidate in the Alpha Graveyard.
- [x] Explain why role-separated information is more than a council of personas.
- [x] Show that `NO_CHAMPION` and `NO_TRADE` are valid results.
- [x] Demonstrate in tests that changing one warrant-bound field removes authority.

## Presentation & Execution

- [x] Keep the primary story within 90 seconds and avoid raw transcripts.
- [x] Record the deterministic fallback before touching the final demo environment.
- [x] Confirm cockpit at 1440×900 and mobile widths; retain semantic controls, visible keyboard focus, and reduced-motion CSS.
- [ ] Verify every claim links to a source artifact or exact reason code.
- [x] Keep credentials, raw account IDs, and recovery material out of video and public evidence exports; verify with a publication-scope scan.
- [x] Produce a 16:9 cover, editable 7-slide judge deck, visually verified PDF, and captioned 64-second MP4.
- [ ] Publish the sanitized immutable-replay cockpit and public repository after explicit external-egress approval.
