# Attempt 019 — remaining-history exhaustion audit

**REJECT**. Fresh pre-2021: n=8, net=$-235.60, expectancy=-0.194R, PF=0.77, max DD=2.13R.

Audit hash: `246c9af097f90ccf48077c19f6555befcd6cf58f6ba3eda12523425bff72a6de`. Rule hash: `472fcf2bdfb48791faa8e50e15190fc5060c0df886b9e76cadf0a80098d5dbdc`. The rule and audit were frozen before the pre-2021 data request.

## Alpaca availability boundary

Requested from 2000-01-01. Earliest common returned session: **2020-07-27**; first eligible evaluation session after warm-up: **2020-10-06**.

| Symbol | Bars | Earliest | Latest |
|---|---:|---|---|
| SPY | 112 | 2018-11-01 | 2020-12-31 |
| QQQ | 111 | 2020-07-27 | 2020-12-31 |
| IWM | 111 | 2020-07-27 | 2020-12-31 |
| XLK | 111 | 2020-07-27 | 2020-12-31 |
| XLF | 111 | 2020-07-27 | 2020-12-31 |
| XLE | 111 | 2020-07-27 | 2020-12-31 |
| XLV | 111 | 2020-07-27 | 2020-12-31 |
| XLY | 111 | 2020-07-27 | 2020-12-31 |

## Fresh year stability

| Year | n | P&L | Exp/R | PF | DD/R |
|---:|---:|---:|---:|---:|---:|
| 2020 | 8 | $-235.60 | -0.194 | 0.77 | 2.13 |

## Execution stress

| Scenario | n | P&L | Exp/R | PF | DD/R |
|---|---:|---:|---:|---:|---:|
| base | 8 | $-235.60 | -0.194 | 0.77 | 2.13 |
| 1.5x costs | 8 | $-250.95 | -0.198 | 0.75 | 2.13 |
| +2 bp/side | 8 | $-267.41 | -0.201 | 0.74 | 2.14 |
| one-session delay | 8 | $-148.42 | -0.196 | 0.90 | 2.21 |

## Admission audit

| Criterion | Pass |
|---|---|
| after_cost_target_stop_at_least_3 | True |
| profit_factor_at_least_2 | False |
| expectancy_at_least_0_25r | False |
| sample_adequate | False |
| max_drawdown_at_most_6r | True |
| cross_symbol_or_three_regime_support | False |
| positive_month_fraction_at_least_60pct | False |
| profitable_at_1_5x_costs | False |
| positive_neighbor_fraction_at_least_60pct | True |
| largest_win_at_most_25pct_gross_profit | False |
| pre_2021_positive_year_fraction_at_least_60pct | False |
| prior_fresh_2021_2022_admission_passed | False |
| all_fresh_blocks_profitable | False |

## Diagnostic aggregate

Pre-2021 and the separately frozen 2021–2022 block together: n=48, net=$-294.07, expectancy=-0.080R, PF=0.95, max DD=6.93R. This pooling is diagnostic only.

## Stopping condition

No usable unrevealed chronological Alpaca IEX daily partition remains for this fixed research universe. Further iteration would tune against revealed outcomes, so discovery stops without a promoted candidate.

## Limitations

- This is backward validation, not a live forward test.
- Alpaca IEX daily OHLC is not SIP and does not reveal intraday path; same-bar stop-first handling is conservative.
- Raw adjustment was frozen in the rule; corporate-action discontinuities can affect very long histories.
- The absence of an unrevealed chronological partition prevents further honest candidate iteration on this data set.
