from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Literal

from trading_platform.identity import canonical_hash
from trading_platform.domain.market_time import supported_market_timezone


ValueState = Literal["known", "unknown", "not_applicable"]
DraftStatus = Literal["open", "rejected", "discarded", "confirmed"]
TransitionReason = Literal[
    "initial_confirmation", "new_observation", "revision", "correction"
]


class AccountSnapshotError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AccountSnapshotPosition:
    security_id: str
    total_quantity: str
    available_quantity_state: ValueState = "unknown"
    available_quantity_value: str | None = None
    cost_state: ValueState = "unknown"
    cost_value: str | None = None
    market_value_state: ValueState = "unknown"
    market_value_value: str | None = None
    content_hash: str = ""


@dataclass(frozen=True)
class AccountSecurityIdentity:
    market: str
    code: str
    currency: str
    observed_on: str
    security_id: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class AccountRegistration:
    account_id: str
    alias: str
    base_currency: str
    source_kind: str
    redacted_source_ref: str
    registered_at: str
    securities: tuple[AccountSecurityIdentity, ...]
    registration_id: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class AccountSnapshotDraft:
    draft_id: str
    account_id: str
    revision: int
    status: DraftStatus
    source_kind: str
    redacted_source_ref: str
    as_of_at: str
    as_of_precision: Literal["date", "instant"]
    timezone: str
    session_semantics: Literal["complete_session", "intraday", "legacy_unknown"]
    currency: str
    cash_state: ValueState
    cash_value: str | None
    positions: tuple[AccountSnapshotPosition, ...]
    nav_state: ValueState = "unknown"
    nav_value: str | None = None
    fees_state: ValueState = "unknown"
    fees_value: str | None = None
    previous_snapshot_version_id: str | None = None
    revises_snapshot_version_id: str | None = None
    corrects_snapshot_version_id: str | None = None
    correction_reason: str | None = None
    validation_state: Literal["valid", "invalid"] = "valid"
    validation_errors: tuple[str, ...] = ()
    capability_impacts: tuple[str, ...] = ()
    canonical_diff: str = "{}"
    canonical_diff_hash: str = ""
    content_hash: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class AccountSnapshotVersion:
    account_snapshot_version_id: str
    account_id: str
    version_no: int
    source_draft_id: str
    as_of_at: str
    as_of_precision: str
    timezone: str
    session_semantics: str
    currency: str
    source_kind: str
    redacted_source_ref: str
    previous_snapshot_version_id: str | None
    revises_snapshot_version_id: str | None
    corrects_snapshot_version_id: str | None
    correction_reason: str | None
    confirmed_by: str
    confirmed_at: str
    content_hash: str
    graph_seal_hash: str
    cash_state: str
    cash_value: str | None
    nav_state: str
    nav_value: str | None
    fees_state: str
    fees_value: str | None
    positions: tuple[AccountSnapshotPosition, ...]
    capabilities: tuple[tuple[str, str, str | None, tuple[str, ...]], ...]


@dataclass(frozen=True)
class AccountSnapshotTransition:
    transition_id: str
    account_id: str
    from_snapshot_version_id: str | None
    to_snapshot_version_id: str
    reason: TransitionReason
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    command_invocation_id: str
    occurred_at: str
    content_hash: str


