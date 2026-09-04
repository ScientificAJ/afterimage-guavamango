# Event/flow strategy-search report

## Winner — stateful shadow-clock early-week shock reversal

**ADMIT** under the stated high-but-attainable gates. This is backtested evidence, not a P&L guarantee.

| Period | Trades | Net R | PF | Expectancy | Max DD | Positive months | Underlyings |
|---|---:|---:|---:|---:|---:|---:|---:|
| Development 2018-2021 | 21 | +6.27 | 1.63 | +0.298R | 3.00R | 54.5% | 6 |
| Validation 2022-2024 | 58 | +24.77 | 2.09 | +0.427R | 4.75R | 69.0% | 8 |
| Recent pseudo-OOS 2025-2026 | 37 | +23.28 | 2.49 | +0.629R | 3.00R | 77.8% | 8 |
| Admission window 2022-2026 | 95 | +48.05 | 2.25 | +0.506R | 4.75R | 72.3% | 8 |

### Admission result

- PF 2.253; expectancy +0.506R across 95 trades.
- Max drawdown 4.75R; positive active months 72.3%.
- 1.5x-cost stress remains +46.88R with PF 2.222.
- 108/108 neighboring settings are profitable.
- Smallest modeled after-cost target/stop ratio: 3.0000:1.

### Causal idea

The agent keeps an always-on virtual position clock. A broad-universe, trend-aligned two-day liquidity shock starts a shadow position even when it will not be traded. Only Monday-Wednesday signals are sent to the paper-execution lane; Thursday-Friday shadow positions still consume the opportunity clock and impose a causal cooldown. This uses rejected opportunities as market memory instead of discarding them.

### Exact rule

- market_state: always advance one virtual shadow position across all weekdays
- signal: long-only; close above 100-day SMA and 50-day SMA above 100-day SMA; two-day return <= -0.6 ATR; close in bottom 25% of daily range
- cross_section: choose the most negative normalized two-day shock among 11 liquid ETFs
- execution_calendar: submit only signals completed Monday, Tuesday, or Wednesday
- cooldown: shadow position owns its exit session; next signal may complete the following session
- entry: next regular-session open
- risk: one ATR stop, cent-rounded after-cost >=3R target, five-session maximum hold
- ambiguity: stop first when daily OHLC contains both target and stop
- capital: $10,000 notional, one serialized opportunity clock

### Data and honesty

- Source: authenticated Alpaca CLI 0.0.14 historical stock bars; 1Day IEX bars.
- Cache hash: `9d770f80007093c046e4ce1b8e48d6bb61f05b8526745b341dd6f914b0cfcc0a`.
- The strategy-search process reused the chronological data. The report therefore says pseudo-OOS rather than pretending an untouched future exists.
- No order was submitted.

### Limitations

- The 2022-2026 evidence is iteratively reused pseudo-OOS, not a sealed future period.
- Alpaca IEX daily bars are not consolidated SIP and contain no bid/ask replay.
- The shadow clock is causal but adds state: skipped Thursday/Friday virtual positions can delay later execution.
- Historical fills use conservative explicit costs but do not model market impact or shorting because the strategy is long-only.
- Results are a backtest, not guaranteed future P&L.
