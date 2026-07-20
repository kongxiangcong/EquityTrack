from __future__ import annotations

import json

from trading_platform.application.workflow_ledger import (
    ResearchDecisionBytes,
    ResearchDecisionMaterialization,
)
from trading_platform.research_presentation import render_research_decision_html
from trading_platform.research_view import (
    ResearchDecisionInput,
    ResearchDecisionView,
    ResearchDecisionViewBuilder,
    ResearchViewError,
)
from trading_platform.application.research_request_codec import (
    decode_research_workflow_request,
)


class CanonicalResearchDecisionViewMaterializer:
    """Owns canonical DecisionView decoding, construction, and HTML projection."""

    def materialize(
        self, request: ResearchDecisionMaterialization
    ) -> ResearchDecisionBytes:
        workflow_request = decode_research_workflow_request(request.request_bytes)
        by_kind = {item.artifact_kind: item for item in request.artifacts}
        if not {"DataSnapshot", "Forecast", "Valuation"}.issubset(by_kind):
            raise ResearchViewError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                "Frozen typed decision inputs are incomplete.",
            )
        view = ResearchDecisionViewBuilder().build(
            ResearchDecisionInput(
                workflow_run_id=request.workflow_run_id,
                data_snapshot=by_kind["DataSnapshot"],
                forecast=by_kind["Forecast"],
                valuation=by_kind["Valuation"],
                research_run_payload=request.source_payload,
                projection=workflow_request.projection,
                trusted_source_validation=(
                    workflow_request.projection.source_manifest_validation_result
                ),
                simulation=by_kind.get("Simulation"),
                market_data_snapshot=by_kind.get("MarketDataSnapshot"),
                market_path=by_kind.get("MarketPathSimulation"),
            )
        )
        json_bytes = json.dumps(
            view.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return ResearchDecisionBytes(
            json_bytes=json_bytes,
            html_bytes=render_research_decision_html(view).encode(),
        )

    def expected_html(
        self,
        workflow_run_id: str,
        research_run_id: str,
        json_bytes: bytes,
    ) -> bytes:
        try:
            decoded = json.loads(json_bytes)
            view = ResearchDecisionView.from_dict(decoded)
        except (json.JSONDecodeError, ResearchViewError) as error:
            raise ResearchViewError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                "Existing decision view is invalid.",
            ) from error
        if (
            view.workflow_run_id != workflow_run_id
            or view.research_run_id != research_run_id
        ):
            raise ResearchViewError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                "Existing decision view identity is invalid.",
            )
        return render_research_decision_html(view).encode()
