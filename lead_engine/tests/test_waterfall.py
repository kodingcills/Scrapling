"""Tests for the Findymail contact-waterfall enrichment worker.

All Findymail HTTP calls go through an injected transport — no network, no
API key needed (same pattern as test_notion_payload.py's Notion mocking).
"""

import pytest

from lead_engine.enrichment.waterfall import (
    FindymailClient,
    enrich_batch,
    enrich_lead,
)
from lead_engine.models import Lead


class FakeFindymailTransport:
    """Records calls; returns canned responses per endpoint."""

    def __init__(
        self,
        credits=None,
        name_results=None,
        domain_results=None,
        verify_results=None,
        error_status=None,
    ):
        self.calls = []
        self.credits = credits or {"credits": 100, "verifier_credits": 100}
        self.name_results = name_results or {}
        self.domain_results = domain_results or {}
        self.verify_results = verify_results or {}
        self.error_status = error_status

    def __call__(self, method, url, headers, json_body):
        self.calls.append((method, url, json_body))
        assert headers["Authorization"] == "Bearer test-key"

        if self.error_status is not None:
            return self.error_status, {}

        if url.endswith("/credits"):
            return 200, dict(self.credits)
        if url.endswith("/search/name"):
            key = json_body["name"]
            hit = self.name_results.get(key)
            return 200, {"contact": hit} if hit else {"contact": None}
        if url.endswith("/search/domain"):
            key = json_body["domain"]
            hits = self.domain_results.get(key, [])
            return 200, {"contacts": hits}
        if url.endswith("/verify"):
            email = json_body["email"]
            return 200, {"email": email, "verified": self.verify_results.get(email, True)}
        raise AssertionError(f"unexpected URL {url}")

    def endpoint_calls(self, fragment):
        return [call for call in self.calls if fragment in call[1]]


def make_client(transport):
    return FindymailClient(api_key="test-key", transport=transport)


def named_lead():
    return Lead(
        company="Acme Robotics",
        source_url="https://acmerobotics.example.com/team/jane",
        contact_name="Jane Smith",
        is_named=True,
        title_role="Quality Manager",
        persona_type="Executive",
        status="New",
    )


def account_lead():
    return Lead(
        company="Beta Automation",
        source_url="https://www.betaautomation.example.com/careers/controls-engineer",
        contact_name="",
        is_named=False,
        title_role="Quality Engineer",
        persona_type="Practitioner",
    )


# ---------------------------------------------------------------------------
# Named-lead path: search/name
# ---------------------------------------------------------------------------


def test_named_lead_uses_search_name_and_verifies():
    transport = FakeFindymailTransport(
        name_results={"Jane Smith": {"name": "Jane Smith", "email": "jane@acmerobotics.example.com"}},
        verify_results={"jane@acmerobotics.example.com": True},
    )
    result = enrich_lead(named_lead(), make_client(transport))

    assert len(transport.endpoint_calls("search/name")) == 1
    assert not transport.endpoint_calls("search/domain")
    # Domain was parsed from source_url with www. stripped where present
    name_call = transport.endpoint_calls("search/name")[0]
    assert name_call[2] == {"name": "Jane Smith", "domain": "acmerobotics.example.com"}
    assert len(transport.endpoint_calls("/verify")) == 1
    assert result.email == "jane@acmerobotics.example.com"
    assert result.contact_status == "valid"


# ---------------------------------------------------------------------------
# Account-level path: search/domain + name backfill
# ---------------------------------------------------------------------------


def test_account_lead_uses_search_domain_and_backfills_name():
    transport = FakeFindymailTransport(
        domain_results={
            "betaautomation.example.com": [
                {"name": "Ravi Patel", "email": "ravi@betaautomation.example.com"}
            ]
        },
        verify_results={"ravi@betaautomation.example.com": True},
    )
    result = enrich_lead(account_lead(), make_client(transport))

    assert len(transport.endpoint_calls("search/domain")) == 1
    domain_call = transport.endpoint_calls("search/domain")[0]
    assert domain_call[2]["roles"] == ["Quality Engineer"]
    assert domain_call[2] == {
        "domain": "betaautomation.example.com",
        "roles": ["Quality Engineer"],
    }
    assert result.contact_name == "Ravi Patel"
    assert result.is_named is True
    assert result.email == "ravi@betaautomation.example.com"
    assert result.contact_status == "valid"


