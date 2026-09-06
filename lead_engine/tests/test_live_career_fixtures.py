"""Tests against live career captures from the 2026-09-06 verification run."""

import json
from pathlib import Path

from scrapling.engines.toolbelt.custom import Response

from lead_engine.scrapers.career_pages import build_leads, extract_roles

FIXTURES = Path(__file__).parent / "fixtures" / "live"


def response(name, url):
    return Response(
        url=url, content=(FIXTURES / name).read_bytes(), status=200, reason="OK",
        encoding="utf-8", cookies={}, headers={"content-type": "text/html"},
        request_headers={}, method="GET",
    )


def test_real_benchmark_infor_capture_contains_seven_postings():
    roles = extract_roles(
        response("benchmark_infor.html", "https://css-benchmark-prd.inforcloudsuite.com/jobs"),
        company="Benchmark",
    )
    assert len(roles) == 7
    assert any(role.title.startswith("Quality Technician I") for role in roles)
    assert all("inforcloudsuite.com" in role.url.lower() for role in roles)
    # The current Lead builder intentionally drops these because the existing
    # classifier maps these title families to category=other.
    assert build_leads(
        response("benchmark_infor.html", "https://css-benchmark-prd.inforcloudsuite.com/jobs"),
        company="Benchmark",
    ) == []


def test_real_flex_careerarc_capture_contains_job_json():
    captures = json.loads((FIXTURES / "flex_careerarc_xhr.json").read_text())
    posting = next(item for item in captures if "/job_postings" in item["url"])
    payload = json.loads(posting["body"])
    assert len(payload["entries"]) == 25
    assert payload["entries"][0]["brand"]["name"] == "Flex"
    assert payload["entries"][0]["title"]
    assert payload["entries"][0]["apply_url"].startswith("https://app.careerarc.com/job_postings/")


def test_real_jabil_capture_is_workday_shell_for_current_matcher():
    page = response("jabil_career.html", "https://careers.jabil.com/jobs.html")
    roles = extract_roles(page, company="Jabil")
    assert roles
    assert not any("job" in role.url.lower() and role.category == "engineering" for role in roles)
    assert len(build_leads(page, company="Jabil")) == 1
