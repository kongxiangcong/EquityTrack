import fs from "node:fs/promises";
import process from "node:process";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("usage: render_valuation_xlsx.mjs <view.json> <output.xlsx> [preview.png]");
}
const view = JSON.parse(await fs.readFile(inputPath, "utf8"));
if (view.schema_version !== "ResearchDecisionView@2") {
  throw new Error("VALUATION_WORKBOOK_VIEW_INVALID");
}

const workbook = Workbook.create();
let modelIdentitySummary = view.model_identity;
try {
  const parsedIdentity = JSON.parse(view.model_identity);
  modelIdentitySummary =
    parsedIdentity.model_policy_hash
    || parsedIdentity.workflow_hash
    || view.model_identity;
} catch {
  // A non-JSON identity is already a concise, typed display value.
}
const summary = workbook.worksheets.add("Summary");
const imported = workbook.worksheets.add("Canonical Inputs");
const bridge = workbook.worksheets.add("Bridge Trace");
const reconciliation = workbook.worksheets.add("Reconciliation");
const audit = workbook.worksheets.add("Sources Audit");
const checks = workbook.worksheets.add("Checks");
for (const sheet of [summary, imported, bridge, reconciliation, audit, checks]) {
  sheet.showGridLines = false;
}

const methodRows = [];
const bridgeRows = [];
for (const scenario of view.scenarios || []) {
  for (const method of scenario.methods || []) {
    const range = method.conditional_value_range;
    if (method.status !== "ready" || !range) continue;
    const rawScenario = (view.audit?.parameters || []).find(
      (item) => item.scenario_id === scenario.scenario_id && item.method_id === method.method_id,
    );
    for (const point of ["low", "base", "high"]) {
      const sourcePoint = method.reconciliation?.[point];
      if (!sourcePoint) continue;
      methodRows.push([
        scenario.role,
        scenario.label,
        method.method_id,
        point,
        Number(sourcePoint.basis_value.value),
        Number(sourcePoint.equity_value.value),
        Number(sourcePoint.per_share_value?.value ?? 0),
        sourcePoint.per_share_value?.unit ?? range[point].unit,
        sourcePoint.per_share_value?.currency ?? range[point].currency,
        sourcePoint.per_share_value?.period ?? range[point].period,
        method.formula_version,
        rawScenario ? "parameter-trace-present" : "parameter-trace-missing",
      ]);
      for (const [stepIndex, item] of (sourcePoint.bridge_trace || []).entries()) {
        const nextOperation = sourcePoint.bridge_trace?.[stepIndex + 1]?.operation;
        bridgeRows.push([
          scenario.role,
          method.method_id,
          point,
          stepIndex + 1,
          item.operation,
          Number(item.amount),
          (item.ref_ids || []).join(" | "),
          nextOperation === "divide_diluted_shares" ? 1 : 0,
        ]);
      }
    }
  }
}
if (!methodRows.length && view.valuation_view?.status === "not_ready") {
  methodRows.push([
    "limited",
    "Data insufficient",
    "not_ready",
    "base",
    null,
    null,
    null,
    "unknown",
    "",
    view.as_of,
    "not_applicable",
    "qualified-inputs-missing",
  ]);
  bridgeRows.push([
    "limited",
    "not_ready",
    "base",
    1,
    "basis_value",
    null,
    "",
    null,
  ]);
} else if (!methodRows.length || !bridgeRows.length) {
  throw new Error("VALUATION_WORKBOOK_RECONCILIATION_INPUT_MISSING");
}
const reconciliationRows = methodRows.map((row) => [row[0], row[2], row[3]]);

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["Canonical Valuation Artifact Export"]];
summary.getRange("A3:B9").values = [
  ["Subject", view.subject_id],
  ["As of", view.as_of],
  ["Model identity", modelIdentitySummary],
  ["Policy", view.policy_identity],
  ["View schema", view.schema_version],
  ["Status", view.status],
  ["Boundary", view.boundary],
];
summary.getRange("A11:D11").values = [["Scenario", "Method", "Base displayed value", "Horizon"]];
const summaryRows = [];
for (const scenario of view.scenarios || []) {
  for (const method of scenario.methods || []) {
    if (method.status === "ready" && method.conditional_value_range?.base) {
      const reconciliationIndex = reconciliationRows.findIndex(
        (row) => row[0] === scenario.role
          && row[1] === method.method_id
          && row[2] === "base",
      );
      if (reconciliationIndex < 0) {
        throw new Error("VALUATION_WORKBOOK_SUMMARY_LINK_MISSING");
      }
      summaryRows.push([
        scenario.label,
        method.method_id,
        reconciliationIndex + 2,
        method.horizon,
        method.display_value_level,
      ]);
    }
  }
}
if (!summaryRows.length && view.valuation_view?.status === "not_ready") {
  summaryRows.push([
    "Data insufficient",
    "not_ready",
    2,
    "No formal valuation",
    "basis_value",
  ]);
}
if (summaryRows.length) {
  summary.getRangeByIndexes(11, 0, summaryRows.length, 4).values =
    summaryRows.map((row) => [row[0], row[1], null, row[3]]);
  for (let index = 0; index < summaryRows.length; index += 1) {
    summary.getRange(`C${index + 12}`).formulas = [[
      `='Reconciliation'!${summaryRows[index][4] === "basis_value" ? "D" : summaryRows[index][4] === "equity_value" ? "F" : "J"}${summaryRows[index][2]}`,
    ]];
  }
  summary.getRange(`C12:C${11 + summaryRows.length}`).format.numberFormat =
    "#,##0.00;[Red](#,##0.00);-";
}

