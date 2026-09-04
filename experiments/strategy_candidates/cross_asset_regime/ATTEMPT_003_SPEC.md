# Attempt 003 — sector-to-index lead–lag catch-up

Attempt 003 is materially distinct from the 10:30 leadership momentum of attempt 001 and the overnight gap continuation of attempt 002. At stock-bar starts 11:30, 13:00, and 14:00 New York time, it measures the move from the open eight bar intervals earlier through the current bar close. The signal is known 15 minutes after the named bar start.

Require three or four of XLK, XLF, XLE, XLV, and XLY to share a direction and their mean move to exceed 0.10%. QQQ and IWM are eligible only if they moved in the same direction but lag the sector mean by at least 0.05% or 0.10%. Trade the more directionally lagging eligible index, predicting cross-asset catch-up. At most one position may be open, so chronologically overlapping checkpoint signals are discarded.

The predeclared 2 × 2 × 3 neighborhood is sector breadth {3,4}, lag gap {0.05%,0.10%}, and nominal stop fraction {15%,20%,25%}. All use the earliest listed 3–9 DTE exact $5 debit vertical, next synchronized option-bar open with $0.03 adverse slippage per leg, a net-of-$2.60-fee target at least 3× the nominal after-cost stop, stop-first evaluation, and a six-bar timeout. January–April selects the winner with at least 12 closed trades. May–September is one rolling/pseudo-OOS pass, never untouched. The admission floors in `ATTEMPT_002_SPEC.md` apply unchanged.
