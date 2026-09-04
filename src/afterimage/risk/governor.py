from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.models import (
    AccountSnapshot,
    EvidenceDecision,
    PayoffPassport,
    RiskDecision,
    RiskGate,
)

from .sizing import size_defined_risk_position


class RiskContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account: AccountSnapshot
    evidence: EvidenceDecision
    payoff: PayoffPassport
    strategy_manifest_hash: str
    expected_account_id_hash: str
    quote_hash: str
    maximum_quote_age_seconds: Decimal = Decimal(2)
    observed_quote_age_seconds: Decimal = Decimal(0)
    maximum_leg_skew_seconds: Decimal = Decimal(1)
    observed_leg_skew_seconds: Decimal = Decimal(0)
    relative_spread: Decimal = Decimal(0)
    maximum_relative_spread: Decimal = Decimal("0.05")
    open_strategy_positions: int = 0
    unknown_orders: int = 0
    realized_daily_pnl: Decimal = Decimal(0)
    worst_open_loss: Decimal = Decimal(0)
    high_water_equity: Decimal = Decimal(100000)
    entry_cutoff_passed: bool = False
    market_open: bool = True
    minimum_ratio: Decimal = Decimal(3)
    maximum_position_loss: Decimal = Decimal(500)
    maximum_daily_loss: Decimal = Decimal(1000)
    maximum_drawdown_fraction: Decimal = Decimal("0.02")


class RiskGovernor:
    policy_version = "hackathon-v1"

    @staticmethod
    def _gate(name: str, passed: bool, observed: object, required: object, code: str) -> RiskGate:
        return RiskGate(
            name=name,
            passed=passed,
            observed=str(observed),
            required=str(required),
            reason_code=None if passed else code,
        )

    def evaluate(self, context: RiskContext) -> RiskDecision:
        account = context.account
        quantity = size_defined_risk_position(
            context.payoff.stressed_max_loss, account.equity, context.maximum_position_loss
        )
        daily_loss = -(context.realized_daily_pnl - abs(context.worst_open_loss))
        drawdown = (
            (context.high_water_equity - account.equity) / context.high_water_equity
            if context.high_water_equity > 0
            else Decimal(1)
        )
        gates = (
            self._gate("paper", account.paper, account.paper, True, "NOT_PAPER"),
            self._gate(
                "account",
                account.account_id_hash == context.expected_account_id_hash,
                account.account_id_hash,
                context.expected_account_id_hash,
                "ACCOUNT_ID_MISMATCH",
            ),
            self._gate(
                "active",
                account.status.upper() == "ACTIVE",
                account.status,
                "ACTIVE",
                "ACCOUNT_INACTIVE",
            ),
            self._gate(
                "trading_unblocked",
                not account.trading_blocked,
                account.trading_blocked,
                False,
                "TRADING_BLOCKED",
            ),
            self._gate(
                "options_level",
                min(account.options_approved_level, account.options_trading_level) >= 3,
                min(account.options_approved_level, account.options_trading_level),
                3,
                "OPTIONS_LEVEL",
            ),
            self._gate(
                "market_open", context.market_open, context.market_open, True, "MARKET_CLOSED"
            ),
            self._gate(
                "entry_cutoff",
                not context.entry_cutoff_passed,
                context.entry_cutoff_passed,
                False,
                "ENTRY_CUTOFF",
            ),
            self._gate(
                "evidence",
                context.evidence.status == DecisionStatus.PASS,
                context.evidence.status,
                DecisionStatus.PASS,
                "EVIDENCE_REJECTED",
            ),
            self._gate(
                "quote_age",
                context.observed_quote_age_seconds <= context.maximum_quote_age_seconds,
                context.observed_quote_age_seconds,
                context.maximum_quote_age_seconds,
                "STALE_QUOTE",
            ),
            self._gate(
                "leg_skew",
                context.observed_leg_skew_seconds <= context.maximum_leg_skew_seconds,
                context.observed_leg_skew_seconds,
                context.maximum_leg_skew_seconds,
                "LEG_TIMESTAMP_SKEW",
            ),
            self._gate(
                "relative_spread",
                context.relative_spread <= context.maximum_relative_spread,
                context.relative_spread,
                context.maximum_relative_spread,
                "WIDE_SPREAD",
            ),
            self._gate(
                "structural_3r",
                context.payoff.structural_ratio >= context.minimum_ratio,
                context.payoff.structural_ratio,
                context.minimum_ratio,
                "STRUCTURAL_RATIO",
            ),
            self._gate(
                "operational_3r",
                context.payoff.operational_ratio >= context.minimum_ratio,
                context.payoff.operational_ratio,
                context.minimum_ratio,
                "OPERATIONAL_RATIO",
            ),
            self._gate("quantity", quantity >= 1, quantity, ">=1", "LOSS_CAP_TOO_SMALL"),
            self._gate(
                "position_loss",
                context.payoff.stressed_max_loss * quantity <= context.maximum_position_loss,
                context.payoff.stressed_max_loss * quantity,
                context.maximum_position_loss,
                "POSITION_LOSS",
            ),
            self._gate(
                "position_collision",
                context.open_strategy_positions == 0,
                context.open_strategy_positions,
                0,
                "POSITION_COLLISION",
            ),
            self._gate(
                "unknown_orders",
                context.unknown_orders == 0,
                context.unknown_orders,
                0,
                "UNKNOWN_ORDERS",
            ),
            self._gate(
                "daily_loss",
                daily_loss < context.maximum_daily_loss,
                daily_loss,
                context.maximum_daily_loss,
                "DAILY_LOSS_HALT",
            ),
            self._gate(
                "drawdown",
                drawdown < context.maximum_drawdown_fraction,
                drawdown,
                context.maximum_drawdown_fraction,
                "DRAWDOWN_HALT",
            ),
        )
        status = (
            DecisionStatus.PASS if all(gate.passed for gate in gates) else DecisionStatus.REJECT
        )
        return RiskDecision(
            status=status,
            gates=gates,
            quantity=quantity if status == DecisionStatus.PASS else 0,
            modeled_max_loss=context.payoff.stressed_max_loss * quantity,
            strategy_manifest_hash=context.strategy_manifest_hash,
            evidence_commit_hash=context.evidence.commit_hash,
            quote_hash=context.quote_hash,
            decided_at=datetime.now(UTC),
        )
