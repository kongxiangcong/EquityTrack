# Data Source Specification

**[Note] This file defines data source priority and selection logic. For specific API parameters, grep search `references/data-sources-detail.md`.**

---

## Data Source Priority

> **Official disclosure is the first layer for critical financial data.** Commercial terminals and Yahoo Finance are useful for structuring, market data, and cross-checks, but they cannot be the sole authority for financial statements, share count, net debt, minority interest, or other valuation-critical numbers.

Every critical number must be entered into `source_manifest` using `references/source-manifest.md`. If a critical number cannot be tied to an official source, mark it `missing` and trigger `data_insufficient_memo` rather than continuing to a valuation conclusion.

### By market (official-first)

| Market | Priority 1: Official financial disclosure | Optional secondary / cross-check | Fallback / allowed use |
|--------|-------------------------------------------|----------------------------------|------------------------|
| A-shares (`.SH` / `.SZ` / `.BJ`) | CNINFO, SSE/SZSE/BSE announcements, company IR annual/interim/quarterly reports | iFind, exchange market data, Yahoo where usable | Web search only for source discovery, news, industry context; not as sole critical financial source |
| Hong Kong (`.HK`) | HKEXnews, company IR annual/interim reports | iFind, Yahoo, terminal data | Web search for source discovery, news, industry context |
| US (`AAPL`, `MSFT`, ...) | SEC EDGAR filings, companyfacts/companyconcept XBRL APIs, company IR annual/quarterly reports | Yahoo, terminal data, consensus services | Web search for source discovery, news, industry context |

### Data type priority

| Data Type | Primary Source | Secondary / Cross-check | Hard Rule |
|-----------|----------------|-------------------------|-----------|
| Financial statements | Official filings / company IR | iFind/Yahoo/terminal structured data | No official source → no valuation conclusion |
| Share count / net debt / minority interest / preferred / leases | Official filings / notes | Terminal data | Missing or conflicting → no per-share value |
| Price / market cap / trading data | Exchange/terminal/Yahoo/iFind with timestamp | Backup market data source | Must save retrieval date and adjustment method |
| Consensus estimates | Licensed consensus source or clearly labeled secondary source | Company guidance / broker summaries | Treat as estimates, never official history |
| Industry / TAM / market share | Association/statistical agency/company filings/reputable research | News/web search | Must label methodology and period |

### Cross-market sources (any ticker)

| Source | Use Case | Notes |
|--------|----------|-------|
| Web Search | Real-time news, capital flows, catalysts, industry dynamics | Primary for news; secondary for data verification |
| 天眼查 | Chinese companies — supply chain, competitors, corporate relationships | Often incomplete; see fallback rules below |
| Caixin | Industry policy, macroeconomic background | All industries |

---

## iFind Data Source (Optional Secondary)

iFind is an optional connector/terminal source. Use it for structuring, market data, historical multiples, and cross-checking. Do not treat it as the only source for critical financial-statement history when official filings are available or required.

### API List

| API Name | Function | Core Parameters |
|----------|----------|-----------------|
| `ifind_get_stock_info` | Company basic info | `ticker`, `file_path` |
| `ifind_get_financial_statements` | Financial statements | `ticker`, `statement`, `financial_parameter`, `file_path` |
| `ifind_get_stock_business_segmentation` | Business segmentation | `ticker`, `financial_parameter`, `file_path` |
| `ifind_get_stock_financial_index` | Financial metrics | `ticker`, `financial_parameter`, `file_path` |
| `ifind_get_forecast` | Earnings forecasts | `ticker`, `file_path` |
| `ifind_get_price` | Stock price data | `ticker`, `start_date`, `end_date`, `file_path`, `adjust` |
| `ifind_get_stock_announcement` | Announcements (A股) | `ticker`, `start_date`, `end_date`, `file_path` |