# ---------------------------------------------------------------------------
# Verification gating
# ---------------------------------------------------------------------------


def test_unverified_email_maps_to_uncertain_not_invalid():
    transport = FakeFindymailTransport(
        name_results={"Jane Smith": {"name": "Jane Smith", "email": "catchall@acmerobotics.example.com"}},
        verify_results={"catchall@acmerobotics.example.com": False},
    )
    result = enrich_lead(named_lead(), make_client(transport))
    # Catch-all domains are often reachable; keep the email, flag for review
    assert result.email == "catchall@acmerobotics.example.com"
    assert result.contact_status == "uncertain"


def test_no_match_maps_to_invalid_with_empty_email():
    transport = FakeFindymailTransport()
    result = enrich_lead(account_lead(), make_client(transport))
    assert result.email == ""
    assert result.contact_status == "invalid"


def test_idempotent_rerun_skips_valid_leads():
    lead = named_lead()
    lead.email = "jane@acmerobotics.example.com"
    lead.contact_status = "valid"
    transport = FakeFindymailTransport()
    result = enrich_lead(lead, make_client(transport))

    assert transport.calls == []
    assert result is lead or (result.email == lead.email and result.contact_status == "valid")


def test_stale_email_gets_reverified_without_refinding():
    lead = named_lead()
    lead.email = "old@acmerobotics.example.com"
    lead.contact_status = "uncertain"
    transport = FakeFindymailTransport(verify_results={"old@acmerobotics.example.com": True})
    result = enrich_lead(lead, make_client(transport))

    assert not transport.endpoint_calls("search/")
    assert len(transport.endpoint_calls("/verify")) == 1
    assert result.contact_status == "valid"


# ---------------------------------------------------------------------------
# Batch credits pre-check
# ---------------------------------------------------------------------------


def test_batch_truncates_on_low_credits_with_warning(caplog):
    leads = [account_lead() for _ in range(10)]
    for index, lead in enumerate(leads):
        lead.source_url = f"https://beta{index}.example.com/x"

    # 2 estimated calls per lead -> only 3 leads affordable with 6 usable credits
    transport = FakeFindymailTransport(
        credits={"credits": 6, "verifier_credits": 6},
        domain_results={f"beta{i}.example.com": [] for i in range(10)},
    )

    with caplog.at_level("WARNING"):
        results = enrich_batch(leads, make_client(transport))

    searched = transport.endpoint_calls("search/domain")
    assert len(searched) == 3
    assert len(results) == 10  # nothing dropped silently
    skipped = [lead for lead in results if lead.contact_status == "no_credits"]
    assert len(skipped) == 7
    assert any("skipping 7" in message for message in caplog.messages)


def test_batch_sufficient_credits_processes_everything():
    leads = [account_lead() for _ in range(4)]
    for index, lead in enumerate(leads):
        lead.source_url = f"https://beta{index}.example.com/x"
    transport = FakeFindymailTransport(
        credits={"credits": 50, "verifier_credits": 50},
        domain_results={f"beta{i}.example.com": [] for i in range(4)},
    )
    results = enrich_batch(leads, make_client(transport))
    assert len(transport.endpoint_calls("search/domain")) == 4
    assert all(lead.contact_status == "invalid" for lead in results)


def test_batch_marks_unprocessed_leads_no_credits():
    leads = [account_lead() for _ in range(5)]
    transport = FakeFindymailTransport(credits={"credits": 2, "verifier_credits": 2})
    results = enrich_batch(leads, make_client(transport))
    statuses = [lead.contact_status for lead in results]
    assert statuses.count("no_credits") >= 3
