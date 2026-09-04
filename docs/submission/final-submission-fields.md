# Recommended lablab.ai submission fields

## Title

AFTERIMAGE — GuavaMango

## Short description / tagline

An autonomous Alpaca agent where market memory finds the trade, a four-model jury attacks it, and only a cost-aware 3R, cryptographically signed intent can reach the broker.

**Length:** 173 characters including spaces.

## Long description

AFTERIMAGE is an autonomous trading agent connected to a dedicated $100,000 Alpaca paper account. GuavaMango scans 11 liquid ETFs for a two-day liquidity shock inside an established uptrend. Its “shadow clock” carries skipped opportunities forward as causal market memory, so live behavior matches the research.

On authenticated Alpaca IEX daily data, the 2022–2026 admission window produced 95 trades, +48.05R net, a 2.253 profit factor, +0.506R expectancy per trade, and 4.746R maximum drawdown. All five annual folds were positive, 108/108 immediate parameter neighbors remained profitable, and 1.5× modeled costs retained +46.88R with a 2.222 profit factor. These are cost-aware historical pseudo-out-of-sample results, not broker P&L.

A four-role Featherless decision desk attacks every candidate. GLM-5.3 runs the strategist and prosecutor; GLM-5.3-Flash runs the regime and execution witnesses. Each claim must cite the frozen evidence packet. Risk code enforces paper-only operation, account and market state, executable-price quality, exposure limits, a $500 modeled-loss ceiling, and structural plus operational reward-to-risk of at least 3:1. A short-lived, single-use Ed25519 warrant binds the evidence, risk vector, quote, account, quantity, and order intent before submission.

The broker path uses the official Alpaca CLI 0.0.14 with OAuth, endpoint attestation, authenticated market data, dry runs, optional paper execution, reconciliation, watchdog exits, and fill autopsy. A separate Alpaca MCP transport and Level 3 options lane support chain discovery, defined-risk multi-leg construction, payoff previews, and Mleg intents. GuavaMango executes equity brackets; options are an independently tested platform capability. The responsive Flight Deck exposes performance, positions, AI reasoning, risk gates, orders, options, and the Market Data → Signal → AI Jury → Risk → Warrant → Alpaca workflow.

## Technologies

Python 3.11; Pydantic; FastAPI; SQLAlchemy; SQLite WAL; DuckDB; PyArrow; asyncio; cryptography/Ed25519; Typer; Alpaca Trading API; official Alpaca CLI 0.0.14; Alpaca MCP 2.3.1; Alpaca IEX market data; Featherless AI; GLM-5.3; GLM-5.3-Flash; Next.js 16; React 19; TypeScript; Recharts; SSE; uv; pnpm.

## Suggested tags

AI Agents, Algorithmic Trading, FinTech, Options, Risk Management, Alpaca, Featherless AI, Open Source

## One-page explanation

Upload or link `docs/submission/one-page-final.md` (convert to PDF only if the form requires an upload rather than pasted text).

## Required account field

Paste the **raw dedicated Alpaca paper account ID from the logged-in Alpaca dashboard** into the private paper-account field. Do not use the one-way SHA-256 binding stored in the repository, and do not put the raw ID in Git, screenshots, descriptions, or the public one-page write-up.

## URL and asset fields

- **Application URL:** use the final public read-only Flight Deck URL.
- **GitHub repository:** use the final public MIT-licensed repository URL.
- **Video:** upload the final MP4, no longer than five minutes.
- **Presentation:** upload the final PDF exported from `docs/submission/AFTERIMAGE_GuavaMango_Judge_Deck_v8.pptx`.
- **Cover image:** upload `docs/submission/assets/afterimage-cover.png`.

Do not submit localhost URLs or the private voice-recorder URL.

## Alpaca integration answer

AFTERIMAGE uses the checksum-pinned official Alpaca CLI 0.0.14 as its broker-truth path for OAuth account/endpoint attestation, current paper account state, authenticated IEX bars, option contracts and quotes, local order dry runs, optional paper submission, order lookup, position reconciliation, and exits. It also implements Alpaca MCP 2.3.1 as a separated data/trading read-and-dry-run transport. The runtime is bound to one positively attested paper endpoint and one account hash. GuavaMango executes next-session equity brackets; the platform's Level 3 options component supports chain discovery, defined-risk multi-leg selection, payoff/risk validation, and Mleg intent construction.

## AI model roles answer

- **Strategist — `zai-org/GLM-5.3`:** builds the strongest packet-grounded, falsifiable trade-or-no-trade thesis.
- **Regime witness — `zai-org/GLM-5.3-Flash`:** independently tests trend, volatility, liquidity, session, and causal fit.
- **Execution witness — `zai-org/GLM-5.3-Flash`:** audits instrument, quotes, spread, costs, sizing, exits, and options details when applicable.
- **Prosecutor — `zai-org/GLM-5.3`:** receives the raw packets plus the other reports, then searches for leakage, overfitting, stale data, unsupported citations, and implementation mismatch.

All outputs use strict schemas and exact evidence paths. Models may support, challenge, or abstain; deterministic evidence and risk code alone can create execution authority.

## Results answer

Authenticated Alpaca IEX daily research, 2022–2026 admission window: 95 trades; +48.05R net; 2.253 profit factor; +0.506R expectancy/trade; 56.84% hit rate; 4.746R maximum drawdown; 72.34% positive active months; eight profitable underlyings; all five annual folds positive. Robustness: +46.88R and 2.222 profit factor at 1.5× modeled costs; 108/108 immediate parameter neighbors profitable; minimum after-cost target-to-stop ratio 3.000013. These are historical, cost-aware pseudo-OOS results, not Alpaca broker P&L. The paper account is connected for forward validation, and no forced trade was used to manufacture activity.

## Submission checklist

- Replace every URL placeholder with a public, judge-accessible link.
- Use the raw Alpaca paper account ID only in the required private form field.
- Verify the video plays, the PDF opens, the cover is 16:9, and the app loads in an incognito window.
- Keep the backtest/broker-P&L distinction intact in every field.
- Submit the form and capture the success/confirmation screen.