> **Parameter Explanation**:
> - `ticker`: Stock code, supports multiple tickers separated by comma (e.g., `"600519.SH,000858.SZ"`). **Do NOT mix A-shares with HK/US stocks** in a single call — cross-market queries return empty data for business segmentation and related stock APIs.
> - `file_path`: Output CSV path (required).
> - `financial_parameter`: **Reporting period in format `YYYY`+`MM DD`** where MM DD is fixed:
>   - `XXXX0331` = Q1 report (一季报)
>   - `XXXX0630` = H1 report (半年报)
>   - `XXXX0930` = Q3 report (三季报)
>   - `XXXX1231` = Annual report (年报)
>   - Example: `"20241231"` = FY2024 annual, `"20250331"` = Q1 2025

### Stock Code Format (iFind)

| Market | Format | Example | Yahoo Finance Equiv |
|--------|--------|---------|---------------------|
| A股 Shanghai | `XXXXXX.SH` | `600519.SH` | `600519.SS` |
| A股 Shenzhen | `XXXXXX.SZ` | `000001.SZ` | `000001.SZ` |
| A股 Beijing | `XXXXXX.BJ` | `835185.BJ` | `835185.BJ` |
| HK stocks | `XXXX.HK` | `0700.HK` | `0700.HK` |
| US NYSE | `XXX.N` | `XOM.N` | `XOM` |
| US NASDAQ | `XXX.O` | `AAPL.O` | `AAPL` |
| US NYSE (Class A) | `XXX.A.N` | `BRK.A.N` | `BRK-A` |
| US NYSE (Class B) | `XXX.B.N` | `BRK.B.N` | `BRK-B` |

> **⚠️ Important**: iFind and Yahoo Finance use **different suffixes for US stocks**.
> - iFind: `.N` (NYSE), `.O` (NASDAQ), `.A.N`, `.B.N`
> - Yahoo Finance: No suffix (NYSE), same ticker (NASDAQ)
> When calling iFind for US stocks, use `.N` / `.O` format. When calling Yahoo Finance, use the plain ticker (e.g., `AAPL`).

### Common Metrics Quick Reference

**Profitability**: `gross_profit_margin`, `net_profit_margin`, `roe`, `roa`
**Growth**: `revenue_growth`, `net_profit_growth`, `eps_growth`
**Valuation**: `pe_ttm`, `pb`, `ps`, `ev_ebitda`

---

## Yahoo Finance Data Source (Optional Secondary)

Yahoo Finance is acceptable for price, market cap, trading data, and a secondary view of financials. It is not the sole source of authority for financial-statement history in this skill.

| API Name | Function | Parameters |
|----------|----------|------------|
| `get_stock_info` | Company info | `ticker` (e.g., `AAPL`) |
| `get_financial_statement` | Financial statements | `ticker`, `statement_type` |
| `get_recommendations` | Analyst ratings | `ticker` |
| `get_news` | News | `ticker`, `limit` |

---

## 天眼查 Data Source

| API Name | Function | Parameters |
|----------|----------|------------|
| `tianyancha_api_search` | Search companies | `keyword` |
| `tianyancha_api_call` | Specific queries | `api_name`, `params` |

Common scenarios: suppliers (`supplier_info`), customers (`customer_info`), competitors (`competitor_info`), equity structure (`shareholder_info`)

### Equity Structure Data Collection Routing

| Company Type | Data Source | Method |
|-------------|------------|--------|
| Chinese companies (incl. China concept stocks/HK-listed Chinese companies) | 天眼查 | `tianyancha_api_call(api_name='shareholder_info', params={'keyword': '[company_name]'})` |
| Non-Chinese companies | Company annual reports/SEC EDGAR/Official IR | Web Search `[company_name] major shareholders`, `[ticker] proxy statement ownership` |

**Collection Points**: Actual controller/major shareholders + shareholding percentage + equity characteristics (family control/state-owned control/dispersed ownership/AB shares/VIE structure) + significant institutional shareholders (if any).

---

## Caixin & Web Search

**Caixin**: `caixin_api_search` (industry policy, macroeconomic background)

