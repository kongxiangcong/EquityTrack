import assert from "node:assert/strict"
import test from "node:test"

import {formatPercent, formatQuantity, methodSummary, persistedResearchHtml, researchViewLabel, selectResearchView} from "../src/research-view.js"

const view = {
  view_id: "research_view_1",
  html_projection: "<!doctype html><p>persisted canonical report</p>",
  subject_id: "002897.SZ",
  as_of: "2026-07-07",
  model_identity: "company-outlook-model@1",
  story: {
    what_happens: "<script>alert(1)</script>",
    why_it_matters: "利润与现金流传导",
    transmission: ["事件 → Driver → 财务 → 价值"],
    counterevidence: ["压力情景仍需观察"],
    what_would_change_the_view: ["关键 Driver 偏离阈值"],
  },
  key_drivers: [{label: "连接器需求", value: "120", unit: "units", period: "2030E"}],
  scenarios: [{role: "base", label: "基准", financials: [], methods: [{
    method_id: "fcff_dcf",
    value_basis: "enterprise_value",
    horizon: "valuation_as_of=2026-07-07",
    display_value_level: "per_share_value",
    conditional_value_range: {
      low: {value: "10", unit: "CNY/share"},
      base: {value: "12", unit: "CNY/share"},
      high: {value: "14", unit: "CNY/share"},
    },
    conditional_per_share_range: {
      low: {value: "10", unit: "CNY/share"},
      base: {value: "12", unit: "CNY/share"},
      high: {value: "14", unit: "CNY/share"},
    },
    display_diagnostics: ["终值占比较高。"],
  }]}],
  market_implied_expectations: [{scenario_label: "基准", base: {value: "0.03", unit: "decimal"}, explanation: "当前价格需要该假设成立。"}],
  valuation_simulation: {
    output_level: "per_share_value",
    converged: true,
    quantiles: {p50: {value: "12.5", unit: "CNY/share"}},
    contributions: [{assumption_id: "连接器需求", share: "0.6"}],
    assumptions: [{
      assumption_id: "连接器需求",
      family: "empirical",
      reference_value: "120",
      unit: "units",
      calibration: {
        sample_id: "<calibration>",
        window_start: "2021-01-01",
        window_end: "2025-12-31",
        available_at: "2026-01-02T00:00:00Z",
      },
    }],
    dependency_model: {model_identity: "<copula@1>", correlation_matrix: [["1"]]},
    deterministic_fallback: {
      scenario_id: "base",
      method_id: "fcff_dcf",
      formula_version: "fcff_dcf@3",
      low: "10",
      base: "12",
      high: "14",
      unit: "CNY/share",
    },
    diagnostics: ["<limited>"],
    rng_algorithm: "splitmix64_box_muller@1",
    seed: 7,
    sample_budget: 10000,
    invalid_path_rate: "0.01",
  },
  market_price_paths: {
    interpretation: "State-conditioned traded-price paths; not intrinsic value or a target price.",
    price_unit: "CNY/share",
    terminal_price_quantiles: {p50: {value: "11.8", unit: "CNY/share"}},
    horizon_return_quantiles: {p50: {value: "-0.02", unit: "decimal"}},
    maximum_drawdown_quantiles: {p50: {value: "-0.15", unit: "decimal"}},
    threshold_trigger_probabilities: [{threshold: "<95>", probability: "0.2"}],
    calibration: {series_identity: "<series@1>"},
    constraints: {policy_identity: "cn-a-share@1"},
    budget: {rng_algorithm: "splitmix64_state_block_bootstrap@1"},
    tail_results: {return_threshold: "-0.1", probability_below_threshold: "0.2"},
  },
  value_market_divergence: {
    explanation: "市场路径中位终点低于基本面价值分布中位数；背离不是确定性价格结论或交易动作。",
  },
  audit: {artifact_records: [], fact_evidence: [], formula_identities: []},
  boundary: "条件研究结果，不构成个性化投资建议。",
}

test("historical selection uses the persisted sandbox report without rebuilding semantics", () => {
  assert.equal(selectResearchView([view], "research_view_1"), view)
  assert.equal(selectResearchView([view], "missing"), null)
  const report = persistedResearchHtml(view)
  assert.equal(report, view.html_projection)
})

test("history labels distinguish policy and snapshot versions", () => {
  const first = {...view, policy_identity: "policy@1", model_data_snapshot_identity: "snapshot-aaaaaaaa"}
  const second = {...view, policy_identity: "policy@2", model_data_snapshot_identity: "snapshot-bbbbbbbb"}
  assert.notEqual(researchViewLabel(first, 0), researchViewLabel(second, 1))
  assert.match(researchViewLabel(second, 1), /policy@2/)
})

test("method summaries keep horizon, value basis, and material diagnostics beside the range", () => {
  const method = view.scenarios[0].methods[0]
  assert.equal(
    methodSummary(method),
    "fcff_dcf · 每股价值 10 CNY/share / 12 CNY/share / 14 CNY/share · 企业价值口径；股权桥完整时才继续转换 · 估值时点 2026-07-07 · 注意：终值占比较高。",
  )
})

test("enterprise-value methods are never labeled per-share", () => {
  const enterpriseMethod = {
    ...view.scenarios[0].methods[0],
    display_value_level: "basis_value",
    conditional_value_range: {
      low: {value: "100", unit: "CNY"},
      base: {value: "120", unit: "CNY"},
      high: {value: "140", unit: "CNY"},
    },
  }
  assert.match(methodSummary(enterpriseMethod), /企业价值 100 CNY \/ 120 CNY \/ 140 CNY/)
})

test("decision values are readable while exact decimals remain in the audit model", () => {
  assert.equal(formatQuantity({value: "62.674663221715583823", unit: "CNY/share"}), "62.67 CNY/share")
  assert.equal(formatQuantity({value: "2818.235945268702", unit: "CNY"}), "2,818.24 CNY")
  assert.equal(formatQuantity({value: "0.0523685046052668", unit: "decimal"}), "0.0524")
  assert.equal(formatPercent({value: "-0.4829895861353563", unit: "decimal"}), "-48.3%")
})
