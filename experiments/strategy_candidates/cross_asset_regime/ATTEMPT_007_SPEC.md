# Attempt 007 — frozen active QQQ regime rule

## Hypothesis and freeze

Attempt 006's predeclared sensitivity grid revealed `qqq_regime_b5_m10_c3_s15` as its most active neighbor: 23 trades, +$388.68, +1.003R expectancy, PF 3.10, and 4.00R drawdown on 2024. This revealed result is hypothesis generation only, not admission or promotion.

Before any 2023 trade outcome is computed, attempt 007 freezes that exact rule without modification. No 2023 result may change the rule, execution model, or admission threshold.

## Exact frozen rule

- Universe inputs: completed regular-session 15-minute bars for QQQ, IWM, XLK, XLF, XLE, XLV, and XLY, plus lagged completed SPY daily closes.
- At 09:45 New York time, require at least five of seven overnight gaps aligned and a direction-adjusted mean gap of at least 0.10%.
- Require the QQQ 09:30–09:45 candle and at least three of five sector ETF first bars to confirm the gap direction.
- Define risk-on using the prior completed SPY close versus its prior 20-session SMA. Exclude only risk-on bullish signals.
- Trade QQQ shares only, maximum $10,000 notional, at the next 15-minute bar open.
- Model one bp adverse slippage per side and $0.005/share/side.
- Use a 0.15% raw-price stop and cent-round the target outward until its after-cost profit is at least 3.0 times the after-cost stop loss.
- Stop precedes target within an ambiguous bar; otherwise exit at target or after six bars. Maximum one position.

## Evidence protocol

- Evaluate 2023-01-03 through 2023-12-29 once after the rule hash is written.
- Bars from 2023-11-15 onward existed previously as warm-up inputs for the 2024 study, but no 2023 trade outcome or metric was computed. Label the result fresh outcome validation rather than untouched data.
- Report the fresh 2023 result first and separately. Only then show 2023+2024 as a provenance-labeled diagnostic pool.
- Apply all current gates to the fresh 2023 result, plus require the exact rule to be positive in both 2023 and 2024 for temporal stability.
- The neighbor-stability gate retains its provenance from the predeclared attempt-006 family; do not evaluate or select additional parameters on 2023.
- Include 1.5x cost, +2 bp per-side slippage, one-bar entry-delay, month, regime, drawdown, and profit-concentration diagnostics.
- Finalize after this attempt. Do not tune or promote a failed rule.