imported.getRange("A1:L1").values = [[
  "Scenario Role", "Scenario Label", "Method", "Point", "Canonical Basis",
  "Canonical Equity", "Canonical Per Share", "Unit", "Currency", "Period",
  "Formula Version", "Parameter Trace",
]];
imported.getRangeByIndexes(1, 0, methodRows.length, 12).values = methodRows;

bridge.getRange("A1:I1").values = [[
  "Scenario Role", "Method", "Point", "Step", "Operation", "Amount", "Evidence Refs",
  "Equity Output Step", "Running Value",
]];
bridge.getRangeByIndexes(1, 0, bridgeRows.length, 8).values = bridgeRows;
for (let index = 0; index < bridgeRows.length; index += 1) {
  const row = index + 2;
  const sameGroup = index > 0
    && bridgeRows[index - 1][0] === bridgeRows[index][0]
    && bridgeRows[index - 1][1] === bridgeRows[index][1]
    && bridgeRows[index - 1][2] === bridgeRows[index][2];
  const previous = sameGroup ? `I${row - 1}` : "0";
  bridge.getRange(`I${row}`).formulas = [[
    `=IF(F${row}="","",IF(E${row}="basis_value",F${row},IF(LEFT(E${row},4)="add_",${previous}+F${row},IF(LEFT(E${row},9)="subtract_",${previous}-F${row},IF(E${row}="convert_fx",${previous}*F${row},IF(E${row}="divide_diluted_shares",${previous}/F${row},NA()))))))`,
  ]];
}