**Web Search Common Keywords**:
| Scenario | Search Keywords | Timeliness Requirement |
|----------|-----------------|------------------------|
| Real-time news/marginal events | `[company_name] latest updates`, `[company_name] new products/orders/policy impact` | Prefer within 7 days, should include even if sparse coverage |
| Capital flows/position changes | `[company_name] major shareholder reduction/increase`, `[company_name] 解禁`, `[company_name] 定向增发`, `[company_name] buyback` | Within 1 month |
| 北向资金/mainline capital | `[company_name] 北向资金`, `[company_name] mainline capital flow` | Within 7 days |
| Industry data | `[industry] market size` | Within 1 year |
| Catalysts | `[company_name] earnings calendar` | Next 6 months |
| Competitors | `[company_name] competitors` | Within 6 months |
| Industry chain | `[industry] supply chain analysis` | Within 1 year |

### Short-term Investment Logic Data Collection Rules

**1. Real-time News High-Weight Principle**
- Even if news is from a day ago with limited coverage (e.g., new product launch, sudden order, regulatory Q&A), if it may impact investor marginal expectations, it must be included in short-term investment logic "利多/利空" or "key disagreement points" analysis.
- Example: A tech company released a new generation product yesterday with only 3-4 reports, but if the product accounts for high revenue percentage, it should be given high weight.

**2. Capital and Market Structure Data Checklist**
Must collect the following data in Phase 1 for subsequent 六维分析 and short-term investment logic:
- [ ] **解禁 Calendar**: Shares to be unlocked within 3 months, percentage of total shares, identity of unlocking shareholders
- [ ] **Increase/Decrease Holdings**: Major shareholder/executive/important institutions (e.g., major fund, long-term investor) announcements in the past month
- [ ] **定向增发/Equity Issuance**: Progress, price, subscribers of announced but incomplete issuances
- [ ] **Buyback Plans**: Announced buyback amount, progress, remaining budget
- [ ] **北向资金/Mainline Capital**: Capital flow trend in past 1-2 weeks (net inflow/outflow)
- [ ] **大宗交易/Abnormal Trading Signals**: Any abnormal bulk discounted trades or 龙虎榜 anomalies in past month

**Data Source Priority**:
| Data Type | Primary Source | Backup Source |
|-----------|----------------|----------------|
| 解禁/Increase/Decrease Holdings/Buyback | iFind `ifind_get_stock_info` / `ifind_get_stock_announcement` | Web Search `[company_name] 解禁 date` |
| 龙虎榜/大宗交易 | Web Search `[company_name] 龙虎榜` / `bulk trading` | 东方财富/同花顺 |
| 北向资金 Flow | Web Search `[company_name] 北向资金` | Shanghai-Hong Kong-Shenzhen disclosure |
| Real-time News | Web Search (财联社, 证券时报, company official Weibo) | Company announcements |

---

## Missing Data Handling

| Scenario | Handling Method | Annotation |
|----------|-----------------|------------|
| Single source missing | Try official source route first, then optional secondary/cross-check | Annotate actual source and source tier |
| Dual source conflict | Official disclosure wins for financials; latest restatement wins when applicable | Annotate difference, period, currency, unit |
| **Critical financial data missing official source** | **Mark `missing` in source manifest → produce `data_insufficient_memo`** | **No valuation conclusion, target price, or rating** |
| **Critical stock price data missing** | **Multi-attempt retry → then skip price/chart module** | **See §Stock Price Data Retry Protocol below** |
| Industry data missing | Web Search supplement | Annotate source |

### Critical Data Gate

If any of the following fields lacks official or adequately documented source coverage, the workflow must degrade to `data_insufficient_memo`:

- Latest annual/interim/quarterly financial statements.
- Reporting currency, unit, reporting period, accounting standard, and restatement status.
- Diluted share count, options/SBC dilution when material, net debt, lease debt, preferred stock, minority interest, pension deficit, non-operating assets, associates/JV value.
- For DCF: EBIT, tax rate, D&A, CapEx, working capital, WACC components, terminal growth basis, and `WACC > g`.
- For financial firms: book value, ROE, COE inputs, regulatory capital/solvency metrics, credit/underwriting quality metrics.
- For biopharma rNPV: asset, indication, phase, geography, rights ownership, PoS basis, peak-sales basis, license terms, cash runway.
- For comps: peer market cap/EV, metric definitions, reporting period, currency/unit, and at least 3 usable peers.

