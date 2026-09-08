"""Tests against live career captures from the 2026-09-06 verification run."""

import json
from pathlib import Path

from scrapling.engines.toolbelt.custom import Response

from lead_engine.scrapers.career_pages import (
    build_leads,
    extract_roles,
    extract_roles_from_captured_xhr,
)

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


class _CapturedXhr:
    def __init__(self, url, body, content_type="application/json"):
        self.url = url
        self.body = body
        self.headers = {"content-type": content_type}


def _response_with_xhr(page_name, xhr_name, url):
    page = response(page_name, url)
    for capture in json.loads((FIXTURES / xhr_name).read_text()):
        page.captured_xhr.append(
            _CapturedXhr(capture["url"], capture["body"], capture.get("content_type", "application/json"))
        )
    return page


def test_generic_xhr_sniffer_extracts_flex_postings_and_leads():
    response = _response_with_xhr(
        "flex_careerarc.html", "flex_careerarc_xhr.json", "https://flex.com/careers"
    )
    roles = extract_roles_from_captured_xhr(response, company="Flex")
    assert len(roles) == 25
    assert all(role.company == "Flex" for role in roles)
    assert all(role.url.startswith("https://app.careerarc.com/job_postings/") for role in roles)

    leads = build_leads(response, company="Flex")
    assert len(leads) == 7
    by_url = {lead.source_url.split("?")[0]: lead for lead in leads}
    process = [lead for lead in leads if lead.title_role == "Process Engineer"]
    quality = [lead for lead in leads if lead.title_role == "Quality Engineer"]
    assert len(process) == 4
    assert len(quality) == 2
    assert all(lead.buyer_type == "Gatekeeper - Process/Mfg Eng" for lead in process)
    assert all(lead.buyer_type == "Buyer - Quality" for lead in quality)
    assert all(lead.source_type == "career_page" for lead in leads)
    # The one remaining lead is "Strategic supply chain manager": engineering/
    # buyer category but outside the target title_role vocabulary.
    other = [lead for lead in leads if lead.title_role == "Other"]
    assert len(other) == 1
    assert other[0].buyer_type == "Unclassified"
    assert by_url["https://app.careerarc.com/job_postings/7714978"].title_role == "Quality Engineer"


def test_generic_xhr_sniffer_finds_nothing_in_jabil_taxonomy_xhrs():
    # Jabil's captured XHRs are taxonomy/category feeds without posting-shaped
    # records; a zero result here is correct, not a sniffer failure.
    response = _response_with_xhr(
        "jabil_career.html", "jabil_xhr.json", "https://careers.jabil.com/jobs.html"
    )
    assert extract_roles_from_captured_xhr(response, company="Jabil") == []


def test_real_jabil_capture_is_workday_shell_for_current_matcher():
    page = response("jabil_career.html", "https://careers.jabil.com/jobs.html")
    roles = extract_roles(page, company="Jabil")
    assert roles
    assert not any("job" in role.url.lower() and role.category == "engineering" for role in roles)
    assert len(build_leads(page, company="Jabil")) == 1