reconciliation.getRange("A1:M1").values = [[
  "Scenario Role", "Method", "Point", "Canonical Basis", "Computed Equity",
  "Canonical Equity", "Equity Difference", "Diluted Shares", "Computed Per Share",
  "Canonical Per Share", "Per Share Difference", "Equity Status", "Per Share Status",
]];
reconciliation.getRangeByIndexes(1, 0, reconciliationRows.length, 3).values = reconciliationRows;
for (let index = 0; index < reconciliationRows.length; index += 1) {
  const row = index + 2;
  reconciliation.getRange(`D${row}`).formulas = [[`='Canonical Inputs'!E${row}`]];
  reconciliation.getRange(`E${row}`).formulas = [[
    `=IF(D${row}="","",SUMIFS('Bridge Trace'!$I$2:$I$${bridgeRows.length + 1},'Bridge Trace'!$A$2:$A$${bridgeRows.length + 1},A${row},'Bridge Trace'!$B$2:$B$${bridgeRows.length + 1},B${row},'Bridge Trace'!$C$2:$C$${bridgeRows.length + 1},C${row},'Bridge Trace'!$H$2:$H$${bridgeRows.length + 1},1))`,
  ]];
  reconciliation.getRange(`F${row}`).formulas = [[`='Canonical Inputs'!F${row}`]];
  reconciliation.getRange(`G${row}`).formulas = [[`=IF(OR(E${row}="",F${row}=""),"",E${row}-F${row})`]];
  reconciliation.getRange(`H${row}`).formulas = [[
    `=SUMIFS('Bridge Trace'!$F$2:$F$${bridgeRows.length + 1},'Bridge Trace'!$A$2:$A$${bridgeRows.length + 1},A${row},'Bridge Trace'!$B$2:$B$${bridgeRows.length + 1},B${row},'Bridge Trace'!$C$2:$C$${bridgeRows.length + 1},C${row},'Bridge Trace'!$E$2:$E$${bridgeRows.length + 1},"divide_diluted_shares")`,
  ]];
  reconciliation.getRange(`I${row}`).formulas = [[`=IF(OR(H${row}=0,E${row}=""),"",E${row}/H${row})`]];
  reconciliation.getRange(`J${row}`).formulas = [[`='Canonical Inputs'!G${row}`]];
  reconciliation.getRange(`K${row}`).formulas = [[`=IF(OR(I${row}="",J${row}=""),"",I${row}-J${row})`]];
  reconciliation.getRange(`L${row}`).formulas = [[`=IF(G${row}="","NOT_READY",IF(ABS(G${row})<0.0000001,"OK","FAIL"))`]];
  reconciliation.getRange(`M${row}`).formulas = [[`=IF(K${row}="","NOT_READY",IF(ABS(K${row})<0.0000001,"OK","FAIL"))`]];
}

const artifactRows = (view.audit?.artifact_records || []).map((item) => [
  item.artifact_kind, item.schema_version, item.content_hash, item.source_identity, item.status,
]);
if (!artifactRows.length) {
  artifactRows.push(
    [
      "Evaluation plan",
      view.audit?.evaluation_plan?.schema_version || "",
      view.audit?.evaluation_plan_identity || "",
      view.audit?.source_policy_identity || "",
      view.status,
    ],
    [
      "Strategy validation",
      "",
      "",
      view.audit?.strategy_validation?.reason_code || "",
      view.audit?.strategy_validation?.status || "not_requested",
    ],
    [
      "Model code identity",
      "",
      view.model_identity,
      "",
      "bound",
    ],
  );
}
audit.getRange("A1:E1").values = [["Audit Item", "Schema", "Identity / Hash", "Source / Reason", "Status"]];
if (artifactRows.length) audit.getRangeByIndexes(1, 0, artifactRows.length, 5).values = artifactRows;
const formulaRows = (view.audit?.formula_identities || []).map((item) => [item]);
audit.getRange("G1").values = [["Formula Identities"]];
if (formulaRows.length) audit.getRangeByIndexes(1, 6, formulaRows.length, 1).values = formulaRows;

checks.getRange("A1:F1").values = [["Check", "Actual", "Expected", "Difference", "Tolerance", "Status"]];
checks.getRange("A2:F5").values = [
  ["Workbook projection rows", methodRows.length, methodRows.length, 0, 0, null],
  ["Equity reconciliation failures", null, 0, null, 0, null],
  ["Per-share reconciliation failures", null, 0, null, 0, null],
  ["Valuation readiness", view.valuation_view?.status || "unknown", "ready", null, null, null],
];
checks.getRange("F2").formulas = [['=IF(B2=C2,"OK","FAIL")']];
checks.getRange("B3").formulas = [[`=COUNTIF('Reconciliation'!L2:L${methodRows.length + 1},"FAIL")`]];
checks.getRange("D3").formulas = [["=B3-C3"]];
checks.getRange("F3").formulas = [['=IF(B3=C3,"OK","FAIL")']];
checks.getRange("B4").formulas = [[`=COUNTIF('Reconciliation'!M2:M${methodRows.length + 1},"FAIL")`]];
checks.getRange("D4").formulas = [["=B4-C4"]];
checks.getRange("F4").formulas = [['=IF(B4=C4,"OK","FAIL")']];
checks.getRange("F5").formulas = [['=IF(B5=C5,"OK","NOT_READY")']];
checks.getRange("A7:B7").values = [["Overall Model Status", null]];
checks.getRange("B7").formulas = [['=IF(F5="NOT_READY","NOT_READY",IF(COUNTIF(F2:F4,"FAIL")=0,"OK","FAIL"))']];