### ⛔ ZERO TOLERANCE: No Simulated/Mock Data Under Any Circumstance

**The following actions are PERMANENTLY PROHIBITED:**

| Prohibited Action | Why It's Dangerous | Correct Alternative |
|-------------------|-------------------|---------------------|
| Generating random/synthetic price data | 52-week high/low completely fabricated → false investment signals | Skip chart, annotate "data unavailable" |
| Using "representative" sample prices | Benchmark overlay and excess return are fiction | Skip chart, annotate "data unavailable" |
| Estimating/guessing historical prices | Misrepresents actual price trajectory to readers | Skip chart, annotate "data unavailable" |
| Hardcoding example numbers from skill docs | Examples are syntax demos, not real data | Extract from Excel model or API |
| Any form of price data fabrication | Compliance violation; destroys report credibility | Skip chart, annotate "data unavailable" |

> **Hard Rules**:
> 1. API error → **Diagnostic workflow** (see below) → **Retry up to 3 times** with corrected parameters
> 2. Parameters correct but still fails → **Switch to backup data source** (iFind → Yahoo Finance)
> 3. All sources exhausted → **Skip that module**, annotate "no public data available"
> 4. **Absolutely prohibited**: Replace real data with random numbers/simulated data/placeholders

### Stock Price Data Retry Protocol (Critical — Most Data-Sensitive Module)

When retrieving **stock price data** (the most data-critical module):

**Step 1: Define "Failure" — A retry-triggering failure is ANY of:**

| Failure Type | Detection Method | Examples |
|-------------|------------------|----------|
| **Timeout** | API call hangs >30s or returns timeout error | `ConnectionTimeout`, `ReadTimeout` |
| **Empty response** | API returns success but file is empty or <100 bytes | CSV has 0 rows, only header row |
| **Error response** | API returns explicit error code/message | `Error: invalid ticker`, `RateLimitError` |
| **Data quality failure** | File exists but has <50 valid price rows | Only 10 rows for a 252-trading-day period |
| **Exception** | Python exception during API call | `KeyError`, `ValueError`, `ConnectionError` |

**→ ANY of the above = 1 failed attempt. Do NOT proceed to script call. Retry.**

**Step 2: Retry Flow**

```
iFind get_price attempt 1
    ↓ fail (any failure type above)
iFind get_price attempt 2 (parameter diagnosis → see below)
    ↓ fail
iFind get_price attempt 3 (exponential backoff: wait 4s, then retry)
    ↓ fail
Yahoo Finance get_historical_stock_prices (fallback source)
    ↓ fail
Action: SKIP stock chart module — insert annotation
    ↓
Proceed with rest of report (NEVER use mock data)
```

**Retry Configuration**:
- Max retries per source: **3** (not 1)
- Backoff strategy: exponential — wait 2s, 4s, 8s between retries
- Source switch: iFind → Yahoo Finance (different infrastructure)
- Final action: skip module (not fabricate data)
- **⛔ NEVER**: After 1 failure, immediately fall back to mock/simulated data. Always exhaust the full retry chain first.

### API Parameter Diagnostic Workflow (Execute Before Each Retry)

When an iFind API call returns empty or errors, **do NOT immediately fall back to Web Search**. Execute this diagnostic first:

