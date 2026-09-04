# Attempt 008 — multi-day regime-confirmed cross-sectional ETF momentum

## Rationale

Attempts 001–007 concentrated on first-hour continuation or catch-up and were vulnerable to intraday friction and unstable direction cells. Attempt 008 moves to a materially different causal horizon: a completed-daily-bar cross-sectional momentum signal with a multi-day holding window and ATR-scaled risk.

The family is declared before development evaluation. Already revealed 2023–2025 Alpaca bars are the only development data. No 2022 trade outcome may be computed until one exact rule is selected and hashed.

## Daily signal

- Inputs are completed regular-session daily OHLCV bars derived from authenticated Alpaca 15-minute IEX bars for SPY, QQQ, IWM, XLK, XLF, XLE, XLV, and XLY.
- At each session close, compute the variant's 20- or 40-session return across QQQ, IWM, XLK, XLF, XLE, XLV, and XLY.
- Risk-on requires SPY above its 50-session SMA, SPY above its close ten sessions earlier, and at least five of seven ETF returns positive. Risk-off requires the symmetric bearish conditions and at least five negative returns.
- Require cross-sectional return dispersion of at least 2.0 percentage points. In risk-on, select the strongest ETF; in risk-off, select the weakest ETF.
- The signal uses only the completed signal session. Enter long/short at the next session open.

## Frozen family

| Variant | Momentum lookback | Stop distance | Maximum hold |
|---|---:|---:|---:|
| `md_rs20_a50_h05` | 20 sessions | 0.50 × ATR(14) | 5 sessions |
| `md_rs20_a75_h05` | 20 sessions | 0.75 × ATR(14) | 5 sessions |
| `md_rs40_a50_h05` | 40 sessions | 0.50 × ATR(14) | 5 sessions |
| `md_rs40_a75_h05` | 40 sessions | 0.75 × ATR(14) | 5 sessions |

All variants use $10,000 maximum notional, one bp adverse slippage per side, $0.005/share/side, a cent-rounded after-cost target of at least 3R, stop-first daily-bar precedence, and maximum one open position.

## Development and fresh evidence protocol

- Evaluate the fixed family on already-revealed 2023–2025 only.
- Record expanding selections trained on 2023 and validated on 2024, then trained through 2024 and validated on 2025.
- Freeze the final exact rule using 2023–2025 development evidence only, requiring at least 60 development trades. The deterministic ranking is expectancy/R, then net P&L, then lexical name.
- After the exact rule hash is written, acquire 2022 Alpaca history and evaluate it once. Some Nov–Dec 2022 bars existed only as warm-up for attempt 007; no 2022 trade outcome or metric has been computed.
- Apply the full admission gates to fresh 2022, including 1.5x costs, monthly/fold stability, cross-symbol/regime support, neighbor stability from the fixed family, concentration, and target:stop.
- Do not select a neighbor or alter parameters after seeing 2022.