const headerStyle = {
  fill: "#173B52",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#173B52" },
};
for (const [sheet, range] of [
  [summary, "A11:D11"], [imported, "A1:L1"], [bridge, "A1:I1"],
  [reconciliation, "A1:M1"], [audit, "A1:E1"], [audit, "G1:G1"], [checks, "A1:F1"],
]) {
  sheet.getRange(range).format = headerStyle;
  sheet.freezePanes.freezeRows(1);
}
summary.getRange("A1:H1").format = {
  fill: "#102F43",
  font: { bold: true, color: "#FFFFFF" },
};
summary.getRange("A3:A9").format.font = { bold: true, color: "#526875" };
imported.getRange(`E2:G${methodRows.length + 1}`).format.numberFormat =
  "#,##0.0000;[Red](#,##0.0000);-";
imported.getRange(`A2:L${methodRows.length + 1}`).format.font = { color: "#008000" };
bridge.getRange(`F2:I${bridgeRows.length + 1}`).format.numberFormat =
  "#,##0.0000;[Red](#,##0.0000);-";
reconciliation.getRange(`D2:K${methodRows.length + 1}`).format.numberFormat =
  "#,##0.0000;[Red](#,##0.0000);-";
checks.getRange("A7:B7").format = {
  fill: "#DCECF2",
  font: { bold: true, color: "#102F43" },
  borders: { preset: "outside", style: "medium", color: "#173B52" },
};
for (const sheet of [summary, imported, bridge, reconciliation, audit, checks]) {
  const used = sheet.getUsedRange();
  used.format.autofitColumns();
  used.format.autofitRows();
}
summary.getRange("A1:A30").format.columnWidth = 24;
summary.getRange("B1:B30").format.columnWidth = 60;
summary.getRange("B3:B9").format.wrapText = true;
summary.getRange("D1:D30").format.columnWidth = 46;
bridge.getRange(`G1:G${bridgeRows.length + 1}`).format.columnWidth = 60;
audit.getRange(`C1:D${Math.max(2, artifactRows.length + 1)}`).format.columnWidth = 52;
audit.getRange(`A1:E${artifactRows.length + 1}`).format.wrapText = true;
summary.getRange("A1:H30").format.autofitRows();
audit.getRange(`A1:E${artifactRows.length + 1}`).format.autofitRows();

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "valuation workbook formula error scan",
});
if (errors.ndjson && /#REF!|#DIV\/0!|#VALUE!|#NAME\?|#N\/A/.test(errors.ndjson)) {
  throw new Error(`VALUATION_WORKBOOK_FORMULA_ERROR:${errors.ndjson}`);
}
const reconciliationCheck = await workbook.inspect({
  kind: "table",
  range: "Checks!A1:F7",
  include: "values,formulas",
  tableMaxRows: 7,
  tableMaxCols: 6,
});
if (reconciliationCheck.ndjson && /\"FAIL\"/.test(reconciliationCheck.ndjson)) {
  const reconciliationDetail = await workbook.inspect({
    kind: "table",
    range: "Reconciliation!A1:M5",
    include: "values,formulas",
    tableMaxRows: 5,
    tableMaxCols: 13,
  });
  throw new Error(
    `VALUATION_WORKBOOK_RECONCILIATION_FAILED:${reconciliationCheck.ndjson}:`
      + reconciliationDetail.ndjson,
  );
}
if (previewPath) {
  const preview = await workbook.render({
    sheetName: "Summary",
    range: `A1:H${Math.max(18, summaryRows.length + 13)}`,
    scale: 1.5,
    format: "png",
  });
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
}
if (process.env.VALUATION_WORKBOOK_QA_DIR) {
  await fs.mkdir(process.env.VALUATION_WORKBOOK_QA_DIR, { recursive: true });
  for (const sheetName of [
    "Summary",
    "Canonical Inputs",
    "Bridge Trace",
    "Reconciliation",
    "Sources Audit",
    "Checks",
  ]) {
    const preview = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1,
      format: "png",
    });
    const filename = sheetName.toLowerCase().replaceAll(" ", "-") + ".png";
    await fs.writeFile(
      `${process.env.VALUATION_WORKBOOK_QA_DIR}/${filename}`,
      new Uint8Array(await preview.arrayBuffer()),
    );
  }
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