```
iFind API returns empty/error (attempt N of 3)
    │
    ├─ Step 1: Check ticker format
    │   ├─ A股: Must be XXXXXX.SH / XXXXXX.SZ / XXXXXX.BJ
    │   ├─ HK: Must be XXXX.HK
    │   ├─ US NYSE: Must be XXX.N (e.g., XOM.N)
    │   ├─ US NASDAQ: Must be XXX.O (e.g., AAPL.O)
    │   └─ Wrong format? → Fix and retry
    │
    ├─ Step 2: Check financial_parameter format
    │   ├─ Must be YYYYMMDD with MM DD ∈ {0331, 0630, 0930, 1231}
    │   ├─ Example wrong: "2024Q1", "FY2024", "2024" → Fix to "20240331"
    │   └─ Wrong format? → Fix and retry
    │
    ├─ Step 3: Check cross-market mixing
    │   ├─ ifind_get_stock_business_segmentation: A股 + HK/US mix → error
    │   ├─ ifind_get_related_stock: Cross-market mix → error
    │   └─ Mixed markets? → Split into separate calls
    │
    ├─ Step 4: Check API-specific restrictions
    │   ├─ ifind_get_forecast: Only A-shares, single ticker only
    │   ├─ ifind_get_stock_announcement: Only A-shares
    │   └─ Restriction violation? → Switch to Yahoo Finance
    │
    ├─ Step 5: Apply exponential backoff wait (2^N seconds)
    │
    ├─ Step 6: Retry (attempt N+1 of 3)
    │
    └─ All 3 attempts exhausted → Switch to Yahoo Finance fallback
        └─ Yahoo Finance also fails → Skip module, annotate "data unavailable"
```

**Critical: Always call `get_data_source_desc("ifind")` first to confirm available APIs and their exact parameter requirements before making iFind calls.**

### ifind_get_price Parameter Checklist (Price Data Specific)

When `ifind_get_price` fails, verify these 5 parameters before retrying:

| # | Parameter | Correct Format | Common Errors |
|---|-----------|---------------|---------------|
| 1 | `ticker` | A股: `XXXXXX.SH/SZ/BJ`; HK: `XXXX.HK`; US NYSE: `XXX.N`; US NASDAQ: `XXX.O` | Missing suffix (`600519` → `600519.SH`); wrong suffix (`AAPL` → `AAPL.O`) |
| 2 | `start_date` / `end_date` | `YYYYMMDD` (e.g., `20240115`) | `YYYY-MM-DD`, `YYYY/MM/DD`, Unix timestamp |
| 3 | `adjust` | `"forward"` (exact string) | `"fwd"`, `"F"`, `"Forward"`, `true` |
| 4 | `file_path` | Valid writable path ending in `.csv` | Non-writable directory, missing extension, relative path issues |
| 5 | `ticker` cross-market | Do NOT mix A股 + HK/US in same call | Returns empty for all tickers |

> **Note**: Steps 1-4 above are specific to `ifind_get_price`. For other iFind APIs (financial statements, business segmentation, etc.), use the general API Parameter Diagnostic Workflow in the previous section.

---

## Data Conflict Resolution Decision Tree

```
Data Conflict Detection
    │
    ├─ Conflict Type Judgment
    │   ├─ Price Data Conflict (stock price/valuation)
    │   │   ├─ A股/HK stocks → Use exchange/terminal source with documented adjustment; iFind/Yahoo can cross-check
    │   │   ├─ US stocks → Use exchange/Yahoo/terminal source with retrieval timestamp
    │   │   └─ Difference >10% → Re-fetch data, check adjustment settings
    │   │
    │   ├─ Financial Data Conflict (revenue/profit/assets)
    │   │   ├─ Check if reporting periods match
    │   │   │   ├─ Match → Use official filing/company disclosure as reference
    │   │   │   └─ Mismatch → Unify using latest reporting period
    │   │   └─ Difference 5-10% → Annotate data source difference, prioritize official disclosure/restatement
    │   │
    │   ├─ Time Series Data Conflict (52-week high/low/historical valuation)
    │   │   ├─ Check if ex-dividend adjustment is consistent, including checking price continuity (any single-day swings >30%)
    │   │   │   ├─ Adjustment consistent → Take average or primary source data
    │   │   │   └─ Adjustment inconsistent → Re-fetch ex-dividend data, or use adjusted data series
    │   │   └─ Single-day swing >30% → Check for stock split/consolidation events
    │   │
    │   └─ Industry Data Conflict (market size/competitive landscape)
    │       ├─ Use authoritative third-party sources (brokerage reports/industry associations)
    │       ├─ Large multi-source differences → Web Search for authoritative sources
    │       └─ Annotate data source and statistical scope differences
    │
    └─ Difference Handling Process
        ├─ Difference <5% → Record difference, use primary source, no annotation
        ├─ Difference 5-10% → Annotate data source difference, prioritize iFind
        └─ Difference >10% → Re-verify data source, Web Search validation, annotate uncertainty if necessary
```