class AccountSnapshotService:
    """Owns snapshot validation, three-state values, and transition semantics."""

    _VALUE_STATES = {"known", "unknown", "not_applicable"}
    _SESSION_SEMANTICS = {"complete_session", "intraday", "legacy_unknown"}
    _A_SHARE_MARKETS = {"SSE", "SZSE", "BSE"}
    _SCREENSHOT_SOURCE = "user_declared_from_broker_screenshot"

    def prepare_registration(
        self, registration: AccountRegistration
    ) -> AccountRegistration:
        if not re.fullmatch(
            r"account_[a-z0-9][a-z0-9_-]{1,63}", registration.account_id
        ):
            raise AccountSnapshotError("ACCOUNT_ID_INVALID")
        alias = registration.alias.strip()
        if not alias:
            raise AccountSnapshotError("ACCOUNT_ALIAS_REQUIRED")
        currency = registration.base_currency.upper()
        if currency != "CNY":
            raise AccountSnapshotError("ACCOUNT_CURRENCY_UNSUPPORTED")
        if registration.source_kind != self._SCREENSHOT_SOURCE:
            raise AccountSnapshotError("ACCOUNT_REGISTRATION_SOURCE_UNSUPPORTED")
        if not registration.redacted_source_ref.strip():
            raise AccountSnapshotError("ACCOUNT_SOURCE_REFERENCE_REQUIRED")
        try:
            registered_at = datetime.fromisoformat(registration.registered_at)
        except ValueError as error:
            raise AccountSnapshotError("ACCOUNT_REGISTERED_AT_INVALID") from error
        if registered_at.tzinfo is None:
            raise AccountSnapshotError("ACCOUNT_REGISTERED_AT_OFFSET_REQUIRED")

        seen: set[tuple[str, str]] = set()
        identities: list[AccountSecurityIdentity] = []
        for identity in registration.securities:
            market = identity.market.upper()
            code = identity.code.strip()
            security_currency = identity.currency.upper()
            key = (market, code)
            if market not in self._A_SHARE_MARKETS:
                raise AccountSnapshotError("SECURITY_MARKET_UNSUPPORTED")
            if not re.fullmatch(r"\d{6}", code):
                raise AccountSnapshotError("SECURITY_CODE_INVALID")
            if security_currency != "CNY":
                raise AccountSnapshotError("SECURITY_CURRENCY_UNSUPPORTED")
            try:
                observed_on = date.fromisoformat(identity.observed_on)
            except ValueError as error:
                raise AccountSnapshotError("SECURITY_OBSERVED_ON_INVALID") from error
            if observed_on > registered_at.date():
                raise AccountSnapshotError("SECURITY_OBSERVED_AFTER_REGISTRATION")
            if key in seen:
                raise AccountSnapshotError("SECURITY_IDENTITY_DUPLICATE")
            seen.add(key)
            security_id = identity.security_id or (
                "security_" + canonical_hash({"market": market, "code": code})[:24]
            )
            if not re.fullmatch(r"security_[a-z0-9_]{3,64}", security_id):
                raise AccountSnapshotError("SECURITY_ID_INVALID")
            normalized = AccountSecurityIdentity(
                market=market,
                code=code,
                currency=security_currency,
                observed_on=observed_on.isoformat(),
                security_id=security_id,
            )
            identities.append(
                replace(normalized, content_hash=canonical_hash(normalized))
            )

        prepared = replace(
            registration,
            alias=alias,
            base_currency=currency,
            securities=tuple(
                sorted(identities, key=lambda item: (item.market, item.code))
            ),
            registration_id="",
            content_hash="",
        )
        content_hash = canonical_hash(prepared)
        return replace(
            prepared,
            registration_id=f"account_registration_{content_hash[:24]}",
            content_hash=content_hash,
        )

    def prepare(
        self,
        draft: AccountSnapshotDraft,
        prior: AccountSnapshotVersion | None = None,
    ) -> AccountSnapshotDraft:
        errors: list[str] = []
        if not draft.account_id:
            errors.append("ACCOUNT_ID_REQUIRED")
        if draft.revision < 1:
            errors.append("DRAFT_REVISION_INVALID")
        if draft.as_of_precision not in {"date", "instant"}:
            errors.append("AS_OF_PRECISION_INVALID")
        else:
            try:
                if draft.as_of_precision == "date":
                    datetime.fromisoformat(f"{draft.as_of_at}T00:00:00")
                else:
                    parsed = datetime.fromisoformat(draft.as_of_at)
                    if parsed.tzinfo is None:
                        errors.append("AS_OF_OFFSET_REQUIRED")
            except ValueError:
                errors.append("AS_OF_INVALID")
        try:
            supported_market_timezone(draft.timezone)
        except ValueError:
            errors.append("TIMEZONE_INVALID")
        if draft.session_semantics not in self._SESSION_SEMANTICS:
            errors.append("SESSION_SEMANTICS_INVALID")
        if len(draft.currency) != 3 or not draft.currency.isalpha():
            errors.append("CURRENCY_INVALID")
        self._check_value("cash", draft.cash_state, draft.cash_value, errors)
        self._check_value("nav", draft.nav_state, draft.nav_value, errors)
        self._check_value("fees", draft.fees_state, draft.fees_value, errors)
        seen: set[str] = set()
        prepared_positions: list[AccountSnapshotPosition] = []
        for position in draft.positions:
            prefix = f"position:{position.security_id or '<missing>'}"
            if not position.security_id:
                errors.append("POSITION_SECURITY_ID_REQUIRED")
            elif position.security_id in seen:
                errors.append("POSITION_SECURITY_ID_DUPLICATE")
            seen.add(position.security_id)
            total = self._decimal(position.total_quantity)
            if total is None:
                errors.append("POSITION_TOTAL_QUANTITY_INVALID")
            self._check_value(
                f"{prefix}:available_quantity",
                position.available_quantity_state,
                position.available_quantity_value,
                errors,
            )
            available = self._decimal(position.available_quantity_value)
            if (
                position.available_quantity_state == "known"
                and total is not None
                and available is not None
                and available > total
            ):
                errors.append("POSITION_AVAILABLE_EXCEEDS_TOTAL")
            self._check_value(
                f"{prefix}:cost",
                position.cost_state,
                position.cost_value,
                errors,
            )
            self._check_value(
                f"{prefix}:market_value",
                position.market_value_state,
                position.market_value_value,
                errors,
            )
            normalized = replace(
                position,
                total_quantity=(
                    self._render(total)
                    if total is not None
                    else position.total_quantity
                ),
                available_quantity_value=self._normalized_optional(
                    position.available_quantity_state,
                    position.available_quantity_value,
                ),
                cost_value=self._normalized_optional(
                    position.cost_state, position.cost_value
                ),
                market_value_value=self._normalized_optional(
                    position.market_value_state,
                    position.market_value_value,
                ),
                content_hash="",
            )
            prepared_positions.append(
                replace(normalized, content_hash=canonical_hash(normalized))
            )
        if (
            draft.nav_state == "known"
            and draft.cash_state == "known"
            and all(
                position.market_value_state == "known"
                for position in prepared_positions
            )
        ):
            nav = self._decimal(draft.nav_value)
            cash = self._decimal(draft.cash_value)
            market_values = tuple(
                self._decimal(position.market_value_value)
                for position in prepared_positions
            )
            if (
                nav is not None
                and cash is not None
                and all(value is not None for value in market_values)
                and nav
                != cash
                + sum(
                    (value for value in market_values if value is not None),
                    Decimal(0),
                )
            ):
                errors.append("NAV_RECONCILIATION_MISMATCH")
        if draft.corrects_snapshot_version_id and not (
            draft.correction_reason and draft.correction_reason.strip()
        ):
            errors.append("CORRECTION_REASON_REQUIRED")
        if draft.revises_snapshot_version_id and draft.corrects_snapshot_version_id:
            errors.append("SNAPSHOT_RELATION_AMBIGUOUS")
        impacts = self._capability_impacts(draft, tuple(prepared_positions))
        if "NAV_RECONCILIATION_MISMATCH" in errors:
            impacts = tuple(sorted((*impacts, "nav_reconciliation_conflict")))
        canonical_diff = self._canonical_diff(draft, tuple(prepared_positions), prior)
        canonical_diff_hash = canonical_hash(canonical_diff)
        prepared = replace(
            draft,
            currency=draft.currency.upper(),
            cash_value=self._normalized_optional(draft.cash_state, draft.cash_value),
            nav_value=self._normalized_optional(draft.nav_state, draft.nav_value),
            fees_value=self._normalized_optional(draft.fees_state, draft.fees_value),
            positions=tuple(prepared_positions),
            validation_state="invalid" if errors else "valid",
            validation_errors=tuple(sorted(set(errors))),
            capability_impacts=impacts,
            canonical_diff=canonical_diff,
            canonical_diff_hash=canonical_diff_hash,
            content_hash="",
        )
        return replace(prepared, content_hash=canonical_hash(prepared))

    def _canonical_diff(
        self,
        draft: AccountSnapshotDraft,
        positions: tuple[AccountSnapshotPosition, ...],
        prior: AccountSnapshotVersion | None,
    ) -> str:
        def position_values(
            values: tuple[AccountSnapshotPosition, ...],
        ) -> list[dict[str, object]]:
            return [
                {
                    "security_id": item.security_id,
                    "total_quantity": item.total_quantity,
                    "available_quantity_state": item.available_quantity_state,
                    "available_quantity_value": item.available_quantity_value,
                    "cost_state": item.cost_state,
                    "cost_value": item.cost_value,
                    "market_value_state": item.market_value_state,
                    "market_value_value": item.market_value_value,
                }
                for item in sorted(values, key=lambda value: value.security_id)
            ]

        before = (
            None
            if prior is None
            else {
                "account_snapshot_version_id": prior.account_snapshot_version_id,
                "as_of_at": prior.as_of_at,
                "as_of_precision": prior.as_of_precision,
                "timezone": prior.timezone,
                "session_semantics": prior.session_semantics,
                "currency": prior.currency,
                "cash_state": prior.cash_state,
                "cash_value": prior.cash_value,
                "nav_state": prior.nav_state,
                "nav_value": prior.nav_value,
                "fees_state": prior.fees_state,
                "fees_value": prior.fees_value,
                "positions": position_values(prior.positions),
            }
        )
        after = {
            "as_of_at": draft.as_of_at,
            "as_of_precision": draft.as_of_precision,
            "timezone": draft.timezone,
            "session_semantics": draft.session_semantics,
            "currency": draft.currency.upper(),
            "cash_state": draft.cash_state,
            "cash_value": self._normalized_optional(draft.cash_state, draft.cash_value),
            "nav_state": draft.nav_state,
            "nav_value": self._normalized_optional(draft.nav_state, draft.nav_value),
            "fees_state": draft.fees_state,
            "fees_value": self._normalized_optional(draft.fees_state, draft.fees_value),
            "positions": position_values(positions),
        }
        return json.dumps(
            {
                "from_snapshot_version_id": (
                    prior.account_snapshot_version_id if prior else None
                ),
                "before": before,
                "after": after,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def transition_reason(
        self, draft: AccountSnapshotDraft, prior: AccountSnapshotVersion | None
    ) -> TransitionReason:
        if prior is None:
            if (
                draft.previous_snapshot_version_id
                or draft.revises_snapshot_version_id
                or draft.corrects_snapshot_version_id
            ):
                raise AccountSnapshotError("SNAPSHOT_PREDECESSOR_INVALID")
            return "initial_confirmation"
        if draft.previous_snapshot_version_id != prior.account_snapshot_version_id:
            raise AccountSnapshotError("SNAPSHOT_PREDECESSOR_STALE")
        if draft.revises_snapshot_version_id:
            if draft.revises_snapshot_version_id != prior.account_snapshot_version_id:
                raise AccountSnapshotError("SNAPSHOT_REVISION_TARGET_INVALID")
            if draft.as_of_at != prior.as_of_at:
                raise AccountSnapshotError("SNAPSHOT_REVISION_AS_OF_MISMATCH")
            return "revision"
        if draft.corrects_snapshot_version_id:
            return "correction"
        return "new_observation"

    @staticmethod
    def _decimal(value: str | None) -> Decimal | None:
        if value is None:
            return None
        try:
            result = Decimal(value)
        except InvalidOperation:
            return None
        if not result.is_finite() or result < 0:
            return None
        return result

    @staticmethod
    def _render(value: Decimal) -> str:
        rendered = format(value.normalize(), "f")
        return "0" if rendered == "-0" else rendered

    def _check_value(
        self, field: str, state: str, value: str | None, errors: list[str]
    ) -> None:
        if state not in self._VALUE_STATES:
            errors.append(f"{field.upper()}:STATE_INVALID")
        elif state == "known":
            if self._decimal(value) is None:
                errors.append(f"{field.upper()}:KNOWN_VALUE_INVALID")
        elif value is not None:
            errors.append(f"{field.upper()}:VALUE_MUST_BE_EMPTY")

    def _normalized_optional(self, state: str, value: str | None) -> str | None:
        if state != "known":
            return None
        parsed = self._decimal(value)
        return self._render(parsed) if parsed is not None else value

    @staticmethod
    def _capability_impacts(
        draft: AccountSnapshotDraft,
        positions: tuple[AccountSnapshotPosition, ...],
    ) -> tuple[str, ...]:
        impacts: list[str] = []
        for field, state in (
            ("cash", draft.cash_state),
            ("nav", draft.nav_state),
            ("fees", draft.fees_state),
        ):
            if state != "known":
                impacts.append(f"{field}_dependent_rules_unable")
        for position in positions:
            for field, state in (
                ("available_quantity", position.available_quantity_state),
                ("cost", position.cost_state),
                ("market_value", position.market_value_state),
            ):
                if state != "known":
                    impacts.append(
                        f"{field}_dependent_rules_unable:{position.security_id}"
                    )
        return tuple(sorted(impacts))


__all__ = [
    "AccountRegistration",
    "AccountSecurityIdentity",
    "AccountSnapshotDraft",
    "AccountSnapshotError",
    "AccountSnapshotPosition",
    "AccountSnapshotService",
    "AccountSnapshotTransition",
    "AccountSnapshotVersion",
]
