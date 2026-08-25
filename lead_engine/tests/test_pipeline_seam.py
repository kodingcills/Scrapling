"""Cross-module seam test: scraper -> enrichment -> drafter -> Notion mapping.

Each module had its own isolated tests; this proves the Lead object itself
flows through the whole pipeline without field drift. Not mocked at the
Lead level: only the network boundaries (Findymail HTTP) are faked, and the
drafter runs in template mode (no Anthropic key).
"""

import json

import pytest

from scrapling.engines.toolbelt.custom import Response

from lead_engine.drafters.slot_drafter import validate_draft, draft_for_lead
from lead_engine.enrichment.waterfall import FindymailClient, enrich_lead
from lead_engine.models import Lead
from lead_engine.notion_sync.client import build_properties
from lead_engine.scrapers.career_pages import build_leads

CAREER_HTML = """
<h1>Open Positions</h1>
<a href="/jobs/quality-engineer">Quality Engineer</a>
<a href="/jobs/senior-buyer">Senior Buyer</a>
<a href="/jobs/benefits">Benefits Overview</a>
"""


def _career_response() -> Response:
    return Response(
        url="https://acmerobotics.example.com/careers",
        content=CAREER_HTML.encode("utf-8"),
        status=200,
        reason="OK",
        encoding="utf-8",
        cookies={},
        headers={"content-type": "text/html"},
        request_headers={},
        method="GET",
    )


class FakeFindymailTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, json_body):
        self.calls.append((method, url, json_body))
        if url.endswith("/credits"):
            return 200, {"credits": 100, "verifier_credits": 100}
        if url.endswith("/search/domain"):
            assert json_body["domain"] == "acmerobotics.example.com"
            return 200, {
                "contacts": [
                    {"name": "Ravi Patel", "email": "ravi@acmerobotics.example.com"}
                ]
            }
        if url.endswith("/verify"):
            return 200, {"email": json_body["email"], "verified": True}
        raise AssertionError(f"unexpected URL {url}")


def test_career_scrape_enrich_draft_notion_seam(monkeypatch):
    monkeypatch.setattr("lead_engine.config.settings.anthropic_api_key", "")

    # 1. Scrape: exactly what career_pages.build_leads produces from real HTML
    leads = build_leads(_career_response(), company="Acme Robotics")
    assert leads, "scraper produced no leads"
    lead = next(lead for lead in leads if lead.title_role == "Quality Engineer")
    # Account-level until enrichment names it
    assert isinstance(lead, Lead)
    assert lead.is_named is False
    assert lead.contact_name == ""
    original_url = lead.source_url

    # Round-trip through the jsonl representation like main.py does
    lead = Lead.from_dict(json.loads(json.dumps(lead.to_dict())))
    assert lead.source_url == original_url

    # 2. Enrich: mocked Findymail transport, real enrich_lead logic
    transport = FakeFindymailTransport()
    enriched = enrich_lead(lead, FindymailClient(api_key="test-key", transport=transport))
    assert enriched.contact_name == "Ravi Patel"
    assert enriched.is_named is True
    assert enriched.email == "ravi@acmerobotics.example.com"
    assert enriched.contact_status == "valid"

    # 3. Draft: template mode, must pass its own validator
    drafted = draft_for_lead(enriched)
    assert drafted.generated_draft.startswith("Subject:")
    assert drafted.status == "Drafted"
    subject, _, body = drafted.generated_draft.partition("\n\n")
    ok, failures = validate_draft(subject.removeprefix("Subject: "), body)
    assert ok, failures

    # 4. Notion mapping: title property key is literally "Lead Name"
    props = build_properties(drafted)
    assert "Lead Name" in props, f"title property drifted: {sorted(props)}"
    assert props["Lead Name"]["title"][0]["text"]["content"] == "Ravi Patel"
    assert props["Email"] == {"email": "ravi@acmerobotics.example.com"}
    assert props["Contact Status"] == {"select": {"name": "valid"}}
    assert props["Generated Draft"]["rich_text"][0]["text"]["content"] == drafted.generated_draft
