from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from afterimage.config import RiskPolicy, load_runtime_config
from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.models import (
    AccountSnapshot,
    EvidenceDecision,
    PayoffPassport,
    RiskDecision,
    RiskGate,
)
from afterimage.strategies.deployment import DeploymentDecision

from .sizing import size_defined_risk_position, size_equity_position


class RiskContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account: AccountSnapshot
    evidence: EvidenceDecision | DeploymentDecision
    payoff: PayoffPassport
    strategy_manifest_hash: str
    expected_account_id_hash: str
    quote_hash: str
    observed_quote_age_seconds: Decimal = Decimal(0)
    observed_leg_skew_seconds: Decimal = Decimal(0)
    relative_spread: Decimal = Decimal(0)
    open_strategy_positions: int = 0
    unknown_orders: int = 0
    realized_daily_pnl: Decimal
    worst_open_loss: Decimal
    high_water_equity: Decimal
    entry_cutoff_passed: bool
    market_open: bool = True


class RiskGovernor:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or load_runtime_config().risk

    @property
    def policy_version(self) -> str:
        return self.policy.policy_version

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
        if context.payoff.asset_class == "equity":
            if context.payoff.entry_price is None:
                quantity = 0
            else:
                quantity = size_equity_position(
                    context.payoff.stressed_max_loss,
                    context.payoff.entry_price,
                    account.equity,
                    self.policy.maximum_modeled_loss,
                    self.policy.maximum_equity_notional,
                )
        else:
            quantity = size_defined_risk_position(
                context.payoff.stressed_max_loss,
                account.equity,
                self.policy.maximum_modeled_loss,
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
                context.payoff.asset_class == "equity"
                or min(account.options_approved_level, account.options_trading_level) >= 3,
                min(account.options_approved_level, account.options_trading_level),
                "not-required-for-equity" if context.payoff.asset_class == "equity" else 3,
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
                context.observed_quote_age_seconds <= self.policy.maximum_quote_age_seconds,
                context.observed_quote_age_seconds,
                self.policy.maximum_quote_age_seconds,
                "STALE_QUOTE",
            ),
            self._gate(
                "leg_skew",
                context.observed_leg_skew_seconds <= self.policy.maximum_leg_timestamp_skew_seconds,
                context.observed_leg_skew_seconds,
                self.policy.maximum_leg_timestamp_skew_seconds,
                "LEG_TIMESTAMP_SKEW",
            ),
            self._gate(
                "relative_spread",
                context.relative_spread <= self.policy.maximum_relative_spread,
                context.relative_spread,
                self.policy.maximum_relative_spread,
                "WIDE_SPREAD",
            ),
            self._gate(
                "structural_3r",
                context.payoff.structural_ratio >= self.policy.minimum_structural_reward_risk,
                context.payoff.structural_ratio,
                self.policy.minimum_structural_reward_risk,
                "STRUCTURAL_RATIO",
            ),
            self._gate(
                "operational_3r",
                context.payoff.operational_ratio >= self.policy.minimum_operational_reward_risk,
                context.payoff.operational_ratio,
                self.policy.minimum_operational_reward_risk,
                "OPERATIONAL_RATIO",
            ),
            self._gate("quantity", quantity >= 1, quantity, ">=1", "LOSS_CAP_TOO_SMALL"),
            self._gate(
                "position_loss",
                context.payoff.stressed_max_loss * quantity <= self.policy.maximum_modeled_loss,
                context.payoff.stressed_max_loss * quantity,
                self.policy.maximum_modeled_loss,
                "POSITION_LOSS",
            ),
            self._gate(
                "equity_notional",
                context.payoff.asset_class != "equity"
                or (
                    context.payoff.entry_price is not None
                    and context.payoff.entry_price * quantity <= self.policy.maximum_equity_notional
                ),
                (
                    context.payoff.entry_price * quantity
                    if context.payoff.entry_price is not None
                    else "missing"
                ),
                self.policy.maximum_equity_notional,
                "EQUITY_NOTIONAL",
            ),
            self._gate(
                "position_collision",
                context.open_strategy_positions <= self.policy.maximum_open_strategy_positions - 1,
                context.open_strategy_positions,
                f"<{self.policy.maximum_open_strategy_positions}",
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
                daily_loss < self.policy.maximum_daily_loss,
                daily_loss,
                self.policy.maximum_daily_loss,
                "DAILY_LOSS_HALT",
            ),
            self._gate(
                "drawdown",
                drawdown < self.policy.maximum_high_water_drawdown_fraction,
                drawdown,
                self.policy.maximum_high_water_drawdown_fraction,
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
