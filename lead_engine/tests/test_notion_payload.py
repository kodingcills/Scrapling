"""Tests for the Notion payload mapping (build_properties / upsert_lead)."""

import json

from lead_engine.models import Lead
from lead_engine.notion_sync.client import (
    SOURCE_TYPE_NOTION_MAP,
    NotionClient,
    build_properties,
)


def _lead(**overrides):
    base = dict(
        company="Acme Robotics",
        source_url="https://acme.example.com/team/jane",
        contact_name="Jane Smith",
        title_role="Quality Manager",
        buyer_type="Buyer - Quality",
        source_type="team_page",
        operational_trigger="plant expansion: new welding cell",
        pain_signal="scrap rate on second shift",
        persona_type="Executive",
        tech_stack_bottleneck="cells run FANUC with PROFINET",
        generated_draft="Subject: acme — welding cell\n\nDraft body.",
        status="Drafted",
    )
    base.update(overrides)
    return Lead(**base)


def test_status_is_a_plain_select_with_new_default():
    props = build_properties(_lead(status="New"))
    assert props["Status"] == {"select": {"name": "New"}}
    # The old {"status": {"name": ...}} property type must never appear
    assert "status" not in props
    assert Lead().status == "New"


def test_new_lead_columns_are_mapped():
    lead = _lead()
    props = build_properties(lead)
    assert props["Persona Type"] == {"select": {"name": "Executive"}}
    assert (
        props["Tech Stack / Bottleneck"]["rich_text"][0]["text"]["content"]
        == "cells run FANUC with PROFINET"
    )
    assert props["Generated Draft"]["rich_text"][0]["text"]["content"].startswith("Subject:")
    assert props["Title / Role"] == {"select": {"name": "Quality Manager"}}


def test_email_property_present_only_when_set():
    with_email = build_properties(_lead(email="jane@acme.example.com"))
    assert with_email["Email"] == {"email": "jane@acme.example.com"}
    without_email = build_properties(_lead(email=""))
    assert "Email" not in without_email


def test_contact_status_select_mapped():
    props = build_properties(_lead(contact_status="valid"))
    assert props["Contact Status"] == {"select": {"name": "valid"}}


def test_source_type_maps_to_real_notion_options():
    assert SOURCE_TYPE_NOTION_MAP["career_page"] == "Career Page / Job Posting"
    assert SOURCE_TYPE_NOTION_MAP["integrator_directory"] == "Integrator Directory"
    # team_page has no clean existing Notion option; "Other" is the deliberate
    # least-wrong fit, not an accident.
    assert SOURCE_TYPE_NOTION_MAP["team_page"] == "Other"
    for source_type, notion_name in SOURCE_TYPE_NOTION_MAP.items():
        props = build_properties(_lead(source_type=source_type))
        assert props["Source Type"] == {"select": {"name": notion_name}}


def test_source_type_unknown_value_falls_back_to_other():
    lead = _lead(source_type="career_page")
    object.__setattr__(lead, "source_type", "trade_show")  # bypass the validator
    props = build_properties(lead)
    assert props["Source Type"] == {"select": {"name": "Other"}}


def test_payload_serializes_cleanly():
    json.dumps(build_properties(_lead()))


class RecordingTransport:
    def __init__(self, existing_page_id=None):
        self.existing_page_id = existing_page_id
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, json.loads(body) if body else None))
        if "/query" in url:
            results = [{"id": self.existing_page_id}] if self.existing_page_id else []
            return 200, {"results": results}
        if method == "PATCH":
            page_id = self.existing_page_id or ""
            return 200, {"id": page_id}
        return 201, {"id": "created-page-1"}


def test_upsert_lead_updates_in_place_by_source_url():
    transport = RecordingTransport(existing_page_id="row-42")
    client = NotionClient("secret", "db-id", transport=transport)
    page_id = client.upsert_lead(_lead())

    assert page_id == "row-42"
    methods_and_urls = [(m, u) for m, u, _ in transport.calls]
    assert ("POST", "https://api.notion.com/v1/databases/db-id/query") in methods_and_urls
    assert ("PATCH", "https://api.notion.com/v1/pages/row-42") in methods_and_urls
    query_call = next(c for c in transport.calls if "/query" in c[1])
    assert query_call[2]["filter"]["property"] == "Source URL"


def test_upsert_lead_creates_when_no_match():
    transport = RecordingTransport(existing_page_id=None)
    client = NotionClient("secret", "db-id", transport=transport)
    page_id = client.upsert_lead(_lead())
    assert page_id == "created-page-1"
    create_call = next(c for c in transport.calls if c[0] == "POST" and c[1].endswith("/pages"))
    assert create_call[2]["properties"]["Status"] == {"select": {"name": "Drafted"}}
