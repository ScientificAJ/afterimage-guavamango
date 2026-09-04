# Attempt 006 — QQQ regime-conditioned breadth gap continuation

## Hypothesis and frozen scope

Attempt 005's already-revealed 2025 extension showed that QQQ was stronger than IWM and that bullish entries during a lagged SPY risk-on regime were the only materially weak regime/direction cell. This is hypothesis generation only. Attempt 006 is frozen before any 2024 trade outcome is computed and will be evaluated once on 2024.

The family is materially distinct from attempt 005: it trades QQQ only, uses a lagged SPY 20-session regime exclusion, requires first-bar confirmation from the sector ETF breadth rather than IWM, and has a one-factor neighboring set. It never selects a variant using 2024 results.

## Signal at 09:45 New York time

- Use completed regular-session 15-minute bars for QQQ, IWM, XLK, XLF, XLE, XLV, and XLY, plus lagged completed SPY daily closes.
- Calculate each universe ETF's overnight gap from the prior regular-session close to the current 09:30 open.
- Determine a bullish/bearish direction only if the predeclared breadth count and absolute direction-adjusted mean-gap threshold are met.
- Require the QQQ 09:30–09:45 candle to confirm the direction and at least the predeclared count among XLK, XLF, XLE, XLV, and XLY to confirm it.
- Define risk-on as the last completed SPY close greater than or equal to its prior 20-session simple average, otherwise risk-off. Skip only risk-on bullish signals. This classification uses no current-session SPY data.
- Trade QQQ only. No relative-strength instrument choice remains.

## Frozen focal rule and one-factor neighbors

All rules use a 0.15% stop, six-bar maximum hold, $10,000 maximum notional, one bp adverse slippage per side, $0.005/share/side, next-bar-open entry, cent-rounded after-cost target of at least 3R, stop-first same-bar precedence, and max one position.

| Role | Variant | Gap breadth | Mean gap | Sector first-bar confirmations |
|---|---|---:|---:|---:|
| Focal | `qqq_regime_b5_m10_c4_s15` | 5/7 | 0.10% | 4/5 |
| Neighbor | `qqq_regime_b4_m10_c4_s15` | 4/7 | 0.10% | 4/5 |
| Neighbor | `qqq_regime_b5_m15_c4_s15` | 5/7 | 0.15% | 4/5 |
| Neighbor | `qqq_regime_b5_m10_c3_s15` | 5/7 | 0.10% | 3/5 |

## Evidence protocol

- Evaluate 2024-01-02 through 2024-12-31 exactly once after the family hash is recorded.
- A prior cache contains 2024-11-15 through 2024-12-31 as warm-up inputs for the later 2025 study, but no 2024 trade outcome or candidate metric was evaluated. Accordingly, label this fresh outcome validation, not untouched data.
- Use earlier bars only as lagged warm-up. Keep focal and neighbor results separate; never select a neighbor from 2024.
- Report base costs, 1.5x costs, +2 bp per-side slippage stress, one-bar entry delay, monthly and regime stability, and concentration.
- Apply the current admission floors without exception. Finalize the research after this attempt and do not promote a failed rule.
