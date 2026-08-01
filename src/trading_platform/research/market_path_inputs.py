from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from equity_research import (
    MarketConstraintPolicy,
    MarketPathBudget,
    MarketPathCalibration,
    MarketPathEngine,
    MarketPathObservation,
    MarketPathRequest,
)

from trading_platform.application.workflow_ledger import SnapshotEvidence
from trading_platform.domain.research_evaluation import ResearchWorkflowRequest
from trading_platform.identity import canonical_hash


@dataclass(frozen=True)
class MarketPathCompilation:
    request: MarketPathRequest | None
    missing_gates: tuple[str, ...]
    source_member_ids: tuple[str, ...]


@dataclass(frozen=True)
class _DailyInput:
    member_id: str
    session_date: str
    close: Decimal
    adjustment_factor: Decimal
    available_at: str
    retrieved_at: str
    suspended: bool
    limit_state: str
    corporate_action_identity: str | None


class FrozenMarketPathCompiler:
    """Compiles only complete, PIT-safe frozen evidence into the engine input."""

    MODEL_IDENTITY = "FrozenMarketPathCompiler@1"
    STATE_MODEL_IDENTITY = "one_session_return_sign@1"

    def compile(
        self,
        *,
        request: ResearchWorkflowRequest,
        evidence: SnapshotEvidence,
        valuation_simulation_decision_id: str,
    ) -> MarketPathCompilation:
        daily, daily_gates = self._daily(evidence)
        calendar, calendar_gates = self._calendar(evidence)
        policy, policy_gates = self._policy(evidence)
        missing = tuple(
            dict.fromkeys(
                (
                    *daily_gates,
                    *calendar_gates,
                    *policy_gates,
                )
            )
        )
        source_ids = tuple(
            dict.fromkeys(
                item.normalized_version_id
                for item in evidence.member_evidence
                if item.dataset
                in {"daily", "trade_cal", "market_path_policy"}
            )
        )
        if missing or policy is None:
            return MarketPathCompilation(None, missing, source_ids)

        sequenced_inputs = tuple(sorted(daily, key=lambda item: item.session_date))
        if (
            len(sequenced_inputs) < 61
            or sequenced_inputs[-1].session_date
            != request.effective_session_date
        ):
            return MarketPathCompilation(
                None,
                ("MARKET_PATH_HISTORY_INSUFFICIENT",),
                source_ids,
            )
        calibration_rows = sequenced_inputs[:-1]
        starting = sequenced_inputs[-1]
        calendar_by_session = {
            session: member_id for session, member_id in calendar
        }
        required_calendar = tuple(
            item.session_date for item in sequenced_inputs
        )
        if any(
            session not in calendar_by_session
            for session in required_calendar
        ):
            return MarketPathCompilation(
                None,
                ("MARKET_PATH_TRADING_CALENDAR_INCOMPLETE",),
                source_ids,
            )

        observations = tuple(
            self._observation(calibration_rows, index)
            for index in range(len(calibration_rows))
        )
        series_member_ids = tuple(
            item.member_id for item in calibration_rows
        )
        calendar_member_ids = tuple(
            calendar_by_session[item.session_date] for item in sequenced_inputs
        )
        current_state = _state(
            starting.close * starting.adjustment_factor,
            calibration_rows[-1].close
            * calibration_rows[-1].adjustment_factor,
        )
        identity_payload = {
            "snapshot": evidence.data_snapshot_id,
            "members": source_ids,
            "as_of": request.evaluation_plan.horizon.as_of,
            "parent": valuation_simulation_decision_id,
            "policy": policy.policy_identity,
        }
        identity = canonical_hash(identity_payload)
        compiled = MarketPathRequest(
            simulation_id=f"market_path_{identity[:24]}",
            security_id=request.security_id,
            as_of=request.evaluation_plan.horizon.as_of,
            as_of_at=evidence.as_of_at,
            valuation_simulation_source_identity=(
                valuation_simulation_decision_id
            ),
            model_identity=self.MODEL_IDENTITY,
            policy_identity=policy.policy_identity,
            price_unit="CNY/share",
            currency="CNY",
            starting_price=starting.close,
            starting_price_session=starting.session_date,
            starting_price_member_id=starting.member_id,
            starting_price_available_at=starting.available_at,
            starting_price_evidence_refs=(starting.member_id,),
            current_market_state=current_state,
            current_state_available_at=max(
                starting.available_at,
                calibration_rows[-1].available_at,
            ),
            current_state_evidence_refs=(
                starting.member_id,
                calibration_rows[-1].member_id,
                self.STATE_MODEL_IDENTITY,
            ),
            calibration=MarketPathCalibration(
                snapshot_id=f"market_path_calibration_{identity[:24]}",
                platform_snapshot_id=evidence.data_snapshot_id,
                market="A-share",
                market_timezone="Asia/Shanghai",
                series_identity=f"daily_series_{identity[:24]}",
                series_evidence_refs=series_member_ids,
                adjustment_mode="backward_adjusted_return",
                trading_calendar_identity=(
                    f"trading_calendar_{identity[:24]}"
                ),
                calendar_evidence_refs=calendar_member_ids,
                calendar_member_ids=calendar_member_ids,
                trading_sessions=tuple(
                    item.session_date for item in calibration_rows
                ),
                next_session_date=starting.session_date,
                next_session_calendar_member_id=(
                    calendar_by_session[starting.session_date]
                ),
                series_member_ids=series_member_ids,
                adjustment_member_ids=series_member_ids,
                corporate_action_member_ids=tuple(
                    item.member_id
                    for item in calibration_rows
                    if item.corporate_action_identity is not None
                ),
                state_model_identity=self.STATE_MODEL_IDENTITY,
                observations=observations,
                window_start=calibration_rows[0].session_date,
                window_end=calibration_rows[-1].session_date,
                as_of=request.evaluation_plan.horizon.as_of,
                basis=(
                    "Frozen adjusted close-to-close returns with explicit "
                    "calendar, factor, state, suspension, and limit lineage."
                ),
            ),
            constraints=policy,
            budget=MarketPathBudget(
                rng_algorithm=MarketPathEngine.RNG_ALGORITHM,
                seed=int(identity[:16], 16),
                path_count=1000,
                horizon_sessions=20,
                block_length=5,
                minimum_candidate_blocks=10,
            ),
            price_thresholds=(),
            tail_return_threshold=Decimal("-0.20"),
        )
        return MarketPathCompilation(compiled, (), source_ids)

    @staticmethod
    def _daily(
        evidence: SnapshotEvidence,
    ) -> tuple[tuple[_DailyInput, ...], tuple[str, ...]]:
        result: list[_DailyInput] = []
        incomplete = False
        for member in evidence.member_evidence:
            if member.dataset != "daily":
                continue
            fields = tuple(
                field
                for field in member.extracted_fields
                if str(field.get("field_name", "")) == "current_price"
            )
            for field in fields:
                required = {
                    "period",
                    "value",
                    "adjustment_factor",
                    "suspended",
                    "limit_state",
                }
                if not required.issubset(field):
                    incomplete = True
                    continue
                try:
                    close = _decimal(field["value"])
                    factor = _decimal(field["adjustment_factor"])
                    datetime.fromisoformat(
                        str(field["period"]) + "T00:00:00"
                    )
                except (InvalidOperation, ValueError):
                    incomplete = True
                    continue
                suspended = field["suspended"]
                limit_state = str(field["limit_state"])
                if (
                    close <= 0
                    or factor <= 0
                    or type(suspended) is not bool
                    or limit_state not in {"none", "up", "down"}
                ):
                    incomplete = True
                    continue
                action = field.get("corporate_action_identity")
                result.append(
                    _DailyInput(
                        member.normalized_version_id,
                        str(field["period"]),
                        close,
                        factor,
                        member.available_at,
                        member.retrieved_at,
                        suspended,
                        limit_state,
                        None if action is None else str(action),
                    )
                )
        gates: list[str] = []
        if len(result) < 61:
            gates.append("MARKET_PATH_HISTORY_INSUFFICIENT")
        if incomplete:
            gates.append(
                "MARKET_PATH_ADJUSTMENT_STATE_EVIDENCE_INCOMPLETE"
            )
        return tuple(result), tuple(gates)

    @staticmethod
    def _calendar(
        evidence: SnapshotEvidence,
    ) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
        rows: list[tuple[str, str]] = []
        for member in evidence.member_evidence:
            if member.dataset != "trade_cal":
                continue
            for field in member.extracted_fields:
                if (
                    str(field.get("field_name", ""))
                    == "trading_session"
                    and field.get("value") in {1, "1", True}
                ):
                    rows.append(
                        (
                            str(field.get("period", "")),
                            member.normalized_version_id,
                        )
                    )
        return (
            tuple(rows),
            ()
            if rows
            else ("MARKET_PATH_TRADING_CALENDAR_UNAVAILABLE",),
        )

    @staticmethod
    def _policy(
        evidence: SnapshotEvidence,
    ) -> tuple[
        MarketConstraintPolicy | None,
        tuple[str, ...],
    ]:
        values: dict[str, tuple[Any, str]] = {}
        for member in evidence.member_evidence:
            if member.dataset != "market_path_policy":
                continue
            for field in member.extracted_fields:
                values[str(field.get("field_name", ""))] = (
                    field.get("value"),
                    member.normalized_version_id,
                )
        required = {
            "one_way_transaction_cost_bps",
            "price_limit_fraction",
            "price_tick_size",
            "market_path_policy_identity",
        }
        if not required.issubset(values):
            return (
                None,
                ("MARKET_PATH_CONSTRAINT_POLICY_UNAVAILABLE",),
            )
        try:
            result = MarketConstraintPolicy(
                policy_identity=str(
                    values["market_path_policy_identity"][0]
                ),
                one_way_transaction_cost_bps=_decimal(
                    values["one_way_transaction_cost_bps"][0]
                ),
                minimum_execution_lag_sessions=1,
                price_limit_fraction=_decimal(
                    values["price_limit_fraction"][0]
                ),
                price_tick_size=_decimal(
                    values["price_tick_size"][0]
                ),
                preserve_observed_suspensions=True,
                preserve_observed_limit_states=True,
            )
        except (InvalidOperation, ValueError):
            return None, ("MARKET_PATH_CONSTRAINT_POLICY_INVALID",)
        return result, ()

    @classmethod
    def _observation(
        cls,
        rows: tuple[_DailyInput, ...],
        index: int,
    ) -> MarketPathObservation:
        item = rows[index]
        refs = [item.member_id]
        if index:
            refs.append(rows[index - 1].member_id)
        return MarketPathObservation(
            session_date=item.session_date,
            unadjusted_close=item.close,
            adjustment_factor=item.adjustment_factor,
            market_state=(
                "warmup"
                if index == 0
                else _state(
                    item.close * item.adjustment_factor,
                    rows[index - 1].close
                    * rows[index - 1].adjustment_factor,
                )
            ),
            close_available_at=item.available_at,
            factor_available_at=item.available_at,
            state_available_at=item.available_at,
            retrieved_at=item.retrieved_at,
            suspended=item.suspended,
            limit_state=item.limit_state,  # type: ignore[arg-type]
            corporate_action_identity=item.corporate_action_identity,
            evidence_refs=tuple(refs),
        )


def _decimal(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise InvalidOperation
    return result


def _state(current: Decimal, previous: Decimal) -> str:
    if current > previous:
        return "risk_on"
    if current < previous:
        return "risk_off"
    return "flat"


__all__ = [
    "FrozenMarketPathCompiler",
    "MarketPathCompilation",
]
