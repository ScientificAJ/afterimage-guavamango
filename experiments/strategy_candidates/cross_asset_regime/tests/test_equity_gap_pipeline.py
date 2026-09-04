from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from experiments.strategy_candidates.cross_asset_regime.run_equity_gap_research import aggregate_rolling_oos


@dataclass(frozen=True)
class Row:
    session: date
    label: str


def test_rolling_oos_contains_only_fold_validation_and_final_pseudo_rows() -> None:
    development = {
        "a": (Row(date(2026, 2, 1), "train"), Row(date(2026, 3, 1), "march")),
        "b": (Row(date(2026, 4, 1), "april"),),
    }
    pseudo = {"b": (Row(date(2026, 5, 1), "may"),)}
    rows = aggregate_rolling_oos(
        development,
        ((3, "a"), (4, "b")),
        pseudo,
        "b",
    )
    assert tuple(row.label for row in rows) == ("march", "april", "may")
