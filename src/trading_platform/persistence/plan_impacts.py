from __future__ import annotations

import json
import sqlite3

from trading_platform.domain.plan_impacts import (
    FrozenPlanImpactEvidence,
    PlanChangeProposal,
    PlanImpactAssessment,
    PlanImpactError,
    PlanImpactFinding,
)
from trading_platform.identity import canonical_hash

from .locking import DataRootWriterLock


class SQLitePlanImpactRepository:
    """Owns frozen plan-impact authority and immutable proposal revisions."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock

    def save_assessment(
        self, command, assessment: PlanImpactAssessment
    ) -> PlanImpactAssessment:
        assessment.validate()
        request_hash = canonical_hash(command)
        replay = self._connection.execute(
            "SELECT assessment_id,request_hash "
            "FROM plan_impact_assessment WHERE invocation_id=?",
            (command.invocation_id,),
        ).fetchone()
        if replay is not None:
            if replay["request_hash"] != request_hash:
                raise PlanImpactError(
                    "PLAN_IMPACT_INVOCATION_CONFLICT"
                )
            return self.get_assessment(replay["assessment_id"])
        evidence = assessment.evidence
        finding = assessment.finding
        with self._writer_lock.acquire(
            f"plan-impact:{assessment.assessment_id}"
        ):
            try:
                with self._connection:
                    self._connection.execute(
                        "INSERT INTO plan_impact_assessment VALUES("
                        + ",".join("?" for _ in range(28))
                        + ")",
                        (
                            assessment.assessment_id,
                            command.invocation_id,
                            request_hash,
                            evidence.review_run_id,
                            evidence.review_item_id,
                            evidence.plan_version_id,
                            evidence.review_rule_id,
                            evidence.review_rule_result,
                            evidence.evidence_manifest_id,
                            self._json(evidence.research_refs),
                            self._json(evidence.market_refs),
                            self._json(evidence.industry_refs),
                            self._json(evidence.sector_refs),
                            self._json(evidence.unable_reasons),
                            evidence.authority_content_hash,
                            finding.impact_kind,
                            finding.materiality,
                            self._json(finding.uncertainties),
                            finding.what_changed,
                            finding.what_would_change_the_view,
                            finding.schema_version,
                            assessment.model_identity,
                            assessment.policy_identity,
                            assessment.prompt_identity,
                            assessment.content_hash,
                            assessment.created_by,
                            assessment.created_at,
                            assessment.schema_version,
                        ),
                    )
                    self._insert_receipt(
                        invocation_id=command.invocation_id,
                        command_name="plan_impact_assessment.create@1",
                        request_hash=request_hash,
                        result_type="PlanImpactAssessment",
                        aggregate_id=assessment.assessment_id,
                        revision_id=assessment.assessment_id,
                        status="created",
                        decision_actor=command.decision_actor,
                        interaction_channel=command.interaction_channel,
                        transport_actor=command.transport_actor,
                        created_at=assessment.created_at,
                    )
            except sqlite3.IntegrityError as error:
                raise PlanImpactError(
                    "PLAN_IMPACT_STORAGE_CONFLICT"
                ) from error
        return self.get_assessment(assessment.assessment_id)

    def get_assessment(
        self, assessment_id: str
    ) -> PlanImpactAssessment:
        row = self._connection.execute(
            "SELECT * FROM plan_impact_assessment "
            "WHERE assessment_id=?",
            (assessment_id,),
        ).fetchone()
        if row is None:
            raise PlanImpactError("PLAN_IMPACT_NOT_FOUND")
        evidence_identity = {
            "review_run_id": row["review_run_id"],
            "review_item_id": row["review_item_id"],
            "plan_version_id": row["plan_version_id"],
            "review_rule_id": row["review_rule_id"],
            "review_rule_result": row["review_rule_result"],
            "evidence_manifest_id": row["evidence_manifest_id"],
            "research_refs": tuple(json.loads(row["research_refs_json"])),
            "market_refs": tuple(json.loads(row["market_refs_json"])),
            "industry_refs": tuple(json.loads(row["industry_refs_json"])),
            "sector_refs": tuple(json.loads(row["sector_refs_json"])),
            "unable_reasons": tuple(
                json.loads(row["unable_reasons_json"])
            ),
            "schema_version": "FrozenPlanImpactEvidence@1",
        }
        evidence = FrozenPlanImpactEvidence(
            **evidence_identity,
            authority_content_hash=row["authority_content_hash"],
        )
        if (
            evidence.authority_content_hash
            != canonical_hash(evidence_identity)
        ):
            raise PlanImpactError("PLAN_IMPACT_EVIDENCE_CORRUPT")
        assessment = PlanImpactAssessment(
            assessment_id=row["assessment_id"],
            evidence=evidence,
            finding=PlanImpactFinding(
                impact_kind=row["impact_kind"],
                materiality=row["materiality"],
                uncertainties=tuple(
                    json.loads(row["uncertainties_json"])
                ),
                what_changed=row["what_changed"],
                what_would_change_the_view=row[
                    "what_would_change_the_view"
                ],
                schema_version=row["finding_schema_version"],
            ),
            model_identity=row["model_identity"],
            policy_identity=row["policy_identity"],
            prompt_identity=row["prompt_identity"],
            content_hash=row["content_hash"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            schema_version=row["schema_version"],
        )
        assessment.validate()
        return assessment

    def save_proposal(
        self, command, proposal: PlanChangeProposal
    ) -> PlanChangeProposal:
        proposal.validate()
        return self._insert_proposal_revision(
            invocation_id=command.invocation_id,
            request_hash=canonical_hash(command),
            proposal=proposal,
            actor=command,
        )

    def get_proposal(
        self, proposal_id: str
    ) -> PlanChangeProposal:
        row = self._connection.execute(
            "SELECT * FROM plan_change_proposal "
            "WHERE proposal_id=? ORDER BY revision DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        if row is None:
            raise PlanImpactError("PROPOSAL_NOT_FOUND")
        return self._proposal(row)

    def assert_base_is_active(
        self, proposal: PlanChangeProposal
    ) -> None:
        row = self._connection.execute(
            "SELECT a.plan_version_id FROM plan_activation a "
            "WHERE a.plan_id=("
            "SELECT plan_id FROM trade_plan_version "
            "WHERE plan_version_id=?) "
            "AND a.ended_at IS NULL",
            (proposal.base_plan_version_id,),
        ).fetchone()
        if (
            row is None
            or row["plan_version_id"]
            != proposal.base_plan_version_id
        ):
            raise PlanImpactError("PROPOSAL_BASE_PLAN_STALE")

    def plan_owner(
        self, plan_version_id: str
    ) -> tuple[str, str]:
        row = self._connection.execute(
            "SELECT m.account_id,m.security_id "
            "FROM trade_plan_version v "
            "JOIN trade_plan_master m ON m.plan_id=v.plan_id "
            "WHERE v.plan_version_id=?",
            (plan_version_id,),
        ).fetchone()
        if row is None:
            raise PlanImpactError("PROPOSAL_BASE_PLAN_NOT_FOUND")
        return row["account_id"], row["security_id"]

    def dispose(
        self,
        *,
        invocation_id: str,
        request_hash: str,
        proposal: PlanChangeProposal,
        actor,
    ) -> PlanChangeProposal:
        replay = self._connection.execute(
            "SELECT proposal_id,revision,request_hash "
            "FROM plan_change_proposal "
            "WHERE command_invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if replay is not None:
            if replay["request_hash"] != request_hash:
                raise PlanImpactError(
                    "PROPOSAL_INVOCATION_CONFLICT"
                )
            row = self._connection.execute(
                "SELECT * FROM plan_change_proposal "
                "WHERE proposal_id=? AND revision=?",
                (replay["proposal_id"], replay["revision"]),
            ).fetchone()
            assert row is not None
            return self._proposal(row)
        latest = self.get_proposal(proposal.proposal_id)
        if proposal.status not in {"accepted", "rejected"}:
            raise PlanImpactError("PROPOSAL_ALREADY_DISPOSED")
        if (
            latest.status != "open"
            or proposal.revision != latest.revision + 1
        ):
            raise PlanImpactError("PROPOSAL_REVISION_CONFLICT")
        return self._insert_proposal_revision(
            invocation_id=invocation_id,
            request_hash=request_hash,
            proposal=proposal,
            actor=actor,
        )

    def _insert_proposal_revision(
        self,
        *,
        invocation_id: str,
        request_hash: str,
        proposal: PlanChangeProposal,
        actor=None,
    ) -> PlanChangeProposal:
        replay = self._connection.execute(
            "SELECT proposal_id,revision,request_hash "
            "FROM plan_change_proposal "
            "WHERE command_invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if replay is not None:
            if replay["request_hash"] != request_hash:
                raise PlanImpactError(
                    "PROPOSAL_INVOCATION_CONFLICT"
                )
            row = self._connection.execute(
                "SELECT * FROM plan_change_proposal "
                "WHERE proposal_id=? AND revision=?",
                (replay["proposal_id"], replay["revision"]),
            ).fetchone()
            assert row is not None
            return self._proposal(row)
        with self._writer_lock.acquire(
            f"plan-change-proposal:{proposal.proposal_id}"
        ):
            try:
                with self._connection:
                    self._connection.execute(
                        "INSERT INTO plan_change_proposal VALUES("
                        + ",".join("?" for _ in range(20))
                        + ")",
                        (
                            proposal.proposal_id,
                            proposal.revision,
                            (
                                None
                                if proposal.revision == 1
                                else proposal.revision - 1
                            ),
                            invocation_id,
                            request_hash,
                            proposal.status,
                            proposal.assessment_id,
                            proposal.base_plan_version_id,
                            proposal.base_graph_seal_hash,
                            self._json(
                                proposal.proposed_canonical_patch
                            ),
                            proposal.proposed_diff_hash,
                            proposal.created_by,
                            proposal.created_at,
                            proposal.updated_at,
                            proposal.accepted_draft_id,
                            proposal.content_hash,
                            proposal.schema_version,
                            (
                                None
                                if actor is None
                                else actor.decision_actor
                            ),
                            (
                                None
                                if actor is None
                                else actor.interaction_channel
                            ),
                            (
                                None
                                if actor is None
                                else actor.transport_actor
                            ),
                        ),
                    )
                    command_name = (
                        "plan_change_proposal.create@1"
                        if proposal.status == "open"
                        else (
                            "plan_change_proposal.accept@1"
                            if proposal.status == "accepted"
                            else "plan_change_proposal.reject@1"
                        )
                    )
                    self._insert_receipt(
                        invocation_id=invocation_id,
                        command_name=command_name,
                        request_hash=request_hash,
                        result_type="PlanChangeProposal",
                        aggregate_id=proposal.proposal_id,
                        revision_id=str(proposal.revision),
                        status=proposal.status,
                        decision_actor=actor.decision_actor,
                        interaction_channel=actor.interaction_channel,
                        transport_actor=actor.transport_actor,
                        created_at=proposal.updated_at,
                    )
            except sqlite3.IntegrityError as error:
                raise PlanImpactError(
                    "PROPOSAL_STORAGE_CONFLICT"
                ) from error
        return self.get_proposal(proposal.proposal_id)

    @staticmethod
    def _proposal(row: sqlite3.Row) -> PlanChangeProposal:
        proposal = PlanChangeProposal(
            proposal_id=row["proposal_id"],
            revision=row["revision"],
            status=row["status"],
            assessment_id=row["assessment_id"],
            base_plan_version_id=row["base_plan_version_id"],
            base_graph_seal_hash=row["base_graph_seal_hash"],
            proposed_canonical_patch=json.loads(
                row["proposed_canonical_patch_json"]
            ),
            proposed_diff_hash=row["proposed_diff_hash"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            accepted_draft_id=row["accepted_draft_id"],
            content_hash=row["content_hash"],
            schema_version=row["schema_version"],
        )
        proposal.validate()
        return proposal

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _insert_receipt(
        self,
        *,
        invocation_id: str,
        command_name: str,
        request_hash: str,
        result_type: str,
        aggregate_id: str,
        revision_id: str,
        status: str,
        decision_actor: str,
        interaction_channel: str,
        transport_actor: str,
        created_at: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO application_command_receipt VALUES("
            "?,?,?,?,?,?,?,?,?,?,?)",
            (
                invocation_id,
                command_name,
                request_hash,
                result_type,
                aggregate_id,
                revision_id,
                status,
                decision_actor,
                interaction_channel,
                transport_actor,
                created_at,
            ),
        )


__all__ = ["SQLitePlanImpactRepository"]
