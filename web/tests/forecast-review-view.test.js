import assert from "node:assert/strict"
import test from "node:test"

import {
  forecastReviewSummary,
  registrySummary,
} from "../src/forecast-review-view.js"

test("forecast registry distinguishes registered, due, and reviewed items", () => {
  assert.match(registrySummary({
    label: "收入",
    horizon: "2026E",
    review_date: "2027-03-20",
    review_status: "due",
  }), /到期待复核/)
  assert.match(registrySummary({
    target_id: "revenue",
    review_status: "reviewed",
  }), /已复核/)
})

test("review history shows coverage and version without claiming model validity", () => {
  const summary = forecastReviewSummary({
    reviewed_at: "2027-03-21T09:00:00+08:00",
    status: "partial",
    numeric_interval_coverage: "0.5",
    numeric_results: [
      {absolute_error: "8"},
      {absolute_error: null},
    ],
    calibration_version: {new_model_identity: "company-outlook-model@2"},
  })
  assert.match(summary, /可比数值项 1/)
  assert.match(summary, /区间覆盖率 50.0%/)
  assert.match(summary, /company-outlook-model@2/)
  assert.doesNotMatch(summary, /有效|命中证明/)
})
