from __future__ import annotations

import sqlite3
from typing import Any, Callable

from trading_platform.result import ApplicationError, OperationResult
from trading_platform.storage import SQLiteStore, StorageError
from trading_platform.evidence import evidence_set_from_dict
from trading_platform.identifiers import digest
from trading_platform.research.core import InvestmentCase, validate_candidate
from trading_platform.valuation import ValuationAssessment, assess as assess_valuation
from trading_platform.planning import PlanClosed, StalePlan, TradePlan, TradePlanDraft, blocked_evaluation, confirm as confirm_plan, evaluate as evaluate_plan, is_active_plan, prepare as prepare_plan
from trading_platform.portfolio import AccountSnapshot, ExecutionRecord, RiskPolicy, StaleAccount, build_portfolio, confirm_account, evaluate_risk
from trading_platform.review import DecisionReview, DecisionTask, StaleReview, commit_review, create_task


STABLE_FAILURES = {"INVALID_INPUT", "NOT_FOUND", "STALE_INPUT", "IDEMPOTENCY_CONFLICT", "PERSISTENCE_FAILURE", "INTERNAL_FAILURE"}


class Application:
    """The task-level application Interface."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def account_confirm(self, candidate: dict[str, Any], *, idempotency_key: str) -> OperationResult:
        return self._mutate("account.confirm", candidate, idempotency_key, "AccountSnapshot", self._confirm_account)

    def account_show(self, account_id: str, as_of: str | None = None) -> OperationResult:
        try:
            snapshot = self.store.latest("AccountSnapshot", account_id=account_id, as_of=as_of)
        except StorageError as error:
            return OperationResult.failure(
                "PERSISTENCE_FAILURE", "The account could not be read.", step=f"account.show.{error.step}"
            )
        if snapshot is None:
            return OperationResult.failure("NOT_FOUND", "No confirmed account snapshot exists.", step="account.lookup")
        return OperationResult.success(snapshot)

    def research_commit(self, request: dict[str, Any], *, idempotency_key: str) -> OperationResult:
        return self._mutate("research.commit", request, idempotency_key, "InvestmentCase", self._commit_research)

    def _commit_research(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            evidence = evidence_set_from_dict(request["evidence_set"])
            investment_case_record = validate_candidate(
                str(request["security_id"]), str(request["as_of"]), evidence, request["candidate"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationError("INVALID_INPUT", str(error), step="research.validate") from error
        evidence_payload = evidence.as_dict()
        investment_case = investment_case_record.as_dict()
        self.store.put("EvidenceSet", evidence.evidence_set_id, evidence_payload, as_of=evidence.as_of)
        self.store.put(
            "InvestmentCase", investment_case["investment_case_id"], investment_case, as_of=investment_case["as_of"]
        )
        return investment_case

    def valuation_assess(self, request: dict[str, Any], *, idempotency_key: str) -> OperationResult:
        return self._mutate("valuation.assess", request, idempotency_key, "ValuationAssessment", self._assess_valuation)

    def _assess_valuation(self, request: dict[str, Any]) -> dict[str, Any]:
        investment_case_id = str(request.get("investment_case_id", ""))
        investment_case = self.store.get("InvestmentCase", investment_case_id)
        if investment_case is None:
            raise ApplicationError("NOT_FOUND", "The referenced InvestmentCase does not exist.", step="valuation.reference")
        try:
            evidence = evidence_set_from_dict(request["evidence_set"])
            if investment_case["as_of"] != evidence.as_of:
                raise ApplicationError("STALE_INPUT", "Valuation evidence does not match the InvestmentCase as_of.", step="valuation.reference")
            assessment_record = assess_valuation(
                investment_case_id,
                evidence,
                str(request["method"]),
                str(request["company_archetype"]),
                scenarios=request.get("scenarios"),
                peers=request.get("peers"),
                comparable_currency=request.get("comparable_currency"),
                accounting_basis=request.get("accounting_basis"),
            )
        except ApplicationError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationError("INVALID_INPUT", str(error), step="valuation.validate") from error
        assessment = assessment_record.as_dict()
        self.store.put("EvidenceSet", evidence.evidence_set_id, evidence.as_dict(), as_of=evidence.as_of)
        self.store.put("ValuationAssessment", assessment["valuation_assessment_id"], assessment, as_of=assessment["as_of"])
        return assessment

    def planning_prepare(self, request: dict[str, Any], *, idempotency_key: str) -> OperationResult:
        return self._mutate("planning.prepare", request, idempotency_key, "TradePlanDraft", self._prepare_plan, replay=self._replay_prepare)

    def _prepare_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        investment_case = self.store.get("InvestmentCase", str(request.get("investment_case_id", "")))
        if investment_case is None:
            raise ApplicationError("NOT_FOUND", "The referenced InvestmentCase does not exist.", step="planning.reference")
        valuation_id = request.get("valuation_assessment_id")
        valuation = self.store.get("ValuationAssessment", str(valuation_id)) if valuation_id else None
        if valuation_id and valuation is None:
            raise ApplicationError("NOT_FOUND", "The referenced ValuationAssessment does not exist.", step="planning.reference")
        account = self.store.get("AccountSnapshot", str(request.get("account_snapshot_id", "")))
        if account is None:
            raise ApplicationError("NOT_FOUND", "The referenced AccountSnapshot does not exist.", step="planning.reference")
        plan_request = request.get("plan", {})
        supersedes_id = plan_request.get("supersedes_plan_id")
        close_id = plan_request.get("close_plan_id")
        superseded_payload = self.store.get("TradePlan", str(supersedes_id)) if supersedes_id else None
        closing_payload = self.store.get("TradePlan", str(close_id)) if close_id else None
        superseded = TradePlan.from_dict(superseded_payload) if superseded_payload is not None else None
        closing = TradePlan.from_dict(closing_payload) if closing_payload is not None else None
        existing_plans = [TradePlan.from_dict(value) for value in self.store.list("TradePlan")]
        existing_closings = [PlanClosed.from_dict(value) for value in self.store.list("PlanClosed")]
        try:
            policy = RiskPolicy.from_candidate(request["risk_policy"])
            executions = [
                ExecutionRecord.from_dict(execution)
                for execution in self.store.list("ExecutionRecord")
                if execution.get("account_id") == account["account_id"]
                and execution.get("base_snapshot_id") == account["snapshot_id"]
            ]
            account_record = AccountSnapshot.from_dict(account)
            state = build_portfolio(account_record, request["prices"], executions=executions)
            risk_record = evaluate_risk(state, policy)
            investment_case_record = InvestmentCase.from_dict(investment_case)
            valuation_record = ValuationAssessment.from_dict(valuation) if valuation is not None else None
            prepared_record = prepare_plan(
                investment_case_record, valuation_record, account_record, risk_record, plan_request,
                superseded_plan=superseded, closed_plan=closing,
                existing_plans=existing_plans, existing_closings=existing_closings,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationError("INVALID_INPUT", str(error), step="planning.validate") from error
        prepared = prepared_record.as_dict()
        risk = prepared["risk_limit_result"]
        card = prepared["decision_card"]
        draft = prepared["trade_plan_draft"]
        self.store.put("RiskPolicy", policy.policy_id, policy.as_dict())
        self.store.put("RiskLimitResult", risk["risk_limit_result_id"], risk, as_of=card["as_of"])
        self.store.put("DecisionCard", card["decision_card_id"], card, as_of=card["as_of"])
        self.store.put("TradePlanDraft", draft["draft_id"], draft, account_id=draft["account_id"])
        return prepared

    def planning_confirm(self, request: dict[str, Any], *, idempotency_key: str) -> OperationResult:
        return self._mutate("planning.confirm", request, idempotency_key, "TradePlan", self._confirm_plan)

    def _confirm_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        draft = self.store.get("TradePlanDraft", str(request.get("draft_id", "")))
        if draft is None:
            raise ApplicationError("NOT_FOUND", "The referenced TradePlanDraft does not exist.", step="planning.reference")
        try:
            confirmed = confirm_plan(
                TradePlanDraft.from_dict(draft),
                request,
                existing_plans=[TradePlan.from_dict(value) for value in self.store.list("TradePlan")],
                existing_closings=[PlanClosed.from_dict(value) for value in self.store.list("PlanClosed")],
            )
        except StalePlan as error:
            raise ApplicationError("STALE_INPUT", str(error), step="planning.confirmation") from error
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationError("INVALID_INPUT", str(error), step="planning.confirmation") from error
        kind = confirmed.kind
        result = confirmed.as_dict()
        result_id = result["trade_plan_id"] if kind == "TradePlan" else result["plan_closed_id"]
        self.store.put(kind, result_id, result, account_id=draft["account_id"], as_of=result.get("confirmed_at") or result.get("closed_at"))
        return result

    def monitor_evaluate(self, request: dict[str, Any], *, idempotency_key: str) -> OperationResult:
        return self._mutate("monitor.evaluate", request, idempotency_key, "PlanEvaluation", self._evaluate_monitor, replay=self._replay_monitor)

    def _evaluate_monitor(self, request: dict[str, Any]) -> dict[str, Any]:
        plan = self.store.get("TradePlan", str(request.get("trade_plan_id", "")))
        if plan is None:
            raise ApplicationError("NOT_FOUND", "The referenced TradePlan does not exist.", step="monitor.reference")
        try:
            evidence = evidence_set_from_dict(request["evidence_set"])
            plan_record = TradePlan.from_dict(plan)
            active = is_active_plan(
                plan_record,
                [TradePlan.from_dict(value) for value in self.store.list("TradePlan")],
                [PlanClosed.from_dict(value) for value in self.store.list("PlanClosed")],
            )
            evaluation_record = blocked_evaluation(plan_record, evidence, "TradePlan is not active") if not active else evaluate_plan(plan_record, evidence)
            evaluation = evaluation_record.as_dict()
            task_record = create_task(plan_record, evaluation_record) if evaluation_record.status == "triggered" else None
            task = task_record.as_dict() if task_record is not None else None
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationError("INVALID_INPUT", str(error), step="monitor.evaluate") from error
        self.store.put("EvidenceSet", evidence.evidence_set_id, evidence.as_dict(), as_of=evidence.as_of)
        self.store.put("PlanEvaluation", evaluation["plan_evaluation_id"], evaluation, account_id=plan["account_id"], as_of=evaluation["as_of"])
        if task is not None:
            self.store.put("DecisionTask", task["task_id"], task, account_id=plan["account_id"], as_of=task["created_at"])
        return {"plan_evaluation": evaluation, "decision_task": task}

    def review_commit(self, request: dict[str, Any], *, idempotency_key: str) -> OperationResult:
        return self._mutate("review.commit", request, idempotency_key, "DecisionReview", self._commit_review)

    def _commit_review(self, request: dict[str, Any]) -> dict[str, Any]:
        plan = self.store.get("TradePlan", str(request.get("trade_plan_id", "")))
        if plan is None:
            raise ApplicationError("NOT_FOUND", "The referenced TradePlan does not exist.", step="review.reference")
        task_payload = self.store.get("DecisionTask", str(request.get("task_id", ""))) if request.get("task_id") else None
        process_payload = self.store.get("DecisionReview", str(request.get("process_review_id", ""))) if request.get("process_review_id") else None
        task = DecisionTask.from_dict(task_payload) if task_payload is not None else None
        process = DecisionReview.from_dict(process_payload) if process_payload is not None else None
        plan_record = TradePlan.from_dict(plan)
        try:
            frozen_ref_times = self._frozen_ref_times(plan, task_payload) if request.get("review_type") == "PROCESS" and task_payload is not None else None
            review_record = commit_review(
                request,
                plan_record,
                task=task,
                process=process,
                frozen_ref_times=frozen_ref_times,
            )
        except StaleReview as error:
            raise ApplicationError("STALE_INPUT", str(error), step="review.window") from error
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationError("INVALID_INPUT", str(error), step="review.validate") from error
        review = review_record.as_dict()
        self.store.put("DecisionReview", review["decision_review_id"], review, account_id=plan["account_id"], as_of=review["as_of"])
        return review

    def _frozen_ref_times(
        self, plan: dict[str, Any], task: dict[str, Any]
    ) -> dict[str, str | None]:
        card = self._required_record("DecisionCard", str(plan["decision_card_id"]))
        evaluation = self._required_record(
            "PlanEvaluation", str(task["plan_evaluation_id"])
        )
        linked: list[tuple[str, dict[str, Any], str | None]] = [
            (str(plan["trade_plan_id"]), plan, plan.get("confirmed_at")),
            (str(task["task_id"]), task, task.get("created_at")),
            (str(card["decision_card_id"]), card, card.get("as_of")),
            (
                str(evaluation["plan_evaluation_id"]),
                evaluation,
                evaluation.get("as_of"),
            ),
        ]
        references = (
            ("InvestmentCase", card.get("investment_case_id")),
            ("ValuationAssessment", card.get("valuation_assessment_id")),
            ("RiskLimitResult", card.get("risk_limit_result_id")),
            ("AccountSnapshot", card.get("account_snapshot_id")),
            ("EvidenceSet", evaluation.get("evidence_set_id")),
        )
        for kind, record_id in references:
            if record_id is None:
                continue
            record = self._required_record(kind, str(record_id))
            record_time = record.get("as_of")
            if record_time is None and kind == "RiskLimitResult":
                record_time = record.get("portfolio_state", {}).get("as_of")
            linked.append((str(record_id), record, record_time))
        return {record_id: record_time for record_id, _, record_time in linked}

    def _confirm_account(self, candidate: dict[str, Any]) -> dict[str, Any]:
        replaces = candidate.get("replaces_snapshot_id")
        prior = self.store.get("AccountSnapshot", str(replaces)) if replaces else None
        try:
            payload = confirm_account(candidate, prior).as_dict()
        except LookupError as error:
            raise ApplicationError("NOT_FOUND", str(error), step="account.reference") from error
        except StaleAccount as error:
            raise ApplicationError("STALE_INPUT", str(error), step="account.reference") from error
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationError("INVALID_INPUT", str(error), step="account.validate") from error
        self.store.put("AccountSnapshot", payload["snapshot_id"], payload, account_id=payload["account_id"], as_of=payload["as_of"])
        return payload

    def _replay_prepare(self, result_kind: str, result_id: str) -> dict[str, Any]:
        draft = self._required_record(result_kind, result_id)
        card = self._required_record("DecisionCard", str(draft["decision_card_id"]))
        risk = self._required_record("RiskLimitResult", str(card["risk_limit_result_id"]))
        return {"risk_limit_result": risk, "decision_card": card, "trade_plan_draft": draft}

    def _replay_monitor(self, result_kind: str, result_id: str) -> dict[str, Any]:
        evaluation = self._required_record(result_kind, result_id)
        task = next(
            (
                candidate
                for candidate in self.store.list("DecisionTask")
                if candidate.get("plan_evaluation_id") == result_id
            ),
            None,
        )
        return {"plan_evaluation": evaluation, "decision_task": task}

    def _required_record(self, kind: str, record_id: str) -> dict[str, Any]:
        record = self.store.get(kind, record_id)
        if record is None:
            raise ApplicationError(
                "INTERNAL_FAILURE",
                "An idempotent result reference is missing.",
                step="command.replay",
            )
        return record

    def _mutate(
        self,
        operation: str,
        request: dict[str, Any],
        key: str,
        result_kind: str,
        action: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        replay: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> OperationResult:
        if not key:
            return OperationResult.failure("INVALID_INPUT", "An idempotency key is required.", step="command.validate")
        request_digest = digest(request)
        try:
            with self.store.transaction():
                existing = self.store.command(operation, key)
                if existing:
                    if existing["request_digest"] != request_digest:
                        raise ApplicationError("IDEMPOTENCY_CONFLICT", "The idempotency key is bound to a different request.", step="command.replay")
                    loader = replay or self._required_record
                    return OperationResult.success(
                        loader(str(existing["result_kind"]), str(existing["result_id"]))
                    )
                result = action(request)
                referenced_kind, result_id = _result_reference(result_kind, result)
                self.store.put_command(operation, key, request_digest, referenced_kind, result_id)
            return OperationResult.success(result)
        except ApplicationError as error:
            return OperationResult.failure(error.code, error.message, step=error.step)
        except StorageError as error:
            return OperationResult.failure(
                "PERSISTENCE_FAILURE",
                "The atomic operation could not be completed.",
                step=f"{operation}.{error.step}",
            )
        except sqlite3.Error:
            return OperationResult.failure("PERSISTENCE_FAILURE", "The atomic operation could not be completed.", step=f"{operation}.sqlite")
        except (TypeError, ValueError):
            return OperationResult.failure("INVALID_INPUT", "The request contains an invalid value.", step=f"{operation}.validate")
        except Exception:
            return OperationResult.failure("INTERNAL_FAILURE", "The operation failed unexpectedly.", step=operation)


def _result_reference(default_kind: str, result: dict[str, Any]) -> tuple[str, str]:
    direct = {
        "AccountSnapshot": "snapshot_id",
        "InvestmentCase": "investment_case_id",
        "ValuationAssessment": "valuation_assessment_id",
        "DecisionReview": "decision_review_id",
    }
    if default_kind in direct:
        return default_kind, str(result[direct[default_kind]])
    if default_kind == "TradePlan":
        if "plan_closed_id" in result:
            return "PlanClosed", str(result["plan_closed_id"])
        return "TradePlan", str(result["trade_plan_id"])
    if default_kind == "TradePlanDraft":
        return default_kind, str(result["trade_plan_draft"]["draft_id"])
    if default_kind == "PlanEvaluation":
        return default_kind, str(result["plan_evaluation"]["plan_evaluation_id"])
    raise ApplicationError(
        "INTERNAL_FAILURE", "The operation did not return a canonical result reference.", step="command.result"
    )
