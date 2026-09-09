"""Tests for the `targets` batch command: _load_targets() validation and
cmd_targets()'s per-company error isolation.

No network, no browser - LeadEngineFetcher.fetch and build_leads() are
monkeypatched, same pattern as the other CLI-facing tests in this suite.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as main_module  # noqa: E402
from lead_engine.enrichment.waterfall import FindymailClient as RealFindymailClient  # noqa: E402
from lead_engine.models import Lead  # noqa: E402


def _write_yaml(tmp_path, data):
    path = tmp_path / "targets.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


# ---------------------------------------------------------------------------
# _load_targets(): validation
# ---------------------------------------------------------------------------


def test_load_targets_happy_path(tmp_path):
    path = _write_yaml(
        tmp_path,
        {
            "targets": [
                {"company": "Acme", "career_url": "https://acme.example.com/careers"},
                {"company": "Beta", "team_url": "https://beta.example.com/team"},
                {
                    "company": "Gamma",
                    "career_url": "https://gamma.example.com/careers",
                    "team_url": "https://gamma.example.com/team",
                },
            ]
        },
    )
    targets = main_module._load_targets(path)
    assert len(targets) == 3
    assert targets[0] == {"company": "Acme", "career_url": "https://acme.example.com/careers", "team_url": ""}
    assert targets[1] == {"company": "Beta", "career_url": "", "team_url": "https://beta.example.com/team"}


def test_load_targets_rejects_missing_top_level_key(tmp_path):
    path = _write_yaml(tmp_path, {"companies": []})
    with pytest.raises(ValueError, match="expected a top-level 'targets' list"):
        main_module._load_targets(path)


def test_load_targets_rejects_empty_list(tmp_path):
    path = _write_yaml(tmp_path, {"targets": []})
    with pytest.raises(ValueError, match="expected a top-level 'targets' list"):
        main_module._load_targets(path)


def test_load_targets_rejects_entry_missing_company(tmp_path):
    path = _write_yaml(tmp_path, {"targets": [{"career_url": "https://x.example.com"}]})
    with pytest.raises(ValueError, match="must be a mapping with at least a 'company' key"):
        main_module._load_targets(path)


def test_load_targets_rejects_entry_with_no_urls(tmp_path):
    path = _write_yaml(tmp_path, {"targets": [{"company": "NoUrls"}]})
    with pytest.raises(ValueError, match="has neither career_url nor team_url"):
        main_module._load_targets(path)


def test_load_targets_against_the_real_committed_file():
    """The actual file this ships with must stay loadable and non-empty."""
    targets = main_module._load_targets(Path(__file__).resolve().parents[1] / "data" / "target_companies.yaml")
    assert len(targets) >= 10
    assert all(t["company"] and t["career_url"] for t in targets)


# ---------------------------------------------------------------------------
# cmd_targets(): per-company error isolation
# ---------------------------------------------------------------------------


class _FakeResponse:
    pass


def _patch_crawls(monkeypatch, career=None, team=None):
    monkeypatch.setattr(
        "lead_engine.scrapers.career_pages.crawl_leads",
        career or (lambda url, company="": []),
    )
    monkeypatch.setattr(
        "lead_engine.scrapers.team_pages.crawl_leads",
        team or (lambda url, company="": []),
    )


def test_cmd_targets_isolates_one_company_failure(tmp_path, monkeypatch, caplog):
    """Real-world scenario this exists for: one target's site is down or
    times out. That must not stop the rest of the batch, and it must show
    up as a reported error, not a silent drop."""
    targets_path = _write_yaml(
        tmp_path,
        {
            "targets": [
                {"company": "Good Co", "career_url": "https://good.example.com/careers"},
                {"company": "Broken Co", "career_url": "https://broken.example.com/careers"},
            ]
        },
    )
    out_path = tmp_path / "out.jsonl"

    def fake_career_crawl(url, company="", **kwargs):
        if "broken" in url:
            raise RuntimeError("connection timed out")
        return [Lead(company=company, source_url=url, title_role="Quality Engineer")]

    monkeypatch.setattr(main_module, "send_run_summary", lambda *a, **kw: None)
    _patch_crawls(monkeypatch, career=fake_career_crawl)

    args = argparse.Namespace(
        targets_file=str(targets_path), out=str(out_path), no_sync=True, no_enrich=True, max_enrich=10
    )
    exit_code = main_module.cmd_targets(args)

    assert exit_code == 0
    leads = main_module.load_leads(out_path)
    assert len(leads) == 1
    assert leads[0].company == "Good Co"
    assert "Broken Co" in caplog.text
    assert "connection timed out" in caplog.text


def test_cmd_targets_runs_both_career_and_team_urls_for_one_company(tmp_path, monkeypatch):
    targets_path = _write_yaml(
        tmp_path,
        {
            "targets": [
                {
                    "company": "Dual Co",
                    "career_url": "https://dual.example.com/careers",
                    "team_url": "https://dual.example.com/team",
                }
            ]
        },
    )
    out_path = tmp_path / "out.jsonl"
    calls = []

    def fake_career_crawl(url, company="", **kwargs):
        calls.append(url)
        return [Lead(company=company, source_type="career_page", title_role="Quality Engineer")]

    def fake_team_crawl(url, company="", **kwargs):
        calls.append(url)
        return [Lead(company=company, source_type="team_page", title_role="Quality Manager", is_named=True)]

    monkeypatch.setattr(main_module, "send_run_summary", lambda *a, **kw: None)
    _patch_crawls(monkeypatch, career=fake_career_crawl, team=fake_team_crawl)

    args = argparse.Namespace(
        targets_file=str(targets_path), out=str(out_path), no_sync=True, no_enrich=True, max_enrich=10
    )
    exit_code = main_module.cmd_targets(args)

    assert exit_code == 0
    assert calls == ["https://dual.example.com/careers", "https://dual.example.com/team"]
    leads = main_module.load_leads(out_path)
    assert {lead.source_type for lead in leads} == {"career_page", "team_page"}


def test_cmd_targets_missing_file_returns_error_exit_code(tmp_path):
    args = argparse.Namespace(targets_file=str(tmp_path / "nope.yaml"), out=None, no_sync=True)
    assert main_module.cmd_targets(args) == 1


# ---------------------------------------------------------------------------
# cmd_targets(): Notion dedup, --max-enrich cap, --no-enrich
# ---------------------------------------------------------------------------


class FakeFindymailTransport:
    def __init__(self, credits=100):
        self.credits = credits
        self.calls = []

    def __call__(self, method, url, headers, json_body):
        self.calls.append((method, url, json_body))
        if url.endswith("/credits"):
            return 200, {"credits": self.credits, "verifier_credits": self.credits}
        if url.endswith("/search/domain"):
            return 200, {"contacts": [{"name": "Ravi Patel", "email": f"ravi@{json_body['domain']}"}]}
        if url.endswith("/search/name"):
            return 200, {"contact": {"name": "Ravi Patel", "email": f"ravi@{json_body['domain']}"}}
        if url.endswith("/verify"):
            return 200, {"verified": True}
        raise AssertionError(f"unexpected URL {url}")


def _fake_notion(seen_state):
    class FakeNotionClient:
        upserted = []

        def __init__(self, token, database_id, transport=None):
            pass

        def get_existing_lead(self, source_url):
            return seen_state.get(source_url)

        def upsert_lead(self, lead):
            FakeNotionClient.upserted.append(lead)
            return "page-id"

    return FakeNotionClient


def _wire_batch_fakes(monkeypatch, seen_state, transport):
    from lead_engine.config import settings

    monkeypatch.setattr(settings, "notion_token", "test-token")
    monkeypatch.setattr(settings, "notion_database_id", "test-db-id")
    monkeypatch.setattr(settings, "findymail_api_key", "test-key")
    monkeypatch.setattr("lead_engine.notion_sync.client.NotionClient", _fake_notion(seen_state))
    monkeypatch.setattr(
        "lead_engine.enrichment.waterfall.FindymailClient",
        lambda: RealFindymailClient(api_key="test-key", transport=transport),
    )
    monkeypatch.setattr(main_module, "send_run_summary", lambda *a, **kw: None)


def _scraped_leads():
    leads = []
    for index in range(13):
        leads.append(
            Lead(
                company="New Co",
                source_url=f"https://newco.example.com/careers/req{index}",
                title_role="Quality Engineer",
            )
        )
    leads.append(Lead(company="Seen Co", source_url="https://seenco.example.com/careers/reqA", title_role="Quality Manager"))
    leads.append(Lead(company="Seen Co", source_url="https://seenco.example.com/careers/reqB", title_role="Quality Engineer"))
    return leads


def test_cmd_targets_dedup_caps_and_syncs_everything(tmp_path, monkeypatch, caplog):
    """13 new + 2 already-in-Notion leads, --max-enrich 10: only the new
    leads may reach Findymail, only 10 of them, and every lead still gets
    synced (seen ones with their preserved Notion state)."""
    targets_path = _write_yaml(
        tmp_path,
        {"targets": [{"company": "Batch Co", "career_url": "https://newco.example.com/careers"}]},
    )
    out_path = tmp_path / "out.jsonl"

    seen_state = {
        "https://seenco.example.com/careers/reqA": Lead(
            company="Seen Co",
            source_url="https://seenco.example.com/careers/reqA",
            contact_name="Pat Kim",
            is_named=True,
            email="pat@seenco.example.com",
            contact_status="valid",
            status="Reviewed",
            generated_draft="Subject: hi\n\nbody",
        ),
    }
    transport = FakeFindymailTransport()
    _wire_batch_fakes(monkeypatch, seen_state, transport)
    _patch_crawls(
        monkeypatch,
        career=lambda url, company="", **kwargs: _scraped_leads(),
    )

    args = argparse.Namespace(
        targets_file=str(targets_path), out=str(out_path), no_sync=False, no_enrich=False, max_enrich=10
    )
    assert main_module.cmd_targets(args) == 0

    search_domains = {body["domain"] for _, url, body in transport.calls if url.endswith("/search/domain")}
    assert search_domains == {"newco.example.com"}, "already-seen lead reached Findymail"
    search_calls = [call for call in transport.calls if call[1].endswith("/search/domain")]
    assert len(search_calls) == 10, f"expected exactly 10 finder calls, got {len(search_calls)}"

    assert "4 new lead(s) over the --max-enrich cap of 10" in caplog.text

    from lead_engine.notion_sync.client import NotionClient

    assert len(NotionClient.upserted) == 15
    synced_by_url = {lead.source_url: lead for lead in NotionClient.upserted}
    seen = synced_by_url["https://seenco.example.com/careers/reqA"]
    assert seen.email == "pat@seenco.example.com"
    assert seen.contact_status == "valid"
    assert seen.status == "Reviewed"
    assert seen.generated_draft == "Subject: hi\n\nbody"
    enriched = synced_by_url["https://newco.example.com/careers/req0"]
    assert enriched.email == "ravi@newco.example.com"
    assert enriched.contact_status == "valid"
    assert enriched.contact_name == "Ravi Patel"
    skipped = synced_by_url["https://newco.example.com/careers/req12"]
    assert skipped.email == ""
    assert skipped.contact_status == "not_attempted"

    saved = {lead.source_url: lead for lead in main_module.load_leads(out_path)}
    assert len(saved) == 15
    assert saved["https://newco.example.com/careers/req3"].email == "ravi@newco.example.com"
    assert saved["https://seenco.example.com/careers/reqB"].contact_status == "not_attempted"


def test_merge_existing_state_never_takes_company_name_as_contact():
    """Notion's "Lead Name" title falls back to the company name for
    account-level rows; merging that back must not mark the lead is_named
    and steer future enrichment toward search_name with the company name."""
    lead = Lead(company="Key Tronic Corporation", source_url="https://www.keytronic.com/quality-engineer/")
    existing = Lead(source_url=lead.source_url, contact_name="Key Tronic Corporation", is_named=True)
    main_module._merge_existing_state(lead, existing)
    assert lead.contact_name == ""
    assert lead.is_named is False


def test_cmd_targets_no_enrich_spends_zero_findymail_calls(tmp_path, monkeypatch):
    targets_path = _write_yaml(
        tmp_path,
        {"targets": [{"company": "Batch Co", "career_url": "https://newco.example.com/careers"}]},
    )
    out_path = tmp_path / "out.jsonl"

    transport = FakeFindymailTransport()
    _wire_batch_fakes(monkeypatch, {}, transport)
    _patch_crawls(monkeypatch, career=lambda url, company="", **kwargs: _scraped_leads())

    args = argparse.Namespace(
        targets_file=str(targets_path), out=str(out_path), no_sync=False, no_enrich=True, max_enrich=10
    )
    assert main_module.cmd_targets(args) == 0

    assert transport.calls == [], "--no-enrich must not touch Findymail at all"
    from lead_engine.notion_sync.client import NotionClient

    assert len(NotionClient.upserted) == 15
    assert all(lead.contact_status == "not_attempted" for lead in NotionClient.upserted)


def test_cmd_targets_dedup_without_notion_still_caps(tmp_path, monkeypatch, caplog):
    """No Notion configured -> no dedup is possible, every lead counts as
    new, and the cap is the last line of credit defense."""
    from lead_engine.config import settings

    targets_path = _write_yaml(
        tmp_path,
        {"targets": [{"company": "Batch Co", "career_url": "https://newco.example.com/careers"}]},
    )
    out_path = tmp_path / "out.jsonl"

    transport = FakeFindymailTransport()
    monkeypatch.setattr(settings, "notion_token", "")
    monkeypatch.setattr(settings, "notion_database_id", "")
    monkeypatch.setattr(settings, "findymail_api_key", "test-key")
    monkeypatch.setattr(
        "lead_engine.enrichment.waterfall.FindymailClient",
        lambda: RealFindymailClient(api_key="test-key", transport=transport),
    )
    monkeypatch.setattr(main_module, "send_run_summary", lambda *a, **kw: None)
    _patch_crawls(monkeypatch, career=lambda url, company="", **kwargs: _scraped_leads())

    args = argparse.Namespace(
        targets_file=str(targets_path), out=str(out_path), no_sync=True, no_enrich=False, max_enrich=5
    )
    assert main_module.cmd_targets(args) == 0

    assert "cannot dedup against Notion" in caplog.text
    search_calls = [call for call in transport.calls if call[1].endswith("/search/domain")]
    assert len(search_calls) == 5
    assert "10 new lead(s) over the --max-enrich cap of 5" in caplog.text
