"""Tests for the Notion payload mapping (build_properties / upsert_lead)."""

import json

from lead_engine.models import Lead
from lead_engine.notion_sync.client import (
    SOURCE_TYPE_NOTION_MAP,
    NotionClient,
    build_background_context,
    build_properties,
    normalize_notion_id,
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


def test_normalize_notion_id_accepts_bare_and_dashed_uuid():
    bare = "63f8848d11c04873926a9c44530f60c9"
    dashed = "63f8848d-11c0-4873-926a-9c44530f60c9"
    assert normalize_notion_id(bare) == dashed
    assert normalize_notion_id(dashed) == dashed


def test_normalize_notion_id_extracts_from_pasted_urls():
    """Real bug: NOTION_DATABASE_ID was set to the full browser URL instead
    of the bare id, and the raw string reached Notion's API unparsed -
    parent.database_id must be a valid uuid, so every create failed with a
    400 the first time this project ever attempted a real Notion write."""
    expected = "63f8848d-11c0-4873-926a-9c44530f60c9"
    assert normalize_notion_id("https://app.notion.com/p/63f8848d11c04873926a9c44530f60c9") == expected
    assert (
        normalize_notion_id(
            "https://www.notion.so/Precision-Assembly-Leads-63f8848d11c04873926a9c44530f60c9?v=abc123"
        )
        == expected
    )


def test_normalize_notion_id_passes_through_non_id_strings():
    """A test fixture id like "db-id" has no 32-hex-char run - must not be
    mangled, just passed through so Notion's own error (not ours) surfaces
    if it's ever genuinely wrong."""
    assert normalize_notion_id("db-id") == "db-id"


def test_notion_client_normalizes_database_id_pasted_as_url():
    client = NotionClient("secret", "https://app.notion.com/p/63f8848d11c04873926a9c44530f60c9")
    assert client.database_id == "63f8848d-11c0-4873-926a-9c44530f60c9"


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


def _properties_transport(properties):
    def transport(method, url, headers, body):
        if "/query" in url:
            return 200, {"results": [{"id": "row-42"}]}
        if method == "GET" and url.endswith("/pages/row-42"):
            return 200, {"properties": properties}
        raise AssertionError(f"unexpected call {method} {url}")

    return transport


def test_get_existing_lead_maps_enrichment_state_back():
    transport = _properties_transport(
        {
            "Lead Name": {"title": [{"plain_text": "Pat Kim"}]},
            "Email": {"email": "pat@seenco.example.com"},
            "Contact Status": {"select": {"name": "valid"}},
            "Status": {"select": {"name": "Reviewed"}},
            "Generated Draft": {"rich_text": [{"plain_text": "Subject: hi\n\nbody"}]},
        }
    )
    client = NotionClient("secret", "db-id", transport=transport)
    existing = client.get_existing_lead("https://seenco.example.com/careers/a")
    assert existing is not None
    assert existing.email == "pat@seenco.example.com"
    assert existing.contact_status == "valid"
    assert existing.status == "Reviewed"
    assert existing.contact_name == "Pat Kim"
    assert existing.is_named is True
    assert existing.generated_draft.startswith("Subject:")


def test_get_existing_lead_returns_none_when_not_found():
    def no_match_transport(method, url, headers, body):
        assert "/query" in url
        return 200, {"results": []}

    client = NotionClient("secret", "db-id", transport=no_match_transport)
    assert client.get_existing_lead("https://unknown.example.com/x") is None


def test_get_existing_lead_tolerates_invalid_select_values():
    """A hand-edited Notion row must not crash the pipeline: invalid select
    values fall back to Lead defaults instead of tripping the validators."""
    transport = _properties_transport(
        {
            "Contact Status": {"select": {"name": "hand-edited-garbage"}},
            "Status": {"select": {"name": "also-garbage"}},
        }
    )
    client = NotionClient("secret", "db-id", transport=transport)
    existing = client.get_existing_lead("https://seenco.example.com/careers/a")
    assert existing.contact_status == "not_attempted"
    assert existing.status == "New"


def test_linkedin_and_profile_summary_mapped_when_present():
    props = build_properties(
        _lead(
            linkedin="https://www.linkedin.com/in/janesmith",
            company_description="Acme builds precision assembly cells for med device OEMs.",
        )
    )
    assert props["LinkedIn"] == {"url": "https://www.linkedin.com/in/janesmith"}
    assert (
        props["Profile Summary"]["rich_text"][0]["text"]["content"]
        == "Acme builds precision assembly cells for med device OEMs."
    )


def test_linkedin_and_profile_summary_omitted_when_blank():
    """URL properties sent as null clear the stored value, and an empty
    rich_text would wipe Profile Summary on re-sync - both stay absent
    instead of blanking data from a previous run."""
    props = build_properties(_lead())
    assert "LinkedIn" not in props
    assert "Profile Summary" not in props
    # ...and Background & Context stays absent when the lead has neither a
    # tech-stack mention nor a pain signal - no filler sentence
    assert "Background & Context" not in build_properties(
        _lead(tech_stack_bottleneck="", pain_signal="")
    )


def test_background_context_combines_tech_then_pain():
    lead = _lead(
        tech_stack_bottleneck="cells run FANUC with PROFINET",
        pain_signal="scrap rate on second shift",
    )
    assert build_background_context(lead) == "cells run FANUC with PROFINET — scrap rate on second shift"
    props = build_properties(lead)
    assert (
        props["Background & Context"]["rich_text"][0]["text"]["content"]
        == "cells run FANUC with PROFINET — scrap rate on second shift"
    )


def test_background_context_single_signal_and_blank_case():
    tech_only = _lead(tech_stack_bottleneck="UR10e cobots on the line", pain_signal="")
    assert build_background_context(tech_only) == "UR10e cobots on the line"
    pain_only = _lead(tech_stack_bottleneck="", pain_signal="rework spike after changeover")
    assert build_background_context(pain_only) == "rework spike after changeover"
    neither = _lead(tech_stack_bottleneck="", pain_signal="")
    assert build_background_context(neither) == ""
    assert "Background & Context" not in build_properties(neither)


def test_get_existing_lead_maps_linkedin_and_profile_summary_back():
    transport = _properties_transport(
        {
            "LinkedIn": {"url": "https://www.linkedin.com/in/patkim"},
            "Profile Summary": {"rich_text": [{"plain_text": "Seen Co assembles PCBAs."}]},
        }
    )
    client = NotionClient("secret", "db-id", transport=transport)
    existing = client.get_existing_lead("https://seenco.example.com/careers/a")
    assert existing.linkedin == "https://www.linkedin.com/in/patkim"
    assert existing.company_description == "Seen Co assembles PCBAs."
