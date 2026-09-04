# AFTERIMAGE / GuavaMango

**The trade is the last step of the proof.**

AFTERIMAGE is a strategy-pluggable autonomous trading agent connected to a dedicated Alpaca paper account. Its admitted strategy, **GuavaMango**, searches 11 liquid ETFs for a two-day liquidity shock inside an established uptrend, then proposes a next-session long equity bracket only when the entire decision chain clears. Its distinctive mechanism is a stateful **shadow clock**: even Thursday and Friday setups that are intentionally not traded still occupy a virtual position and cooldown. Rejected opportunities therefore become causal market memory instead of disappearing from the strategy's history.

## AI logic

The signal is deterministic and falsifiable: price must be above its 100-session moving average, the 50-session average must exceed the 100-session average, the two-day return must be at most -0.6 ATR, and the close must be in the bottom 25% of the day's range. GuavaMango selects the most negative normalized shock across QQQ, IWM, XLK, XLF, XLE, XLV, XLY, XLI, XLP, TLT, and GLD. Eligible signals complete Monday through Wednesday, enter at the next regular-session open, use a one-ATR stop, target at least 3R after modeled costs, and time out after five sessions.

AI challenges the trade; it does not own execution authority. A four-role Featherless desk receives frozen, role-specific evidence packets. `zai-org/GLM-5.3` powers the strategist and the adversarial prosecutor; `zai-org/GLM-5.3-Flash` powers the regime and execution witnesses. Every material finding must cite an exact packet field, distinguish observation from inference, and name falsifiers. Missing, malformed, stale, or contradictory evidence produces a challenge or abstention, not invented confidence. A recorded live Featherless receipt verifies both exact routes and demonstrates that the desk blocks an under-evidenced candidate.

## Risk gates and authority

Deterministic code—not an LLM—checks the paper endpoint and bound account, market and cutoff state, admitted strategy evidence, quote age, leg synchronization, spread, quantity, position collisions, unknown orders, daily loss, and high-water drawdown. It enforces both structural and operational reward-to-risk of at least 3:1, a $500 maximum modeled loss, a $10,000 equity-notional ceiling, one open strategy position, a $1,000 daily-loss halt, and a 2% drawdown halt.

A passing decision creates a 20–30 second, single-use Ed25519 execution warrant bound to the exact account hash, strategy authority hash, evidence hash, quote vector, risk vector, symbol or option legs, side, quantity, prices, and nonce. Change one field, let it expire, or consume it twice, and the warrant fails. Deterministic client order IDs make retries idempotent. After submission, Alpaca's orders and positions—not local memory or the model—are broker truth; restart reconciliation, an exact-position watchdog, separately signed exits, and a fill autopsy complete the lifecycle.

## Alpaca and options implementation

The operational path uses the checksum-pinned official Alpaca CLI 0.0.14 with OAuth, positive attestation of `https://paper-api.alpaca.markets`, one-way account binding, real account/clock/order/position checks, authenticated IEX market data, local dry-run rendering, and optional paper submission. An Alpaca MCP 2.3.1 transport is also implemented with separated data and trading toolsets for read/dry-run workflows. The connected account was verified ACTIVE at $100,000 with effective Options Level 3 and zero unknown exposure.

GuavaMango's admitted lane executes equity brackets. The same strategy-independent AFTERIMAGE pipeline also contains bounded Alpaca option-chain discovery, contract filtering, synchronized quote handling, defined-risk multi-leg construction, Greeks/liquidity inputs, structural and operational payoff previews, Level 3 Mleg intent construction, and option-specific risk gates. Options are a first-class execution component rather than a claim that the equity backtest represents option P&L.

## Evidence and results

Research used authenticated Alpaca IEX daily bars from 2018 through September 3, 2026. In the 2022–2026 admission window, GuavaMango produced **95 trades, +48.05R net, 2.253 profit factor, +0.506R expectancy per trade, 4.746R maximum drawdown, 72.34% positive active months, and eight profitable underlyings**. All five annual folds were positive. At 1.5× modeled costs it retained +46.88R and a 2.222 profit factor, and all 108 immediate parameter neighbors remained profitable. The minimum modeled after-cost target-to-stop ratio was 3.000013.

Those figures are a cost-aware backtest, not broker P&L. The 2022–2026 period was visible during iterative research, so it is labeled pseudo-out-of-sample rather than untouched. IEX daily bars are not SIP quotes and do not reconstruct historical bid/ask or market impact. The fresh paper account is connected for forward validation; no strategy-violating trade was forced merely to manufacture activity. Every admitted metric, prior failed attempt, limitation, source/config hash, and research result is preserved as inspectable evidence.

The implementation is MIT-licensed and includes Python 3.11, Pydantic, FastAPI, SQLAlchemy/SQLite WAL, DuckDB, PyArrow, asyncio, cryptography/Ed25519, Typer, Alpaca CLI/MCP, Featherless AI, Next.js 16, React 19, TypeScript, Recharts, resumable SSE, and an interactive judge cockpit. The current suite passes **297 tests**.

*Paper trading only. Historical results do not guarantee future returns; this project is not investment advice.*
