from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import requests


AUDIT_USER_AGENT = (
    "tradingSystem qualification audit/0.0 "
    "(non-production; contact not configured)"
)


def probe(
    name: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    encoding: str | None = None,
) -> tuple[dict[str, Any], requests.Response | None]:
    started = time.perf_counter()
    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        if encoding:
            response.encoding = encoding
        body = response.content
        result = {
            "name": name,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "content_type": response.headers.get("content-type"),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "schema": summarize_schema(response),
        }
        return result, response
    except requests.RequestException as error:
        return (
            {
                "name": name,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "failure": type(error).__name__,
            },
            None,
        )


def summarize_schema(response: requests.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        return {"kind": "non-json"}
    try:
        payload = response.json()
    except ValueError:
        return {"kind": "malformed-json"}
    if isinstance(payload, dict):
        return {"kind": "object", "top_level_keys": sorted(payload.keys())}
    if isinstance(payload, list):
        return {"kind": "array", "length": len(payload)}
    return {"kind": type(payload).__name__}


def main() -> None:
    probes: list[dict[str, Any]] = []

    yahoo_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36"
        )
    }
    for symbol in ("AAPL", "0700.HK"):
        result, _ = probe(
            f"yahoo-chart-{symbol}",
            f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "5d"},
            headers=yahoo_headers,
        )
        probes.append(result)

    for name, url, params, headers, encoding in (
        (
            "eastmoney-us-quote",
            "https://push2.eastmoney.com/api/qt/stock/get",
            {
                "secid": "105.AAPL",
                "fields": "f43,f44,f45,f46,f47,f48,f55,f57,f58,f59,f60,f170",
            },
            None,
            None,
        ),
        (
            "eastmoney-hk-quote",
            "https://push2.eastmoney.com/api/qt/stock/get",
            {
                "secid": "116.00700",
                "fields": "f43,f44,f45,f46,f47,f48,f55,f57,f58,f59,f60,f170",
            },
            None,
            None,
        ),
        (
            "sina-us-quote",
            "https://hq.sinajs.cn/list=gb_aapl",
            None,
            {
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": yahoo_headers["User-Agent"],
            },
            "gbk",
        ),
        (
            "sina-hk-quote",
            "https://hq.sinajs.cn/list=rt_hk00700",
            None,
            {
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": yahoo_headers["User-Agent"],
            },
            "gbk",
        ),
        (
            "tencent-us-quote",
            "https://qt.gtimg.cn/q=usAAPL",
            None,
            None,
            "gbk",
        ),
        (
            "tencent-hk-quote",
            "https://qt.gtimg.cn/q=r_hk00700",
            None,
            None,
            "gbk",
        ),
    ):
        result, _ = probe(name, url, params=params, headers=headers, encoding=encoding)
        probes.append(result)

    sec_headers = {"User-Agent": AUDIT_USER_AGENT}
    ticker_result, ticker_response = probe(
        "sec-company-tickers",
        "https://www.sec.gov/files/company_tickers.json",
        headers=sec_headers,
    )
    submissions_result, submissions_response = probe(
        "sec-submissions-aapl",
        "https://data.sec.gov/submissions/CIK0000320193.json",
        headers=sec_headers,
    )
    facts_result, facts_response = probe(
        "sec-companyfacts-aapl",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        headers=sec_headers,
    )
    probes.extend((ticker_result, submissions_result, facts_result))

    cross_validation: dict[str, Any] = {
        "production_user_agent_compliant": False,
        "reason": "audit identity deliberately has no truthful contact address",
    }
    if submissions_response and facts_response:
        submissions = submissions_response.json()
        facts = facts_response.json()
        mapped_cik = None
        if ticker_response and ticker_response.status_code == 200:
            ticker_map = ticker_response.json()
            apple_map = next(
                value for value in ticker_map.values() if value.get("ticker") == "AAPL"
            )
            mapped_cik = str(apple_map["cik_str"]).zfill(10)
        submissions_cik = str(submissions["cik"]).zfill(10)
        facts_cik = str(facts["cik"]).zfill(10)
        recent = submissions["filings"]["recent"]
        latest_10k_index = recent["form"].index("10-K")
        latest_accession = recent["accessionNumber"][latest_10k_index]
        linked_fact_count = 0
        unit_names: set[str] = set()
        for taxonomy in facts.get("facts", {}).values():
            for concept in taxonomy.values():
                for unit, entries in concept.get("units", {}).items():
                    unit_names.add(unit)
                    linked_fact_count += sum(
                        1 for entry in entries if entry.get("accn") == latest_accession
                    )
        cross_validation.update(
            {
                "mapped_cik": mapped_cik,
                "submissions_cik": submissions_cik,
                "companyfacts_cik": facts_cik,
                "submissions_companyfacts_normalized_cik_match": (
                    submissions_cik == facts_cik == "0000320193"
                ),
                "ticker_map_normalized_cik_match": (
                    None
                    if mapped_cik is None
                    else mapped_cik == submissions_cik == facts_cik
                ),
                "ticker_identity_match": (
                    "AAPL" in submissions.get("tickers", [])
                    and "Nasdaq" in submissions.get("exchanges", [])
                ),
                "submissions_recent_rows": len(recent["form"]),
                "submissions_has_historical_files": bool(
                    submissions["filings"].get("files")
                ),
                "latest_10k": {
                    "form": recent["form"][latest_10k_index],
                    "filing_date": recent["filingDate"][latest_10k_index],
                    "report_date": recent["reportDate"][latest_10k_index],
                    "acceptance_datetime": recent["acceptanceDateTime"][
                        latest_10k_index
                    ],
                    "accession": latest_accession,
                    "primary_document": recent["primaryDocument"][
                        latest_10k_index
                    ],
                },
                "companyfacts_taxonomies": sorted(facts.get("facts", {}).keys()),
                "companyfacts_concepts": sum(
                    len(taxonomy) for taxonomy in facts.get("facts", {}).values()
                ),
                "companyfacts_units": sorted(unit_names),
                "facts_linked_to_latest_10k_accession": linked_fact_count,
            }
        )

    print(
        json.dumps(
            {
                "suite": "global-stock-data-live-connectivity",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "upstream_commit": "d52a8a0013363577bceb28ca876c88fe6c1a5aeb",
                "python": "3.11.15",
                "requests": requests.__version__,
                "raw_bodies_persisted": False,
                "probes": probes,
                "official_cross_validation": cross_validation,
                "interpretation_boundary": (
                    "HTTP reachability does not establish schema stability, "
                    "data entitlement, cache rights, or production qualification."
                ),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
