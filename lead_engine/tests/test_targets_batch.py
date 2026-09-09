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

    args = argparse.Namespace(targets_file=str(targets_path), out=str(out_path), no_sync=True)
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

    args = argparse.Namespace(targets_file=str(targets_path), out=str(out_path), no_sync=True)
    exit_code = main_module.cmd_targets(args)

    assert exit_code == 0
    assert calls == ["https://dual.example.com/careers", "https://dual.example.com/team"]
    leads = main_module.load_leads(out_path)
    assert {lead.source_type for lead in leads} == {"career_page", "team_page"}


def test_cmd_targets_missing_file_returns_error_exit_code(tmp_path):
    args = argparse.Namespace(targets_file=str(tmp_path / "nope.yaml"), out=None, no_sync=True)
    assert main_module.cmd_targets(args) == 1
