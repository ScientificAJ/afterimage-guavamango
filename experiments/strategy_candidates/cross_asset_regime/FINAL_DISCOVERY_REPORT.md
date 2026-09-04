# AFTERIMAGE strategy discovery — final evidence report

**NO CANDIDATE PROMOTED.** Nineteen recorded attempts were preserved. The last exact frozen rule failed fresh validation, and the full remaining Alpaca history was then consumed in one sealed audit.

Attempts 001–007 remain sealed by snapshot hash `d9aa8d0820fe58c9cacf814da1c64cde5333cb3248f69c46778c5aad02218bb7`.

| Attempt ID | Status | Selected | n | Net P&L | Exp/R | PF | DD/R |
|---|---|---|---:|---:|---:|---:|---:|
| cross_asset_breadth_rotation_v1 | evaluated | `b6_spy10_h07_3r` |  |  |  |  |  |
| overnight_breadth_confirmation_v2 | evaluated | `gap_b4_m10_s25` | 21 | -475.60 | -0.4824524396154202189388149424 | 0.4436125409452503509592887225 |  |
| sector_index_leadlag_v3 | evaluated | `None` | 0 | 0.00 | 0 | 0 |  |
| equity_sector_index_leadlag_v4 | evaluated | `equity_b4_g10_s15` | 17 | -55.96 | -0.2013669640589802701165652606 | 0.5759321006365565322825098515 |  |
| equity_overnight_gap_v5 | evaluated | `equity_gap_b4_m10_s15` | 22 | 221.18 | 0.6064450229938247864360584277 | 2.015612085590963357516760033 |  |
| qqq_regime_gap_v6 | evaluated | `` |  |  |  |  |  |
| qqq_regime_active_rule_v7 | evaluated | `qqq_regime_b5_m10_c3_s15` |  |  |  |  |  |
| multiday_cross_sectional_rotation_v8 | rejected_in_development | `md_rs20_a75_h05` | 161 | 1100.57 | 0.1059519269914302781887224889 | 1.088471750728911018594365339 | 10.57332903903519123438384219 |
| multiday_channel_breakout_v9 | rejected_in_development | `bo_n20_a50_h05` | 150 | 2589.92 | 0.2497581270941037165809118359 | 1.348406763335714410629559528 | 21.61617340595033417368751191 |
| broad_trend_pullback_v10 | rejected_in_development | `pb_d00_a50_h05` | 152 | 147.57 | 0.07685721425771607220128060671 | 1.015858124750151521013063046 | 10.58235701035897612175203856 |
| credit_duration_impulse_v11 | rejected_in_development | `cd_t25_a100_h05` | 67 | -2527.94 | -0.1442661910848529264210715179 | 0.6081399692767003610220224984 | 13.57571361820062034907013491 |
| slow_weekly_rotation_v12 | rejected_in_development | `wk_rs60_a200_h10` | 52 | -1095.69 | -0.003401495520710272200006196958 | 0.8433873914050238844626639109 | 8.428486309287962976856858218 |
| longonly_consensus_rotation_v13 | rejected_in_development | `lo_b6_a75_h05` | 88 | 2962.40 | 0.2984137254581546355927268903 | 1.564564541672463375914530143 | 8.832237079401907176400334752 |
| lowvol_consensus_rotation_v14 | rejected_in_development | `lv_v12_a125_h05` | 72 | 4200.75 | 0.2981228488831869167340417296 | 1.983761466385954394403865024 | 3.098748962129038766527882479 |
| unanimous_breadth_rotation_v15 | rejected_in_development | `ub_b6_a125_h05` | 72 | 4293.89 | 0.2969529760468094828776759149 | 1.986792634946315634652154729 | 3.098748962129038766527882479 |
| growth_cluster_rotation_v16 | rejected_in_development | `gc_b6_a100_h05` | 77 | 3200.00 | 0.2575608152171830826573263738 | 1.627064905136837319767829219 | 6.517523956175948890944127519 |
| frozen_lowvol_consensus_v17 | evaluated | `lv_v12_a125_h05` | 40 | -58.47 | -0.05698378366305816232369817468 | 0.9877835768817721021775194414 | 6.925892885198878411098542374 |
| consumer_growth_expression_v18 | rejected_in_development | `cg_b6_a100_h05` | 118 | 4248.42 | 0.2059114042585032636681928436 | 1.531148770714692037931875152 | 6.170036335457830610818715701 |
| remaining_history_exhaustion_v19 | evaluated_history_exhaustion | `lv_v12_a125_h05` | 8 | -235.60 | -0.193936191706222635212827802 | 0.7668780859463898756221366870 | 2.128018063218244229259341871 |

## Final validation verdict

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


## Production integration contract

There is none: admission failed, so no signal module, scheduler, risk allocation, or order route is authorized for production. The existing exact MLEG dry-run artifact remains a non-submitted audit artifact only (`submitted: false`); no order was placed during this research.
