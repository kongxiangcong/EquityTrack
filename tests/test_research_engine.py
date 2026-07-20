from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from equity_research import (  # noqa: E402
    ResearchEngine,
    ResearchRequest,
)
from trading_platform.domain.research_inputs import ResearchInputs  # noqa: E402


EXAMPLE = ROOT / "examples" / "yihua-002897"
DFD_EXAMPLE = ROOT / "examples" / "duofuduo-002407"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_stub(
    source_id: str,
    *,
    retrieved_at: str = "2026-07-07T09:00:00+08:00",
    report_date: str = "2026-07-07",
    extracted_fields: list[dict] | None = None,
) -> dict:
    return {
        "source_id": source_id,
        "tier": "secondary",
        "publisher": "Regression source",
        "title": f"Structured input source {source_id}",
        "url_or_api": f"https://example.invalid/{source_id}",
        "retrieved_at": retrieved_at,
        "report_date": report_date,
        "extracted_fields": extracted_fields or [],
        "cross_checks": [],
    }


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_float(item) for item in value)
    return False


class ResearchEngineBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = read_json(EXAMPLE / "source_manifest.json")
        self.estimates = read_json(EXAMPLE / "estimate_overlay.json")
        self.inputs_payload = read_json(EXAMPLE / "research_context.json")

    def test_yihua_completes_with_method_level_limits(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("completed_with_limits", run.status)
        self.assertEqual("ready", run.capabilities["research_core"].status)
        self.assertEqual("ready_with_estimates", run.capabilities["financial_model"].status)
        self.assertEqual("blocked", run.methods["dcf"].status)
        self.assertEqual("blocked", run.methods["peer_comps"].status)
        self.assertTrue(run.permissions["research_report"])
        self.assertTrue(run.permissions["conditional_research_plan"])
        self.assertFalse(run.permissions["formal_per_share_valuation"])

    def test_v3_yihua_builds_evidence_constrained_company_research(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual(3, run.schema_version)
        self.assertEqual("professional", run.report_mode)
        self.assertEqual(
            {
                "business",
                "industry",
                "fundamentals",
                "technical",
                "sentiment_events",
                "valuation",
                "governance_risk",
            },
            set(run.analysis.dimensions),
        )
        self.assertIsNotNone(run.debate)
        self.assertIsNotNone(run.synthesis)
        self.assertTrue(run.debate.bull.evidence_ids)
        self.assertTrue(run.debate.bear.evidence_ids)
        self.assertTrue(run.debate.resolved_disagreements)
        self.assertTrue(any(item["response_to"] for item in run.debate.bull.arguments))
        self.assertTrue(any(item["response_to"] for item in run.debate.bear.arguments))
        for dimension in run.analysis.dimensions.values():
            if dimension.status != "blocked":
                self.assertTrue(dimension.key_findings, dimension.dimension_id)
                self.assertTrue(dimension.counterpoints, dimension.dimension_id)
                self.assertTrue(dimension.uncertainties, dimension.dimension_id)

    def test_v3_downgrades_partial_or_estimate_only_narrative_support(self) -> None:
        partial_context = json.loads(json.dumps(self.inputs_payload, ensure_ascii=False))
        partial_context["analyses"]["business"]["evidence_fields"].append(
            "unknown_professional_field"
        )
        partial_context["analyses"]["business"]["key_metrics"].append(
            {"label": "无证据指标", "value": "99", "note": "不得进入报告"}
        )
        partial_run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(partial_context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("limited", partial_run.analysis.dimensions["business"].status)
        self.assertNotIn(
            "无证据指标",
            {item["label"] for item in partial_run.analysis.dimensions["business"].key_metrics},
        )

        estimate_context = json.loads(json.dumps(self.inputs_payload, ensure_ascii=False))
        estimate_context["analyses"]["business"]["evidence_fields"] = ["d_and_a"]
        estimate_run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(estimate_context),
                as_of_date="2026-07-07",
            )
        )
        self.assertEqual("limited", estimate_run.analysis.dimensions["business"].status)

    def test_v3_metrics_are_computed_and_free_form_numeric_claims_are_rejected(self) -> None:
        context = json.loads(json.dumps(self.inputs_payload, ensure_ascii=False))
        context["analyses"]["business"]["key_metrics"][0]["value"] = "9999 亿元"
        context["analyses"]["business"]["key_findings"].append("收入 8888 亿元")
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        metrics = run.analysis.dimensions["business"].key_metrics
        self.assertEqual("64.01 亿元", metrics[0]["value"])
        self.assertNotIn("9999", json.dumps(run.to_dict(), ensure_ascii=False))
        self.assertNotIn("8888", json.dumps(run.to_dict(), ensure_ascii=False))
        self.assertTrue(all(claim.evidence_ids for claim in run.analysis.dimensions["business"].key_findings))

    def test_v3_rejects_dangling_debate_responses(self) -> None:
        context = json.loads(json.dumps(self.inputs_payload, ensure_ascii=False))
        context["debate"]["bull"]["arguments"][2]["response_to"] = "BOGUS"
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertIsNone(run.debate)
        self.assertEqual("professional_limited", run.report_mode)

    def test_v3_rejects_unbound_numbers_across_all_narrative_paths(self) -> None:
        context = json.loads(json.dumps(self.inputs_payload, ensure_ascii=False))
        context["analyses"]["business"]["conclusion"] = "收入 9999 亿元"
        context["debate"]["bull"]["arguments"][0]["claim"] = "收入 8888 亿元"
        context["synthesis"]["core_thesis"] = "利润 7777 亿元"
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.analysis.dimensions["business"].status)
        self.assertIsNone(run.debate)
        self.assertIsNone(run.synthesis)
        payload = json.dumps(run.to_dict(), ensure_ascii=False)
        for value in ("9999", "8888", "7777"):
            self.assertNotIn(value, payload)

    def test_v3_metric_refs_require_exact_sources_and_compatible_units(self) -> None:
        context = json.loads(json.dumps(self.inputs_payload, ensure_ascii=False))
        invalid_source_metric = context["analyses"]["business"]["key_metrics"][0]
        invalid_source_metric["evidence_refs"][0]["source_id"] = "SRC_CNINFO_2026Q1"
        incompatible_metric = context["analyses"]["business"]["key_metrics"][1]
        incompatible_metric["display"] = "cny_per_share"
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual((), run.analysis.dimensions["business"].key_metrics)

    def test_v3_does_not_call_two_financial_fields_a_complete_report(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping({"report_version": 3, "company_type": "cyclical_manufacturing"}),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.capabilities["research_report"].status)
        self.assertFalse(run.permissions["research_report"])
        self.assertEqual("professional_limited", run.report_mode)

    def test_v3_duofuduo_runs_end_to_end_with_a_professional_narrative(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=read_json(DFD_EXAMPLE / "source_manifest.json"),
                research_inputs=ResearchInputs.from_mapping(read_json(DFD_EXAMPLE / "research_context.json")),
                as_of_date="2026-07-17",
            )
        )

        self.assertEqual("002407.SZ", run.company["ticker"])
        self.assertEqual("professional", run.report_mode)
        self.assertNotEqual("blocked", run.capabilities["research_core"].status)
        self.assertTrue(run.permissions["research_report"])
        self.assertIn("氟基新材料", run.analysis.dimensions["business"].conclusion)
        self.assertIn("经营现金流", run.analysis.dimensions["fundamentals"].conclusion)

    def test_estimates_never_become_official_facts(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        da_items = [item for item in run.evidence if item.field_name == "d_and_a"]
        self.assertEqual(1, len(da_items))
        self.assertTrue(da_items[0].estimated)
        self.assertFalse(da_items[0].official)
        self.assertIn("d_and_a", run.capabilities["financial_model"].estimated_fields)
        self.assertIn("d_and_a", run.capabilities["dcf"].estimated_fields)

    def test_manifest_estimate_tier_never_counts_as_sourced_market_data(self) -> None:
        self.manifest["sources"] = [
            source
            for source in self.manifest["sources"]
            if source["source_id"] != "SRC_MARKET_YAHOO_20260707"
        ]
        self.manifest["sources"].append(
            {
                "source_id": "SRC_ESTIMATE_PRICE",
                "tier": "estimate",
                "publisher": "Explicit estimate",
                "title": "Scenario price input",
                "url_or_api": "https://example.invalid/estimate",
                "retrieved_at": "2026-07-07T09:00:00+08:00",
                "report_date": "2026-07-07",
                "extracted_fields": [
                    {
                        "field_name": "current_price",
                        "period": "2026-07-07",
                        "value": 88.0,
                        "unit": "CNY/share",
                        "currency": "CNY",
                        "extraction_method": "scenario_input",
                        "confidence": "low",
                        "basis_sources": ["SRC_CNINFO_2026Q1"],
                    }
                ],
                "cross_checks": [],
            }
        )

        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        price = next(item for item in run.evidence if item.source_id == "SRC_ESTIMATE_PRICE")
        self.assertTrue(price.estimated)
        self.assertFalse(price.official)
        self.assertIn("current_price", run.capabilities["per_share_context"].missing_fields)

    def test_non_numeric_financial_fact_fails_integrity(self) -> None:
        self.manifest["sources"][0]["extracted_fields"][0]["value"] = "N/A"
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.status)
        self.assertIn("FIELD_VALUE_NOT_NUMERIC", {issue.code for issue in run.integrity_issues})

    def test_cross_subject_facts_never_satisfy_target_capabilities(self) -> None:
        for source in self.manifest["sources"]:
            source["extracted_fields"] = [
                field
                for field in source["extracted_fields"]
                if field["field_name"] != "revenue"
            ]
        peer_source = source_stub(
            "PEER_OFFICIAL",
            report_date="2026-04-29",
            extracted_fields=[
                {
                    "field_name": "revenue",
                    "subject_id": "PEER.X",
                    "semantic_role": "revenue",
                    "period": "2026Q1",
                    "value": 999_000_000.0,
                    "unit": "CNY",
                    "currency": "CNY",
                    "extraction_method": "peer_filing",
                    "confidence": "high",
                }
            ],
        )
        peer_source["tier"] = "official"
        self.manifest["sources"].append(peer_source)

        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.capabilities["research_core"].status)
        self.assertIn("revenue", run.capabilities["research_core"].missing_fields)

    def test_invalid_manifest_blocks_the_run_at_the_integrity_seam(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest={"source_manifest_version": 2, "company": {}, "sources": []},
                research_inputs=ResearchInputs(),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.status)
        self.assertFalse(run.permissions["research_report"])
        self.assertGreater(len(run.integrity_issues), 0)

    def test_dcf_uses_only_an_explicit_case_and_matches_worked_example(self) -> None:
        fields = [
            ("revenue", 1000.0),
            ("net_income", 80.0),
            ("cfo", 120.0),
            ("ebit", 130.0),
            ("tax", 25.0),
            ("d_and_a", 30.0),
            ("capex", 40.0),
            ("working_capital", 150.0),
            ("cash", 50.0),
            ("debt", 20.0),
            ("lease_debt", 0.0),
            ("minority_interest", 0.0),
            ("preferred_stock", 0.0),
            ("pension_deficit", 0.0),
            ("non_operating_assets", 0.0),
            ("associates_jv_value", 0.0),
            ("diluted_shares", 10.0),
            ("eps", 8.0),
            ("current_price", 100.0),
        ]
        manifest = {
            "source_manifest_version": 2,
            "company": {
                "name": "Worked Example Co",
                "ticker": "TEST",
                "market": "US",
                "reporting_currency": "USD",
                "trading_currency": "USD",
                "accounting_standard": "US GAAP",
                "latest_financial_period": "2025FY",
            },
            "sources": [
                {
                    "source_id": "SRC_OFFICIAL",
                    "tier": "official",
                    "publisher": "Company IR",
                    "title": "Worked example filing",
                    "url_or_api": "https://example.invalid/filing",
                    "retrieved_at": "2026-01-01T00:00:00Z",
                    "report_date": "2026-01-01",
                    "extracted_fields": [
                        {
                            "field_name": name,
                            "period": "2025FY",
                            "value": value,
                            "unit": "USD" if name != "diluted_shares" else "shares",
                            "currency": "USD",
                            "extraction_method": "worked_example",
                            "confidence": "high",
                        }
                        for name, value in fields
                    ]
                    + [
                        {
                            "field_name": name,
                            "subject_id": "TEST",
                            "semantic_role": {
                                "dcf_fcff": "dcf_forecast_fcff",
                                "terminal_growth": "dcf_terminal_growth",
                                "risk_free_rate": "wacc:risk_free_rate",
                                "equity_risk_premium": "wacc:equity_risk_premium",
                                "beta": "wacc:beta",
                                "pre_tax_cost_of_debt": "wacc:pre_tax_cost_of_debt",
                                "wacc_tax_rate": "wacc:tax_rate",
                                "equity_weight": "wacc:equity_weight",
                                "debt_weight": "wacc:debt_weight",
                            }[name],
                            "period": period,
                            "value": value,
                            "unit": unit,
                            "currency": "USD" if name == "dcf_fcff" else "N/A",
                            "extraction_method": "worked_assumption_evidence",
                            "confidence": "high",
                        }
                        for name, period, value, unit in (
                            ("dcf_fcff", "2026E", 100.0, "USD"),
                            ("dcf_fcff", "2027E", 110.0, "USD"),
                            ("terminal_growth", "terminal", 0.03, "decimal"),
                            ("risk_free_rate", "2026-01-01", 0.04, "decimal"),
                            ("equity_risk_premium", "2026-01-01", 0.07375, "decimal"),
                            ("beta", "2026-01-01", 1.0, "x"),
                            ("pre_tax_cost_of_debt", "2026-01-01", 0.06, "decimal"),
                            ("wacc_tax_rate", "2026-01-01", 0.25, "decimal"),
                            ("equity_weight", "2026-01-01", 0.80, "decimal"),
                            ("debt_weight", "2026-01-01", 0.20, "decimal"),
                        )
                    ],
                    "cross_checks": [],
                }
            ],
            "missing_critical_data": [],
        }
        context = {
            "company_type": "general",
            "peer_count": 0,
            "dcf_case": {
                "wacc": 0.10,
                "forecast_evidence_refs": [
                    {"source_id": "SRC_OFFICIAL", "field_name": "dcf_fcff", "period": "2026E"},
                    {"source_id": "SRC_OFFICIAL", "field_name": "dcf_fcff", "period": "2027E"},
                ],
                "terminal_growth_evidence_ref": {
                    "source_id": "SRC_OFFICIAL",
                    "field_name": "terminal_growth",
                    "period": "terminal",
                },
                "wacc_component_evidence_refs": {
                    "risk_free_rate": {"source_id": "SRC_OFFICIAL", "field_name": "risk_free_rate", "period": "2026-01-01"},
                    "equity_risk_premium": {"source_id": "SRC_OFFICIAL", "field_name": "equity_risk_premium", "period": "2026-01-01"},
                    "beta": {"source_id": "SRC_OFFICIAL", "field_name": "beta", "period": "2026-01-01"},
                    "pre_tax_cost_of_debt": {"source_id": "SRC_OFFICIAL", "field_name": "pre_tax_cost_of_debt", "period": "2026-01-01"},
                    "tax_rate": {"source_id": "SRC_OFFICIAL", "field_name": "wacc_tax_rate", "period": "2026-01-01"},
                    "equity_weight": {"source_id": "SRC_OFFICIAL", "field_name": "equity_weight", "period": "2026-01-01"},
                    "debt_weight": {"source_id": "SRC_OFFICIAL", "field_name": "debt_weight", "period": "2026-01-01"},
                },
                "currency": "USD",
                "forecast_unit_scale": 1.0,
            },
        }

        run = ResearchEngine().run(
            ResearchRequest(
                manifest=manifest,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-01-01",
            )
        )

        dcf = run.methods["dcf"]
        self.assertEqual("ready", dcf.status)
        self.assertAlmostEqual(1519.48051948, dcf.metrics["enterprise_value"], places=6)
        self.assertAlmostEqual(154.948051948, dcf.metrics["equity_value_per_share"], places=6)
        self.assertEqual(25, len(dcf.metrics["sensitivity"]))
        exact_calculation = dcf.metrics["exact_calculation"]
        self.assertTrue(exact_calculation["enterprise_value"].startswith("1519.4805194805"))
        self.assertTrue(exact_calculation["per_share_value"].startswith("154.9480519480"))
        self.assertFalse(_contains_float(exact_calculation))
        self.assertEqual(
            "USD",
            exact_calculation["dimensioned_inputs"]["forecast_fcff"][0]["unit"],
        )
        self.assertEqual(
            "shares",
            exact_calculation["dimensioned_inputs"]["equity_bridge"]["diluted_shares"]["unit"],
        )
        forecast_ref = exact_calculation["dimensioned_inputs"]["forecast_fcff"][0][
            "provenance_refs"
        ][0]
        self.assertTrue(forecast_ref.startswith("Assumption:"))
        self.assertNotIn(
            f"Fact:{forecast_ref.removeprefix('Assumption:')}",
            json.dumps(exact_calculation),
        )
        public_dcf = run.to_dict()["methods"]["dcf"]["metrics"]
        self.assertNotIn("equity_value_per_share", public_dcf)
        self.assertNotIn("sensitivity", public_dcf)
        self.assertNotIn("exact_calculation", public_dcf)
        self.assertFalse(_contains_float(public_dcf))

        mismatched_manifest = json.loads(json.dumps(manifest))
        for field in mismatched_manifest["sources"][0]["extracted_fields"]:
            if field["field_name"] == "dcf_fcff":
                field["currency"] = "CNY"
        mismatched = ResearchEngine().run(
            ResearchRequest(
                manifest=mismatched_manifest,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-01-01",
            )
        )
        self.assertEqual("blocked", mismatched.methods["dcf"].status)

        cross_period_manifest = json.loads(json.dumps(manifest))
        for field in cross_period_manifest["sources"][0]["extracted_fields"]:
            if field["field_name"] == "debt":
                field["period"] = "2024FY"
        cross_period = ResearchEngine().run(
            ResearchRequest(
                manifest=cross_period_manifest,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-01-01",
            )
        )
        self.assertEqual("blocked", cross_period.methods["dcf"].status)
        self.assertTrue(
            cross_period.methods["dcf"].diagnostics[0].startswith(
                "FINANCIAL_PERIOD_MISMATCH:"
            )
        )

        invalid_share_unit_manifest = json.loads(json.dumps(manifest))
        for field in invalid_share_unit_manifest["sources"][0]["extracted_fields"]:
            if field["field_name"] == "diluted_shares":
                field["unit"] = "USD"
        invalid_share_unit = ResearchEngine().run(
            ResearchRequest(
                manifest=invalid_share_unit_manifest,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-01-01",
            )
        )
        self.assertEqual("blocked", invalid_share_unit.methods["dcf"].status)
        self.assertTrue(
            invalid_share_unit.methods["dcf"].diagnostics[0].startswith(
                "FINANCIAL_UNIT_SCALE_MISMATCH:"
            )
        )

        scaled_manifest = json.loads(json.dumps(manifest))
        for field in scaled_manifest["sources"][0]["extracted_fields"]:
            if field["field_name"] == "dcf_fcff":
                field["unit"] = "USD million"
            elif field["field_name"] in {
                "cash",
                "debt",
                "lease_debt",
                "minority_interest",
                "preferred_stock",
                "pension_deficit",
                "non_operating_assets",
                "associates_jv_value",
            }:
                field["unit"] = "USD million"
            elif field["field_name"] == "diluted_shares":
                field["unit"] = "million shares"
        scaled_context = json.loads(json.dumps(context))
        scaled_context["dcf_case"]["forecast_unit_scale"] = 1_000_000
        scaled = ResearchEngine().run(
            ResearchRequest(
                manifest=scaled_manifest,
                research_inputs=ResearchInputs.from_mapping(scaled_context),
                as_of_date="2026-01-01",
            )
        )
        self.assertEqual("ready", scaled.methods["dcf"].status)
        self.assertAlmostEqual(
            1_519_480_519.4805195,
            scaled.methods["dcf"].metrics["enterprise_value"],
            places=4,
        )
        self.assertAlmostEqual(
            154.948051948,
            scaled.methods["dcf"].metrics["equity_value_per_share"],
            places=6,
        )
        self.assertAlmostEqual(
            scaled.methods["dcf"].metrics["equity_value_per_share"],
            scaled.methods["dcf"].metrics["sensitivity"][12]["equity_value_per_share"],
            places=6,
        )

    def test_dcf_missing_equity_bridge_is_method_blocking_not_zero(self) -> None:
        context = dict(self.inputs_payload)
        context["company_type"] = "general"
        context["dcf_case"] = {
            "forecast_fcff": [100_000_000.0, 110_000_000.0],
            "wacc": 0.10,
            "terminal_growth": 0.03,
            "wacc_components": {
                "risk_free_rate": 0.04,
                "equity_risk_premium": 0.07375,
                "beta": 1.0,
                "pre_tax_cost_of_debt": 0.06,
                "tax_rate": 0.25,
                "equity_weight": 0.80,
                "debt_weight": 0.20,
            },
            "currency": "CNY",
            "forecast_unit_scale": 1.0,
            "source_ids": ["SRC_CNINFO_2026Q1"],
        }
        for source in self.manifest["sources"]:
            source["extracted_fields"] = [
                field
                for field in source["extracted_fields"]
                if field["field_name"] != "minority_interest"
            ]

        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.methods["dcf"].status)
        self.assertIn("minority_interest", run.capabilities["dcf"].missing_fields)
        self.assertFalse(run.methods["dcf"].metrics)

    def test_peer_and_historical_methods_use_explicit_structured_cases(self) -> None:
        peer_values = {
            "P1": ("PEER1", 40.0),
            "P2": ("PEER2", 50.0),
            "P3": ("PEER3", 60.0),
        }
        self.manifest["sources"].extend(
            source_stub(
                source_id,
                report_date="2025-12-31",
                extracted_fields=[
                    {
                        "field_name": "peer_pe",
                        "subject_id": ticker,
                        "semantic_role": "peer_multiple:pe",
                        "period": "2025FY",
                        "value": value,
                        "unit": "x",
                        "currency": "N/A",
                        "extraction_method": "structured_peer_input",
                        "confidence": "high",
                    }
                ],
            )
            for source_id, (ticker, value) in peer_values.items()
        )
        self.manifest["sources"].append(
            source_stub(
                "HIST",
                report_date="2025-12-31",
                extracted_fields=[
                    {
                        "field_name": "historical_pe",
                        "subject_id": "002897.SZ",
                        "semantic_role": "historical_multiple:pe",
                        "period": f"2025-{month:02d}-28",
                        "value": (
                            f"{28 + month * 2}.000000000000000001"
                            if month in {6, 7}
                            else float(28 + month * 2)
                        ),
                        "unit": "x",
                        "currency": "N/A",
                        "extraction_method": "structured_historical_input",
                        "confidence": "high",
                    }
                    for month in range(1, 13)
                ],
            )
        )
        ebitda_source = source_stub(
            "EBITDA",
            report_date="2025-12-31",
            extracted_fields=[
                {
                    "field_name": "ebitda",
                    "period": "2025FY",
                    "value": 500_000_000.0,
                    "unit": "CNY",
                    "currency": "CNY",
                    "extraction_method": "worked_example",
                    "confidence": "high",
                }
            ],
        )
        ebitda_source["tier"] = "official"
        self.manifest["sources"].append(ebitda_source)
        self.manifest["sources"].extend(
            source_stub(
                f"EV{index}",
                report_date="2025-12-31",
                extracted_fields=[
                    {
                        "field_name": "peer_ev_ebitda",
                        "subject_id": f"EVPEER{index}",
                        "semantic_role": "peer_multiple:ev_ebitda",
                        "period": "2025FY",
                        "value": float(4 + index),
                        "unit": "x",
                        "currency": "N/A",
                        "extraction_method": "structured_peer_input",
                        "confidence": "high",
                    }
                ],
            )
            for index in range(1, 4)
        )
        self.manifest["sources"].extend(
            source_stub(
                f"PS{index}",
                report_date="2025-12-31",
                extracted_fields=[
                    {
                        "field_name": "peer_ps",
                        "subject_id": f"PSPEER{index}",
                        "semantic_role": "peer_multiple:ps",
                        "period": "2025FY",
                        "value": float(index),
                        "unit": "x",
                        "currency": "N/A",
                        "extraction_method": "structured_peer_input",
                        "confidence": "high",
                    }
                ],
            )
            for index in range(1, 4)
        )
        context = dict(self.inputs_payload)
        context["peer_count"] = 3
        context["peer_case"] = {
            "metric": "pe",
            "company_metric_field": "eps",
            "peers": [
                {"ticker": "PEER1", "usable": True, "period": "2025FY", "currency_checked": True, "accounting_checked": True, "evidence_ref": {"source_id": "P1", "field_name": "peer_pe", "period": "2025FY"}},
                {"ticker": "PEER2", "usable": True, "period": "2025FY", "currency_checked": True, "accounting_checked": True, "evidence_ref": {"source_id": "P2", "field_name": "peer_pe", "period": "2025FY"}},
                {"ticker": "PEER3", "usable": True, "period": "2025FY", "currency_checked": True, "accounting_checked": True, "evidence_ref": {"source_id": "P3", "field_name": "peer_pe", "period": "2025FY"}},
            ],
        }
        context["historical_multiples"] = [
            {"date": f"2025-{month:02d}-28", "evidence_ref": {"source_id": "HIST", "field_name": "historical_pe", "period": f"2025-{month:02d}-28"}}
            for month in range(1, 13)
        ]

        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        peer = run.methods["peer_comps"]
        historical = run.methods["historical_band"]
        self.assertEqual("ready", peer.status)
        self.assertAlmostEqual(50.0, peer.metrics["peer_median_multiple"])
        self.assertAlmostEqual(81.5, peer.metrics["implied_per_share_median"])
        self.assertEqual("81.5", peer.metrics["exact_calculation"]["implied_per_share_median"])
        self.assertFalse(_contains_float(peer.metrics["exact_calculation"]))
        self.assertEqual(
            4,
            len(peer.metrics["exact_calculation"]["provenance_refs"]),
        )
        self.assertEqual("ready", historical.status)
        self.assertAlmostEqual(41.0, historical.metrics["median"])
        self.assertEqual(
            "41.000000000000000001",
            historical.metrics["exact_calculation"]["median"],
        )
        self.assertFalse(_contains_float(historical.metrics["exact_calculation"]))
        self.assertEqual(
            12,
            len(historical.metrics["exact_calculation"]["dimensioned_inputs"]),
        )
        self.assertEqual(12, historical.metrics["observations"])
        self.assertTrue(run.permissions["formal_per_share_valuation"])
        self.assertGreaterEqual(len(peer.evidence_ids), 4)
        self.assertGreaterEqual(len(historical.evidence_ids), 13)
        self.assertIn("minimum_peer_count", peer.assumptions)
        self.assertIn("as_of_date", historical.assumptions)
        public_methods = run.to_dict()["methods"]
        self.assertFalse(_contains_float(public_methods["peer_comps"]["metrics"]))
        self.assertFalse(_contains_float(public_methods["historical_band"]["metrics"]))

        duplicated_context = dict(context)
        duplicated_context["peer_case"] = dict(context["peer_case"])
        duplicated_context["peer_case"]["peers"] = [
            {
                **peer_input,
                "evidence_ref": context["peer_case"]["peers"][0]["evidence_ref"],
            }
            for peer_input in context["peer_case"]["peers"]
        ]
        duplicated = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(duplicated_context),
                as_of_date="2026-07-07",
            )
        )
        self.assertEqual("blocked", duplicated.methods["peer_comps"].status)

        invalid_dimension_manifest = json.loads(json.dumps(self.manifest))
        for source in invalid_dimension_manifest["sources"]:
            if source["source_id"] == "P1":
                source["extracted_fields"][0]["unit"] = "CNY"
        invalid_dimension = ResearchEngine().run(
            ResearchRequest(
                manifest=invalid_dimension_manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )
        self.assertEqual("blocked", invalid_dimension.methods["peer_comps"].status)
        self.assertTrue(
            invalid_dimension.methods["peer_comps"].diagnostics[0].startswith(
                "FINANCIAL_MULTIPLE_DIMENSION_MISMATCH:"
            )
        )

        ps_context = dict(self.inputs_payload)
        ps_context["peer_count"] = 3
        ps_context["peer_case"] = {
            "metric": "ps",
            "company_metric_field": "revenue",
            "peers": [
                {
                    "ticker": f"PSPEER{index}",
                    "usable": True,
                    "period": "2025FY",
                    "currency_checked": True,
                    "accounting_checked": True,
                    "evidence_ref": {
                        "source_id": f"PS{index}",
                        "field_name": "peer_ps",
                        "period": "2025FY",
                    },
                }
                for index in range(1, 4)
            ],
        }
        ps_run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(ps_context),
                as_of_date="2026-07-07",
            )
        )
        self.assertEqual("blocked", ps_run.methods["peer_comps"].status)
        self.assertTrue(
            ps_run.methods["peer_comps"].diagnostics[0].startswith(
                "FINANCIAL_PERIOD_MISMATCH:"
            )
        )

        ev_context = dict(self.inputs_payload)
        ev_context["peer_count"] = 3
        ev_context["peer_case"] = {
            "metric": "ev_ebitda",
            "company_metric_field": "ebitda",
            "peers": [
                {
                    "ticker": f"EVPEER{index}",
                    "usable": True,
                    "period": "2025FY",
                    "currency_checked": True,
                    "accounting_checked": True,
                    "evidence_ref": {
                        "source_id": f"EV{index}",
                        "field_name": "peer_ev_ebitda",
                        "period": "2025FY",
                    },
                }
                for index in range(1, 4)
            ],
        }
        ev_run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(ev_context),
                as_of_date="2026-07-07",
            )
        )
        ev_peer = ev_run.methods["peer_comps"]
        self.assertEqual("ready", ev_peer.status)
        self.assertTrue(
            ev_peer.metrics["exact_calculation"]["implied_per_share_median"].startswith(
                "8.2880314463"
            )
        )
        operations = {
            step["operation"]
            for step in ev_peer.metrics["exact_calculation"]["median_trace"]
        }
        self.assertIn("subtract_lease_debt", operations)
        self.assertIn("add_associates_jv_value", operations)
        self.assertIn("add_non_operating_assets", operations)
        self.assertEqual(
            "CNY",
            ev_peer.metrics["exact_calculation"]["dimensioned_inputs"]["equity_bridge"]["lease_debt"]["unit"],
        )

    def test_context_numbers_cannot_use_unknown_source_ids(self) -> None:
        context = dict(self.inputs_payload)
        context["peer_case"] = {
            "metric": "pe",
            "company_metric_field": "eps",
            "peers": [
                {"ticker": f"P{index}", "period": "2025FY", "currency_checked": True, "accounting_checked": True, "evidence_ref": {"source_id": "FAKE", "field_name": "peer_pe", "period": "2025FY"}}
                for index in range(3)
            ],
        }
        context["historical_multiples"] = [
            {"date": f"2025-{index + 1:02d}-28", "evidence_ref": {"source_id": "FAKE", "field_name": "historical_pe", "period": f"2025-{index + 1:02d}-28"}}
            for index in range(12)
        ]

        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.methods["peer_comps"].status)
        self.assertEqual("blocked", run.methods["historical_band"].status)
        self.assertFalse(run.permissions["formal_per_share_valuation"])

    def test_estimate_tier_cannot_unlock_peer_valuation(self) -> None:
        peers = []
        for index in range(3):
            source_id = f"EST_PEER_{index}"
            source = source_stub(
                source_id,
                extracted_fields=[
                    {
                        "field_name": "peer_pe",
                        "subject_id": f"P{index}",
                        "semantic_role": "peer_multiple:pe",
                        "period": "2025FY",
                        "value": 40.0 + index,
                        "unit": "x",
                        "currency": "N/A",
                        "extraction_method": "estimate_only",
                        "confidence": "low",
                        "basis_sources": ["SRC_CNINFO_2025AR"],
                    }
                ],
            )
            source["tier"] = "estimate"
            self.manifest["sources"].append(source)
            peers.append(
                {
                    "ticker": f"P{index}",
                    "period": "2025FY",
                    "currency_checked": True,
                    "accounting_checked": True,
                    "evidence_ref": {
                        "source_id": source_id,
                        "field_name": "peer_pe",
                        "period": "2025FY",
                    },
                }
            )
        context = dict(self.inputs_payload)
        context["peer_case"] = {"metric": "pe", "peers": peers}

        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.methods["peer_comps"].status)
        self.assertFalse(run.permissions["formal_per_share_valuation"])

    def test_as_of_date_rejects_future_sources(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2020-01-01",
            )
        )

        self.assertEqual("blocked", run.status)
        self.assertIn("SOURCE_NOT_AVAILABLE_AS_OF", {issue.code for issue in run.integrity_issues})

    def test_source_retrieval_timestamp_is_required_but_may_follow_as_of(self) -> None:
        for source in self.manifest["sources"]:
            source["retrieved_at"] = ""
        missing_timestamp = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )
        self.assertEqual("blocked", missing_timestamp.status)
        self.assertIn(
            "SOURCE_RETRIEVED_AT_MISSING",
            {issue.code for issue in missing_timestamp.integrity_issues},
        )

        self.manifest = read_json(EXAMPLE / "source_manifest.json")
        for source in self.manifest["sources"]:
            source["retrieved_at"] = "2027-01-01T00:00:00Z"
        historical_download = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )
        self.assertEqual("completed_with_limits", historical_download.status)

    def test_integrity_errors_fail_closed_before_valuation_rendering(self) -> None:
        context = dict(self.inputs_payload)
        self.manifest["sources"].append(dict(self.manifest["sources"][0]))
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("blocked", run.status)
        self.assertTrue(all(method.status == "blocked" for method in run.methods.values()))
        self.assertTrue(all(not method.metrics for method in run.methods.values()))
        self.assertEqual("audit_memo", run.report_mode)
        self.assertEqual({}, run.analysis.dimensions)
        self.assertIsNone(run.debate)
        self.assertIsNone(run.synthesis)

    def test_default_output_normalizes_prohibited_action_language(self) -> None:
        context = json.loads(json.dumps(self.inputs_payload, ensure_ascii=False))
        context["executive_summary"] = "ADD评级，建议增仓；BUY评级 / 买入 / 目标价 100"
        context["theses"] = [
            {
                "title": "SELL / OUTPERFORM / UNDERWEIGHT",
                "detail": "评级增持，推荐，建议回避，卖出并持有",
                "rating": "BUY",
                "instruction": "建议买入",
                "evidence_fields": [],
            }
        ]
        context["analyses"]["business"]["conclusion"] = "BUY / 买入 / 目标价 100"
        context["analyses"]["business"]["key_findings"][0]["text"] = "BUY评级"
        context["analyses"]["technical"]["key_metrics"][0]["value"] = "SELL / 卖出"
        context["analyses"]["technical"]["key_metrics"][0]["note"] = "HOLD / 持有"
        context["analyses"]["technical"]["key_metrics"][0]["label"] = "BUY评级"
        context["debate"]["bull"]["arguments"][0]["claim"] = "建议增仓并买入"
        context["synthesis"]["core_thesis"] = "OUTPERFORM / BUY / 目标价 100"
        self.manifest["missing_critical_data"][0]["missing_reason"] = "建议买入并加仓"
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        payload = json.dumps(run.to_dict(), ensure_ascii=False)
        for prohibited in (
            "BUY",
            "HOLD",
            "SELL",
            "OUTPERFORM",
            "UNDERWEIGHT",
            "ADD",
            "买入",
            "卖出",
            "持有",
            "增持",
            "增仓",
            "推荐",
            "回避",
            "评级",
            "目标价",
        ):
            self.assertNotIn(prohibited, payload)
        self.assertIn("OUTPUT_LANGUAGE_NORMALIZED", {issue.code for issue in run.integrity_issues})

    def test_conditional_plan_capability_matches_auto_generated_plan(self) -> None:
        context = dict(self.inputs_payload)
        context.pop("conditional_plan", None)
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("ready", run.capabilities["conditional_research_plan"].status)
        self.assertTrue(run.permissions["conditional_research_plan"])
        self.assertGreater(len(run.conditional_plan), 0)

    def test_mid_cycle_placeholder_never_reports_ready(self) -> None:
        context = dict(self.inputs_payload)
        context["company_type"] = "cyclical_manufacturing"
        context["mid_cycle_case"] = {"revenue": 100.0}
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(context),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("limited", run.methods["mid_cycle"].status)

    def test_scenarios_are_hidden_when_scenario_permission_is_false(self) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        self.assertFalse(run.permissions["scenario_analysis"])
        self.assertEqual([], run.summary["scenarios"])

    def test_typed_input_schema_is_canonical(
        self,
    ) -> None:
        inputs = ResearchInputs.from_mapping(self.inputs_payload)
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs.from_mapping(self.inputs_payload),
                as_of_date="2026-07-07",
            )
        )

        self.assertEqual("ResearchInputs@1", inputs.schema_version)

    def test_typed_research_inputs_normalize_action_language(
        self,
    ) -> None:
        run = ResearchEngine().run(
            ResearchRequest(
                manifest=self.manifest,
                estimates=self.estimates,
                research_inputs=ResearchInputs(
                    executive_summary="BUY / 买入 / 目标价 100",
                ),
                as_of_date="2026-07-07",
            )
        )

        self.assertNotIn("BUY", run.summary["executive_summary"])
        self.assertNotIn("买入", run.summary["executive_summary"])
        self.assertNotIn("目标价", run.summary["executive_summary"])


if __name__ == "__main__":
    unittest.main()
