# AFTERIMAGE judge release manifest

Generated and verified on 2026-09-04 before the controlled paper window.

| Artifact | SHA-256 | Verification |
| --- | --- | --- |
| `docs/submission/assets/afterimage-cover.png` | `7b0d80d1bc582411b7d7ec597fe655be354476d9ad5031d18499d059cec898f8` | Original-resolution visual inspection |
| `docs/submission/AFTERIMAGE_Judge_Deck_v3.pptx` | `5f9594724f17eed673485b7d53eafae7408a3109138ebe3087545771121c3443` | 7 slides; package, layout, font, import, and editable-chart/workbook validation passed |
| `output/pdf/AFTERIMAGE_Judge_Deck_v3.pdf` | `c86e9cbe07430bca979a1610cd76d64ad1c5a3de00b9b5ccd1fcc4e50b6f214e` | 7 pages; text extraction and page-by-page visual inspection passed |
| `output/video/AFTERIMAGE_Judge_Demo.mp4` | `1b8d6845fd7aca044491e27704eb7ee072a76dd49b6392b1fb24b219df35d1df` | 64.04 seconds; H.264 High, 1920×1080, 30 fps; seven representative frames inspected |
| `apps/web/public/demo/accepted.json` | `8865a1db455eb71cf6568e5af42b6140c85e61bbcd9cc03b3a27557c643a3243` | Immutable recorded control; publication-scope credential scan passed |
| `apps/web/public/demo/rejected.json` | `eb9f50d05379df7527591b14b756ba2e4a2d38962e3dfc727fd523d567e7b438` | Immutable recorded control; publication-scope credential scan passed |

## Release gates

- Python: 94 tests passed before the forward-precommit verifier/statistics additions; focused additions, Ruff, and strict mypy across 68 source files passed. A final whole-suite count will replace this line at freeze.
- Web: TypeScript lint and Next.js production build passed; desktop 1440×900 and mobile 390×844 public-replay renders inspected.
- Video: TypeScript passed; Remotion composition rendered from editable source under `apps/video`.
- Security: secrets, raw account identifiers, recovery material, private keys, and private datasets are excluded from the publication scope. The standalone trade MCP is permanently disabled; mutations use a frozen process-local OAuth profile, immediate paper/account re-attestation, signed warrants, and strict exposure parsing. Remote broker/model routes are not part of the public replay surface.
- Broker: official Alpaca CLI 0.0.14, positively attested paper endpoint, bound ACTIVE account, effective Level 3, zero orders, zero positions, execution disabled during the latest preflight.

## Claim boundary

The historical option study uses synchronized 5-minute trade-bar closes with modeled slippage; it is not quote replay or broker P&L. Alpaca CLI 0.0.14 exposes historical option bars/trades and latest quotes, not historical option quotes. The current family produced `-$126` across twelve one-lot paths: 4 wins, 8 losses, mean `-0.272R`, 95% t-interval `[-0.972R, +0.428R]`, and `$198` maximum drawdown. No champion was promoted. A self-verifying precommitted paper trial may produce a no-signal, rejection, order, fill, exit, or P&L receipt; nothing is relabeled or forced.

The public repository and deployment URL remain intentionally blank until explicit approval to publish the sanitized workspace to third parties.
