from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Mapping

from trading_platform.application.account_state import (
    AccountStateQueries,
    GetEstimatedAccountState,
)
from trading_platform.application.workflow_ledger import (
    DecisionViewPayloadQuery,
    WorkflowLedgerPort,
    WorkspaceWorkflowQuery,
)
from trading_platform.domain.account_state import AccountStateError
from trading_platform.domain.plan_content_diff import compare_plan_content
from trading_platform.research_view import (
    ResearchDecisionView,
    ResearchViewError,
)


class SQLiteReadModelProjection:
    """Projects decision-focused views from canonical persisted authority."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        account_states: AccountStateQueries,
        workflow_ledger: WorkflowLedgerPort,
    ) -> None:
        self._connection = connection
        self._account_states = account_states
        self._workflow_ledger = workflow_ledger

    def portfolio(
        self, account_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]:
        state = self._estimated(account_id)
        tasks = self._tasks(account_id=account_id)
        plans = self._active_plan_summaries(account_id)
        review = self._latest_review(account_id)
        watchlist = self._all(
            "SELECT i.watchlist_item_id,i.security_id,w.name "
            "FROM watchlist_item i JOIN watchlist w "
            "ON w.watchlist_id=i.watchlist_id ORDER BY i.security_id",
            (),
        )
        account_summary = dict(self._account_summary(state))
        account_summary["positions"] = tuple(
            asdict(position) for position in state.positions
        )
        account_summary["watchlist"] = watchlist
        source_ids = self._state_source_ids(state)
        source_ids += tuple(
            str(item["watchlist_item_id"]) for item in watchlist
        )
        source_ids += tuple(
            str(item["decision_task_id"]) for item in tasks
        )
        source_ids += tuple(
            str(item["plan_version_id"])
            for item in plans
            if item.get("plan_version_id")
        )
        if review is not None:
            source_ids += (
                f"{review['discipline_review_id']}:v{review['version_no']}",
            )
        return source_ids, {
            "account_state_summary": account_summary,
            "unresolved_decision_tasks": tasks,
            "material_changes_since_last_review": (
                self._material_changes(account_id)
            ),
            "holding_active_plan_summaries": plans,
            "discipline_exception_summary": (
                tuple(json.loads(review["exceptions_json"]))
                if review is not None
                else ()
            ),
        }

    def holding(
        self, account_id: str, security_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]:
        state = self._estimated(account_id)
        position = next(
            (
                item
                for item in state.positions
                if item.security_id == security_id
            ),
            None,
        )
        plan = self._active_plan(account_id, security_id)
        tasks = self._tasks(
            account_id=account_id, security_id=security_id
        )
        review_item = self._one(
            "SELECT i.* FROM manual_portfolio_review_item i "
            "JOIN manual_portfolio_review_run r "
            "ON r.review_run_id=i.review_run_id "
            "WHERE i.account_id=? AND i.security_id=? "
            "AND r.status IN ('succeeded','succeeded_with_limits') "
            "ORDER BY r.completed_at DESC LIMIT 1",
            (account_id, security_id),
        )
        source_ids = self._state_source_ids(state)
        if plan is not None and plan.get("plan_version_id"):
            source_ids += (str(plan["plan_version_id"]),)
        source_ids += tuple(
            str(item["decision_task_id"]) for item in tasks
        )
        if review_item is not None:
            source_ids += (str(review_item["review_item_id"]),)
        unknown_warnings = (
            tuple(
                f"{name}:unknown"
                for name, value in (
                    ("available_quantity", position.available_quantity_state),
                    ("cost", position.cost_state),
                    ("market_value", position.market_value_state),
                    ("cash", state.cash_state),
                    ("nav", state.nav_state),
                )
                if value == "unknown"
            )
            if position is not None
            else ("position:unknown",)
        )
        warnings = tuple(state.blocking_reasons) + tuple(
            f"unverified:{item}" for item in state.unverified_evidence
        ) + unknown_warnings
        return source_ids, {
            "security_identity": {
                "security_id": security_id,
                "market": "CN_A_SHARE",
            },
            "position_summary": (
                {
                    **asdict(position),
                    "state_status": state.status,
                }
                if position is not None
                else {
                    "security_id": security_id,
                    "position_state": "unknown",
                    "reason_code": "POSITION_NOT_PROVEN",
                }
            ),
            "active_plan_summary": plan,
            "current_review": (
                {
                    "review_run_id": review_item["review_run_id"],
                    "review_item_id": review_item["review_item_id"],
                    "outcome": review_item["outcome"],
                }
                if review_item is not None
                else None
            ),
            "unresolved_decision_tasks": tasks,
            "material_evidence_changes": (
                tuple(
                    json.loads(review_item["material_changes_json"])
                )
                if review_item is not None
                else ()
            ),
            "key_uncertainties": (
                tuple(json.loads(review_item["unable_reasons_json"]))
                if review_item is not None
                else ()
            ),
            "ability_changing_warnings": warnings,
            "drill_down_links": tuple(
                item
                for item in (
                    (
                        {
                            "kind": "plan",
                            "id": plan["plan_id"],
                        }
                        if plan is not None
                        else None
                    ),
                    (
                        {
                            "kind": "review",
                            "id": review_item["review_run_id"],
                        }
                        if review_item is not None
                        else None
                    ),
                )
                if item is not None
            ),
        }

    def plan_detail(
        self, plan_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]:
        master = self._required(
            "SELECT * FROM trade_plan_master WHERE plan_id=?",
            (plan_id,),
            "READ_MODEL_PLAN_NOT_FOUND",
        )
        versions = self._all(
            "SELECT v.plan_version_id,v.version_no,"
            "v.supersedes_version_id,v.strategy_version_id,"
            "v.investment_thesis_version_id,v.account_snapshot_version_id,"
            "v.data_snapshot_id,v.risk_policy_version_id,v.horizon_start,"
            "v.horizon_end,v.review_by,"
            "v.confirmed_at,v.content_json,a.ended_at,a.activated_at "
            "FROM trade_plan_version v LEFT JOIN plan_activation a "
            "ON a.plan_version_id=v.plan_version_id "
            "WHERE v.plan_id=? ORDER BY v.version_no",
            (plan_id,),
        )
        latest = versions[-1] if versions else None
        version_id = (
            str(latest["plan_version_id"])
            if latest is not None
            else None
        )
        open_draft_row = self._one(
            "SELECT draft_id,revision,status,updated_at,"
            "proposed_graph_seal_hash,content_json,proposed_graph_json "
            "FROM trade_plan_draft "
            "WHERE plan_id=? AND status='open'",
            (plan_id,),
        )
        sleeves = (
            self._all(
                "SELECT sleeve_id,sleeve_kind,"
                "quantity_budget_state,quantity_budget_value,"
                "core_floor_state,core_floor_value,"
                "max_notional_state,max_notional_value,"
                "max_loss_state,max_loss_value,grid_constraint_id "
                "FROM trade_plan_sleeve WHERE plan_version_id=? "
                "ORDER BY sleeve_id",
                (version_id,),
            )
            if version_id
            else ()
        )
        rules = (
            self._all(
                "SELECT rule_id,rule_class,rule_kind,priority,scope,"
                "sleeve_id,effect,applies_to,candidate_intent_json,"
                "input_applicability_json,condition_json "
                "FROM trade_plan_rule WHERE plan_version_id=? "
                "ORDER BY rule_order",
                (version_id,),
            )
            if version_id
            else ()
        )
        evaluations = (
            self._all(
                "SELECT e.plan_evaluation_id,e.status,"
                "e.resolution_outcome,e.resolution_reason_code,"
                "e.resolution_json,e.completeness,e.created_at "
                "FROM plan_evaluation e WHERE e.plan_version_id=? "
                "ORDER BY e.created_at DESC LIMIT 1",
                (version_id,),
            )
            if version_id
            else ()
        )
        challenge = self._one(
            "SELECT challenge_id,draft_id,expected_revision,"
            "expected_content_hash,canonical_diff_json,canonical_diff_hash,"
            "status,activation_intent,issued_at,expires_at "
            "FROM plan_confirmation_challenge WHERE plan_id=? "
            "ORDER BY issued_at DESC LIMIT 1",
            (plan_id,),
        )
        evidence = (
            self._all(
                "SELECT ref_type,ref_id,resolution_status,reference_json "
                "FROM trade_plan_evidence_reference "
                "WHERE plan_version_id=? ORDER BY ref_order",
                (version_id,),
            )
            if version_id
            else ()
        )
        tasks = self._tasks(
            account_id=str(master["account_id"]),
            security_id=str(master["security_id"]),
        )
        reviews = (
            self._all(
                "SELECT i.review_run_id,i.review_item_id,i.outcome,"
                "r.selected_complete_session,r.completed_at "
                "FROM manual_portfolio_review_item i "
                "JOIN manual_portfolio_review_run r "
                "ON r.review_run_id=i.review_run_id "
                "WHERE i.plan_version_id=? ORDER BY r.created_at DESC",
                (version_id,),
            )
            if version_id
            else ()
        )
        proposals = (
            self._all(
                "SELECT proposal_id,revision,status,assessment_id,"
                "proposed_canonical_patch_json,proposed_diff_hash,updated_at "
                "FROM plan_change_proposal WHERE base_plan_version_id=? "
                "ORDER BY proposal_id,revision",
                (version_id,),
            )
            if version_id
            else ()
        )
        freshness = self._plan_evidence_freshness(latest, evidence)
        rule_states = self._rule_states(rules, evaluations)
        current_content = (
            json.loads(latest["content_json"])
            if latest is not None
            else {}
        )
        open_draft = _open_plan_draft_projection(open_draft_row)
        draft_content = (
            json.loads(open_draft_row["content_json"])
            if open_draft_row is not None
            else None
        )
        readable_draft_diff = (
            compare_plan_content(current_content, draft_content).as_dict()
            if draft_content is not None
            else None
        )
        change_diffs = tuple(
            {
                "change_kind": "final_confirmation",
                "status": challenge["status"],
                "revision": challenge["expected_revision"],
                "changed_at": challenge["issued_at"],
                "readable_diff": readable_draft_diff,
            }
            for challenge in (challenge,)
            if challenge is not None
        ) + tuple(
            {
                "change_kind": "revision_proposal",
                "status": proposal["status"],
                "revision": proposal["revision"],
                "changed_at": proposal["updated_at"],
                "readable_diff": compare_plan_content(
                    current_content,
                    json.loads(
                        proposal["proposed_canonical_patch_json"]
                    )["content"],
                ).as_dict(),
            }
            for proposal in proposals
        )
        source_ids = (plan_id,) + tuple(
            str(item["plan_version_id"]) for item in versions
        )
        source_ids += tuple(
            str(item["plan_evaluation_id"]) for item in evaluations
        )
        source_ids += tuple(
            str(item["decision_task_id"]) for item in tasks
        )
        source_ids += tuple(
            str(item["review_item_id"]) for item in reviews
        )
        source_ids += tuple(
            f"{item['proposal_id']}:r{item['revision']}"
            for item in proposals
        )
        if challenge is not None:
            source_ids += (str(challenge["challenge_id"]),)
        if open_draft is not None:
            source_ids += (str(open_draft["draft_id"]),)
        return source_ids, {
            "plan_identity": {
                "plan_id": plan_id,
                "account_id": master["account_id"],
                "security_id": master["security_id"],
                "lifecycle_status": master["lifecycle_status"],
                "strategy_version_id": master["strategy_version_id"],
                "latest_plan_version_id": version_id,
                "open_draft_id": (
                    open_draft["draft_id"]
                    if open_draft is not None
                    else None
                ),
            },
            "sleeve_summary": sleeves,
            "rules": tuple(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key
                        not in {
                            "candidate_intent_json",
                            "input_applicability_json",
                            "condition_json",
                        }
                    },
                    "candidate_intent": (
                        json.loads(item["candidate_intent_json"])
                        if item["candidate_intent_json"] is not None
                        else None
                    ),
                    "input_applicability": json.loads(
                        item["input_applicability_json"]
                    ),
                    "condition": json.loads(item["condition_json"]),
                }
                for item in rules
            ),
            "latest_frozen_evaluations": tuple(
                {
                    **item,
                    "resolution": json.loads(item["resolution_json"]),
                }
                for item in evaluations
            ),
            "evidence_freshness": freshness,
            "rule_states": rule_states,
            "related_tasks": tasks,
            "review_history": reviews,
            "change_diffs": change_diffs,
            "confirmation_state": (
                {
                    **challenge,
                    "canonical_diff": json.loads(
                        challenge["canonical_diff_json"]
                    ),
                    "readable_diff": readable_draft_diff,
                    "open_draft": open_draft,
                }
                if challenge is not None
                else (
                    {"open_draft": open_draft}
                    if open_draft is not None
                    else None
                )
            ),
            "version_history": tuple(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key != "content_json"
                    },
                    "content": _plan_content_projection(
                        item["content_json"]
                    ),
                }
                for item in versions
            ),
            "diagnostics": {
                "disclosure": "details_only",
                "version_count": len(versions),
            },
        }

    def review(
        self, account_id: str, review_run_id: str | None
    ) -> tuple[tuple[str, ...], Mapping[str, object]]:
        periodic = self._discipline_review(account_id)
        run = (
            self._one(
                "SELECT * FROM manual_portfolio_review_run "
                "WHERE review_run_id=? AND account_id=?",
                (review_run_id, account_id),
            )
            if review_run_id
            else self._one(
                "SELECT * FROM manual_portfolio_review_run "
                "WHERE account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            )
        )
        if run is None:
            return (
                (str(periodic["discipline_review_id"]),)
                if periodic is not None
                else ()
            ), {
                "review_run": None,
                "holding_outcomes": (),
                "unresolved_or_deferred_tasks": self._tasks(
                    account_id=account_id
                ),
                "plan_impact_summaries": (),
                "proposal_summaries": (),
                "periodic_discipline_review": periodic,
                "diagnostics": {
                    "disclosure": "details_only",
                    "checkpoint_count": 0,
                },
            }
        run_id = str(run["review_run_id"])
        items = self._all(
            "SELECT review_item_id,security_id,outcome,"
            "material_changes_json,unable_reasons_json,"
            "blocked_reasons_json FROM manual_portfolio_review_item "
            "WHERE review_run_id=? ORDER BY security_id",
            (run_id,),
        )
        assessments = self._all(
            "SELECT assessment_id,review_item_id,plan_version_id,"
            "review_rule_id,review_rule_result,impact_kind,materiality,"
            "uncertainties_json,what_changed,what_would_change_the_view "
            "FROM plan_impact_assessment WHERE review_run_id=? "
            "ORDER BY created_at",
            (run_id,),
        )
        proposals = self._all(
            "SELECT p.proposal_id,p.revision,p.status,p.assessment_id,"
            "p.base_plan_version_id,p.accepted_draft_id "
            "FROM plan_change_proposal p "
            "JOIN plan_impact_assessment a "
            "ON a.assessment_id=p.assessment_id "
            "WHERE a.review_run_id=? AND p.revision=("
            "SELECT max(x.revision) FROM plan_change_proposal x "
            "WHERE x.proposal_id=p.proposal_id) "
            "ORDER BY p.proposal_id",
            (run_id,),
        )
        checkpoints = self._all(
            "SELECT checkpoint_id,status,attempt_no "
            "FROM manual_portfolio_review_checkpoint "
            "WHERE review_run_id=? ORDER BY security_id,stage",
            (run_id,),
        )
        source_ids = (run_id,) + tuple(
            str(item["review_item_id"]) for item in items
        )
        source_ids += tuple(
            str(item["assessment_id"]) for item in assessments
        )
        source_ids += tuple(
            f"{item['proposal_id']}:r{item['revision']}"
            for item in proposals
        )
        if periodic is not None:
            source_ids += (str(periodic["discipline_review_id"]),)
        return source_ids, {
            "review_run": {
                "review_run_id": run_id,
                "selected_session": run["selected_complete_session"],
                "window_start_exclusive": run[
                    "window_start_exclusive"
                ],
                "window_end_inclusive": run["window_end_inclusive"],
                "status": run["status"],
            },
            "holding_outcomes": tuple(
                {
                    **item,
                    "material_changes": json.loads(
                        item["material_changes_json"]
                    ),
                    "unable_reasons": json.loads(
                        item["unable_reasons_json"]
                    ),
                    "blocked_reasons": json.loads(
                        item["blocked_reasons_json"]
                    ),
                }
                for item in items
            ),
            "unresolved_or_deferred_tasks": self._tasks(
                account_id=account_id, review_run_id=run_id
            ),
            "plan_impact_summaries": tuple(
                {
                    **item,
                    "uncertainties": json.loads(
                        item["uncertainties_json"]
                    ),
                }
                for item in assessments
            ),
            "proposal_summaries": proposals,
            "periodic_discipline_review": periodic,
            "diagnostics": {
                "disclosure": "details_only",
                "checkpoints": checkpoints,
            },
        }

    def research_index(
        self, security_id: str | None
    ) -> tuple[tuple[str, ...], Mapping[str, object]]:
        securities = (
            (security_id,)
            if security_id
            else tuple(
                str(row["security_id"])
                for row in self._connection.execute(
                    "SELECT security_id FROM security ORDER BY security_id"
                )
            )
        )
        items: list[Mapping[str, object]] = []
        source_ids: list[str] = []
        for current_security in securities:
            evidence = self._workflow_ledger.load(
                WorkspaceWorkflowQuery(current_security)
            )
            succeeded = [
                row
                for row in evidence.workflows
                if row["status"] in {
                    "succeeded",
                    "succeeded_with_limits",
                }
            ]
            if not succeeded:
                continue
            workflow_id = str(succeeded[0]["workflow_run_id"])
            persisted = self._workflow_ledger.load(
                DecisionViewPayloadQuery(workflow_id)
            )
            try:
                view = ResearchDecisionView.from_dict(
                    json.loads(persisted.json_bytes)
                )
            except (json.JSONDecodeError, ResearchViewError) as error:
                raise ResearchViewError(
                    "RESEARCH_VIEW_PERSISTED_INVALID"
                ) from error
            source_ids.extend(
                (view.view_id, workflow_id, view.research_run_id)
            )
            items.append(
                {
                    "security_id": view.security_id,
                    "research_decision_view_id": view.view_id,
                    "research_run_id": view.research_run_id,
                    "status": view.status,
                    "as_of": view.as_of,
                    "data_quality_grade": view.data_quality_grade,
                    "deliverables": {
                        "html_report": "ready",
                        "pdf_report": "ready",
                        "chart": "available_from_frozen_market_data",
                        "workbook": persisted.workbook_status,
                    },
                    "dimensions": {
                        "company": view.story.get("company"),
                        "forecast": view.story.get("forecast"),
                        "valuation": view.valuation_view,
                        "technical": view.story.get("technical"),
                        "events": view.story.get("events"),
                    },
                    "material_change": view.risk_reward_summary,
                    "key_uncertainties": view.key_uncertainties,
                    "what_would_change_the_view": (
                        view.what_would_change_the_view
                    ),
                    "ability_impact": (
                        "unable"
                        if view.status
                        in {"blocked", "data_insufficient"}
                        else "available"
                    ),
                }
            )
        return tuple(source_ids), {"research_items": tuple(items)}

    def account_editor(
        self, account_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]:
        version = self._one(
            "SELECT v.*,c.cash_state,c.cash_value,c.nav_state,c.nav_value,"
            "c.fees_state,c.fees_value FROM account_snapshot_version v "
            "JOIN account_snapshot_projection_checkpoint p "
            "ON p.account_snapshot_version_id=v.account_snapshot_version_id "
            "JOIN account_snapshot_cash c "
            "ON c.account_snapshot_version_id=v.account_snapshot_version_id "
            "WHERE p.account_id=?",
            (account_id,),
        )
        draft = self._one(
            "SELECT * FROM account_snapshot_draft WHERE account_id=? "
            "AND status='open' ORDER BY revision DESC LIMIT 1",
            (account_id,),
        )
        draft_content = (
            json.loads(draft["content_json"])
            if draft is not None
            else None
        )
        capabilities = (
            self._all(
                "SELECT capability_key,state,reason_code,"
                "required_field_refs_json FROM account_snapshot_capability "
                "WHERE account_snapshot_version_id=? "
                "ORDER BY capability_key",
                (version["account_snapshot_version_id"],),
            )
            if version is not None
            else ()
        )
        confirmed_positions = (
            self._all(
                "SELECT security_id,total_quantity,"
                "available_quantity_state,available_quantity_value,"
                "cost_state,cost_value,market_value_state,"
                "market_value_value FROM account_snapshot_position "
                "WHERE account_snapshot_version_id=? ORDER BY security_id",
                (version["account_snapshot_version_id"],),
            )
            if version is not None
            else ()
        )
        receipt = (
            self._one(
                "SELECT invocation_id,status,created_at "
                "FROM application_command_receipt "
                "WHERE command_name='account_snapshot.confirm@1' "
                "AND revision_or_version_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (version["account_snapshot_version_id"],),
            )
            if version is not None
            else None
        )
        source_ids = tuple(
            str(value)
            for value in (
                (
                    version["account_snapshot_version_id"]
                    if version is not None
                    else None
                ),
                draft["draft_id"] if draft is not None else None,
                receipt["invocation_id"] if receipt is not None else None,
            )
            if value is not None
        )
        return source_ids, {
            "confirmed_snapshot_summary": (
                {
                    "account_snapshot_version_id": version[
                        "account_snapshot_version_id"
                    ],
                    "version_no": version["version_no"],
                    "as_of_at": version["as_of_at"],
                    "as_of_precision": version["as_of_precision"],
                    "cash_state": version["cash_state"],
                    "cash_value": version["cash_value"],
                    "nav_state": version["nav_state"],
                    "nav_value": version["nav_value"],
                    "fees_state": version["fees_state"],
                    "fees_value": version["fees_value"],
                    "currency": version["currency"],
                    "positions": confirmed_positions,
                }
                if version is not None
                else None
            ),
            "current_draft": (
                {
                    key: draft_content[key]
                    for key in (
                        "draft_id",
                        "account_id",
                        "revision",
                        "status",
                        "source_kind",
                        "redacted_source_ref",
                        "as_of_at",
                        "as_of_precision",
                        "timezone",
                        "session_semantics",
                        "currency",
                        "cash_state",
                        "cash_value",
                        "nav_state",
                        "nav_value",
                        "fees_state",
                        "fees_value",
                        "positions",
                        "previous_snapshot_version_id",
                        "revises_snapshot_version_id",
                        "corrects_snapshot_version_id",
                        "correction_reason",
                    )
                }
                if draft_content is not None
                else None
            ),
            "field_lineage": (
                (
                    {
                        "field": "snapshot",
                        "source_kind": version["source_kind"],
                        "redacted_source_ref": version[
                            "redacted_source_ref"
                        ],
                    },
                )
                if version is not None
                else ()
            ),
            "validation": (
                {
                    "state": draft["validation_state"],
                    "errors": json.loads(
                        draft["validation_errors_json"]
                    ),
                }
                if draft is not None
                else {"state": "not_applicable", "errors": []}
            ),
            "capability_impacts": tuple(
                {
                    **item,
                    "required_field_refs": json.loads(
                        item["required_field_refs_json"]
                    ),
                }
                for item in capabilities
            ),
            "canonical_diff": (
                {
                    "canonical_diff": json.loads(
                        draft["canonical_diff"]
                    ),
                    "canonical_diff_hash": draft[
                        "canonical_diff_hash"
                    ],
                    "expected_revision": draft["revision"],
                }
                if draft is not None
                else None
            ),
            "confirmation_receipt_status": receipt,
        }

    def _plan_evidence_freshness(
        self,
        version: Mapping[str, object] | None,
        evidence: tuple[Mapping[str, object], ...],
    ) -> tuple[Mapping[str, object], ...]:
        if version is None:
            return ()
        snapshot = self._one(
            "SELECT effective_session_date,last_success_at "
            "FROM data_snapshot WHERE data_snapshot_id=?",
            (version["data_snapshot_id"],),
        )
        account = self._one(
            "SELECT as_of_at,as_of_precision,confirmed_at "
            "FROM account_snapshot_version "
            "WHERE account_snapshot_version_id=?",
            (version["account_snapshot_version_id"],),
        )
        risk = (
            self._one(
                "SELECT confirmed_at FROM portfolio_risk_policy_version "
                "WHERE portfolio_risk_policy_version_id=?",
                (version["risk_policy_version_id"],),
            )
            if version.get("risk_policy_version_id") is not None
            else None
        )
        anchors: list[Mapping[str, object]] = [
            {
                "evidence_kind": "market_data_snapshot",
                "evidence_id": version["data_snapshot_id"],
                "freshness_state": "frozen",
                "as_of": (
                    snapshot["effective_session_date"]
                    if snapshot is not None
                    else None
                ),
                "last_success_at": (
                    snapshot["last_success_at"]
                    if snapshot is not None
                    else None
                ),
            },
            {
                "evidence_kind": "account_snapshot",
                "evidence_id": version["account_snapshot_version_id"],
                "freshness_state": "frozen",
                "as_of": account["as_of_at"] if account is not None else None,
                "as_of_precision": (
                    account["as_of_precision"]
                    if account is not None
                    else None
                ),
            },
        ]
        if version.get("risk_policy_version_id") is not None:
            anchors.append(
                {
                    "evidence_kind": "risk_policy",
                    "evidence_id": version["risk_policy_version_id"],
                    "freshness_state": "frozen",
                    "as_of": risk["confirmed_at"] if risk is not None else None,
                }
            )
        anchors.extend(
            {
                "evidence_kind": item["ref_type"],
                "evidence_id": item["ref_id"],
                "freshness_state": item["resolution_status"],
                "reference": json.loads(item["reference_json"]),
            }
            for item in evidence
        )
        return tuple(anchors)

    @staticmethod
    def _rule_states(
        rules: tuple[Mapping[str, object], ...],
        evaluations: tuple[Mapping[str, object], ...],
    ) -> tuple[Mapping[str, object], ...]:
        evaluation = evaluations[0] if evaluations else None
        resolution = (
            json.loads(evaluation["resolution_json"])
            if evaluation is not None
            else {}
        )
        winner = resolution.get("winner")
        winner_id = (
            str(winner.get("rule_id"))
            if isinstance(winner, Mapping) and winner.get("rule_id")
            else None
        )
        contributing_rule_ids = {
            str(value)
            for value in resolution.get("contributing_rule_ids", ())
        }
        outcome = (
            str(evaluation["resolution_outcome"])
            if evaluation is not None
            else "not_evaluated"
        )
        return tuple(
            {
                "rule_id": rule["rule_id"],
                "rule_class": rule["rule_class"],
                "rule_kind": rule["rule_kind"],
                "state": (
                    "triggered"
                    if (
                        winner_id == rule["rule_id"]
                        or rule["rule_id"] in contributing_rule_ids
                    )
                    else (
                        "not_triggered"
                        if outcome == "no_action"
                        else (
                            "not_selected"
                            if evaluation is not None
                            else "not_evaluated"
                        )
                    )
                ),
                "evaluation_id": (
                    evaluation["plan_evaluation_id"]
                    if evaluation is not None
                    else None
                ),
                "reason_code": (
                    evaluation["resolution_reason_code"]
                    if evaluation is not None
                    else "PLAN_NOT_EVALUATED"
                ),
            }
            for rule in rules
        )

    def _discipline_review(
        self, account_id: str
    ) -> Mapping[str, object] | None:
        row = self._one(
            "SELECT * FROM discipline_review_version "
            "WHERE account_id=? "
            "ORDER BY period_end_session DESC,version_no DESC LIMIT 1",
            (account_id,),
        )
        if row is None:
            return None
        return {
            "discipline_review_id": row["discipline_review_id"],
            "version_no": row["version_no"],
            "status": row["status"],
            "period_kind": row["period_kind"],
            "period_start_session": row["period_start_session"],
            "period_end_session": row["period_end_session"],
            "exceptions": json.loads(row["exceptions_json"]),
            "overridden_items": json.loads(row["overridden_items_json"]),
            "unrecorded_items": json.loads(row["unrecorded_items_json"]),
            "unverified_items": json.loads(row["unverified_items_json"]),
            "evidence_gap_summary": json.loads(
                row["evidence_gap_summary_json"]
            ),
            "created_at": row["created_at"],
            "confirmed_at": row["confirmed_at"],
        }
    def _estimated(self, account_id: str):
        try:
            return self._account_states.get(
                GetEstimatedAccountState(account_id)
            )
        except AccountStateError as error:
            raise AccountStateError(
                f"READ_MODEL_ACCOUNT_STATE_UNAVAILABLE:{error.code}"
            ) from error

    @staticmethod
    def _account_summary(state) -> Mapping[str, object]:
        return {
            "account_id": state.account_id,
            "confirmed_snapshot": {
                "account_snapshot_version_id": (
                    state.derived_from_snapshot_id
                ),
                "as_of": state.derived_from_snapshot_as_of,
                "as_of_precision": (
                    state.derived_from_snapshot_as_of_precision
                ),
            },
            "estimated_state": {
                "estimated_account_state_id": (
                    state.estimated_account_state_id
                ),
                "cash_state": state.cash_state,
                "cash_value": state.cash_value,
                "nav_state": state.nav_state,
                "nav_value": state.nav_value,
                "currency": state.currency,
                "status": state.status,
                "unverified_count": len(state.unverified_evidence),
            },
        }

    @staticmethod
    def _state_source_ids(state) -> tuple[str, ...]:
        return (
            state.derived_from_snapshot_id,
            state.estimated_account_state_id,
            *state.execution_record_ids,
        )

    def _tasks(
        self,
        *,
        account_id: str,
        security_id: str | None = None,
        review_run_id: str | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        where = ["t.account_id=?"]
        values: list[object] = [account_id]
        if security_id is not None:
            where.append("t.security_id=?")
            values.append(security_id)
        if review_run_id is not None:
            where.append("t.review_run_id=?")
            values.append(review_run_id)
        rows = self._all(
            "SELECT t.decision_task_id,t.security_id,t.task_kind,"
            "t.reason_code,t.priority,t.created_at,"
            "coalesce(x.to_status,t.initial_status) AS status "
            "FROM decision_task t LEFT JOIN decision_task_transition x "
            "ON x.decision_task_id=t.decision_task_id "
            "AND x.transition_seq=(SELECT max(y.transition_seq) "
            "FROM decision_task_transition y "
            "WHERE y.decision_task_id=t.decision_task_id) "
            f"WHERE {' AND '.join(where)} "
            "AND coalesce(x.to_status,t.initial_status) "
            "IN ('open','deferred') "
            "ORDER BY CASE t.priority "
            "WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'normal' THEN 2 ELSE 3 END,"
            "t.created_at,t.decision_task_id",
            tuple(values),
        )
        return rows

    def _active_plan_summaries(
        self, account_id: str
    ) -> tuple[Mapping[str, object], ...]:
        return self._all(
            "SELECT m.security_id,m.plan_id,m.lifecycle_status,"
            "m.strategy_version_id,a.plan_version_id,v.version_no,"
            "d.draft_id AS open_draft_id,d.revision AS draft_revision,"
            "d.updated_at AS draft_updated_at "
            "FROM trade_plan_master m LEFT JOIN plan_activation a "
            "ON a.plan_id=m.plan_id AND a.ended_at IS NULL "
            "LEFT JOIN trade_plan_version v "
            "ON v.plan_version_id=a.plan_version_id "
            "LEFT JOIN trade_plan_draft d "
            "ON d.plan_id=m.plan_id AND d.status='open' "
            "WHERE m.account_id=? ORDER BY m.security_id",
            (account_id,),
        )

    def _active_plan(
        self, account_id: str, security_id: str
    ) -> Mapping[str, object] | None:
        row = self._one(
            "SELECT m.plan_id,m.lifecycle_status,a.plan_version_id,"
            "v.version_no,v.strategy_version_id "
            "FROM trade_plan_master m JOIN plan_activation a "
            "ON a.plan_id=m.plan_id AND a.ended_at IS NULL "
            "JOIN trade_plan_version v "
            "ON v.plan_version_id=a.plan_version_id "
            "WHERE m.account_id=? AND m.security_id=?",
            (account_id, security_id),
        )
        if row is None:
            return None
        sleeves = self._all(
            "SELECT sleeve_kind,quantity_budget_state,"
            "quantity_budget_value,core_floor_state,core_floor_value "
            "FROM trade_plan_sleeve WHERE plan_version_id=? "
            "ORDER BY sleeve_kind",
            (row["plan_version_id"],),
        )
        return {**row, "sleeves": sleeves}

    def _latest_review(
        self, account_id: str
    ) -> Mapping[str, object] | None:
        return self._one(
            "SELECT * FROM discipline_review_version "
            "WHERE account_id=? AND status='confirmed' "
            "ORDER BY period_end_session DESC,version_no DESC LIMIT 1",
            (account_id,),
        )

    def _material_changes(self, account_id: str) -> tuple[str, ...]:
        rows = self._all(
            "SELECT i.material_changes_json "
            "FROM manual_portfolio_review_item i "
            "JOIN manual_portfolio_review_run r "
            "ON r.review_run_id=i.review_run_id "
            "WHERE r.account_id=? "
            "AND r.status IN ('succeeded','succeeded_with_limits') "
            "AND r.completed_at=("
            "SELECT max(x.completed_at) "
            "FROM manual_portfolio_review_run x "
            "WHERE x.account_id=r.account_id "
            "AND x.status IN ('succeeded','succeeded_with_limits'))",
            (account_id,),
        )
        return tuple(
            sorted(
                {
                    str(change)
                    for row in rows
                    for change in json.loads(
                        row["material_changes_json"]
                    )
                }
            )
        )

    def _one(
        self, sql: str, values: tuple[object, ...]
    ) -> Mapping[str, object] | None:
        row = self._connection.execute(sql, values).fetchone()
        return dict(row) if row is not None else None

    def _required(
        self,
        sql: str,
        values: tuple[object, ...],
        code: str,
    ) -> Mapping[str, object]:
        row = self._one(sql, values)
        if row is None:
            raise ValueError(code)
        return row

    def _all(
        self, sql: str, values: tuple[object, ...]
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(
            dict(row) for row in self._connection.execute(sql, values)
        )

def _open_plan_draft_projection(
    row: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if row is None:
        return None
    graph = json.loads(str(row["proposed_graph_json"]))
    version = graph.get("version") if isinstance(graph, Mapping) else None
    if not isinstance(version, Mapping):
        return None
    sleeves = graph.get("sleeves", ())
    rules = graph.get("rules", ())
    references = graph.get("evidence_references", ())
    return {
        "draft_id": row["draft_id"],
        "revision": row["revision"],
        "status": row["status"],
        "updated_at": row["updated_at"],
        "horizon": {
            "start": version.get("horizon_start"),
            "end": version.get("horizon_end"),
            "review_by": version.get("review_by"),
        },
        "content": _plan_content_projection(str(row["content_json"])),
        "sleeves": tuple(
            item for item in sleeves if isinstance(item, Mapping)
        ),
        "rules": tuple(item for item in rules if isinstance(item, Mapping)),
        "evidence": tuple(
            {
                "evidence_kind": item.get("ref_type"),
                "freshness_state": item.get("resolution_status"),
                "as_of": version.get("horizon_start"),
            }
            for item in references
            if isinstance(item, Mapping)
        ),
    }


_PLAN_CONTENT_FIELDS = (
    "schema_version",
    "authoring_schema_version",
    "authoring_input_hash",
    "authoring_intent_hash",
    "research_workflow_run_id",
    "research_view_id",
    "recent_trend_assessment_id",
    "account_snapshot_version_id",
    "portfolio_risk_policy_version_id",
    "strategy_version_id",
    "strategy_key",
    "strategy_parameters",
    "observed_trend",
    "risk_increase_evidence",
    "risk_policy_limits",
    "risk_budget_state",
)


def _plan_content_projection(encoded: str) -> Mapping[str, object]:
    content = json.loads(encoded)
    return {
        key: content[key]
        for key in _PLAN_CONTENT_FIELDS
        if key in content
    }

__all__ = ["SQLiteReadModelProjection"]