### Conflict Resolution Principles

| Data Type | Primary Source | Verification Source | Conflict Handling Rule |
|-----------|----------------|---------------------|----------------------|
| A股 stock price | Exchange/terminal/iFind with timestamp | Yahoo Finance where usable | Check adjustment if difference >5%; document chosen series |
| HK stock price | Exchange/terminal/iFind/Yahoo with timestamp | Alternate market data source | Check adjustment/currency if difference >5%; document chosen series |
| US stock price | Exchange/Yahoo/terminal with timestamp | Alternate market data source | Document retrieval timestamp and adjustment method |
| A股 financials | CNINFO/SSE/SZSE/BSE/company IR | iFind/terminal | Official filing/restatement wins |
| HK financials | HKEXnews/company IR | iFind/Yahoo/terminal | Official filing/restatement wins |
| US financials | SEC EDGAR/XBRL/company IR | Yahoo/iFind/terminal | Official filing/restatement wins |
| Industry data | Official statistics/associations/company filings/reputable research | Web Search | Use authoritative source, annotate methodology and period |

### Adjustment Problem Handling

**Problem Identification:**
- Single-day swing >30% within 52 weeks (non-trading halt)
- Stock price shows cliff-like jumps
- iFind vs Yahoo Finance difference >10%

**Handling Steps:**
1. Search `[company_name] stock split consolidation` to confirm equity changes
2. If confirmed stock split/consolidation → Re-fetch ex-dividend data (`adjust: "forward"`)
3. If confirmed real spike/crash (e.g., earnings disaster) → Keep data, annotate event in chart
4. If unable to confirm → Use iFind data, annotate data uncertainty

### yfinance Downgrade Rules

**A股/HK scenario**:
- yfinance frequently triggers `YFRateLimitError` for A-share/HK tickers
- **Rule**: After first yfinance call fails, do not retry; use iFind as sole data source
- **Annotation**: In data sources annotate `iFind (Yahoo Finance rate-limited)`

**US stock scenario**:
- Prioritize Yahoo Finance, use iFind as verification source
- If yfinance also fails, fall back to iFind

### 天眼查 Data Gap Fallback

天眼查 supplier, customer, competitor data frequently returns empty or timeout. Handle with 3 steps:

1. **Web Search Supplement**
   - Search keywords: `[company_name] suppliers`, `[company_name] customers`, `[industry] competitive landscape`
2. **iFind Industry Classification**
   - Use industry classification from `ifind_get_stock_info` to find comparable companies in same industry as competitors/supply chain reference
3. **Transparency Annotation**
   - If supply chain data cannot be completed through any method, clearly annotate in report:
     `*Supply chain data based on public information; some details have no public data*`

---

## Data Timeliness Check

```markdown
□ Financial statements: Use latest period, annotate reporting period
□ Market data: Use current closing price or real-time price, annotate date
□ Earnings forecasts: Use 30-day consensus forecast, annotate forecast date
□ Announcements/news: Use data from past 6 months, annotate source and date
□ Industry data: Use data from past year, annotate source
□ Comparable companies: Ensure comparison benchmarks are consistent, annotate date
```

---

## Benchmark Index Codes

| Index | Code |
|-------|------|
| 上证指数 | `000001.SH` |
| 沪深300 | `000300.SH` |
| 恒生指数 | `HSI.HK` |
| S&P 500 | `^GSPC` |
| NASDAQ | `^IXIC` |
