"""Tests for the run-summary email notifier (smtplib fully mocked)."""

import smtplib

import pytest

from lead_engine.config import settings
from lead_engine.notifications.email_notify import _body, _subject, send_run_summary


@pytest.fixture
def smtp_configured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "bot@gmail.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "smtp_from_address", "bot@gmail.com")
    monkeypatch.setattr(settings, "notify_to_address", "human@example.com")


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.calls = []
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(("send", message))


def test_sends_with_expected_subject_and_body(smtp_configured, monkeypatch):
    sent = {}

    class CapturingSMTP(FakeSMTP):
        def send_message(self, message):
            sent["subject"] = message["Subject"]
            sent["from"] = message["From"]
            sent["to"] = message["To"]
            sent["body"] = message.get_content()

    monkeypatch.setattr(smtplib, "SMTP", CapturingSMTP)

    send_run_summary("enrich", {"loaded": 7, "valid": 5, "uncertain": 1, "invalid": 1})

    assert sent["subject"] == "[lead-engine] enrich: 7 loaded, 5 valid, 1 uncertain, 1 invalid"
    assert sent["from"] == "bot@gmail.com"
    assert sent["to"] == "human@example.com"
    assert "loaded: 7" in sent["body"]
    smtp = CapturingSMTP.instances[-1]
    assert smtp.host == "smtp.gmail.com" and smtp.port == 587
    assert ("login", "bot@gmail.com", "app-password") in smtp.calls
    assert "starttls" in smtp.calls


def test_not_configured_is_a_noop(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    called = False

    def boom(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(smtplib, "SMTP", boom)
    send_run_summary("draft", {"drafted": 2})
    assert not called


def test_smtp_failure_is_swallowed(smtp_configured, monkeypatch):
    def exploding(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP", exploding)
    send_run_summary("fanuc", {"scraped": 7})  # must not raise


def test_subject_and_body_formatting():
    counts = {"created": 3, "updated": 1, "errors": 2}
    assert _subject("sync-jsonl", counts) == "[lead-engine] sync-jsonl: 3 created, 1 updated, 2 errors"
    body = _body("sync-jsonl", counts, ["boom one", "boom two"])
    assert "errors (2):" in body and "- boom one" in body


def test_body_lists_per_lead_detail():
    body = _body(
        "targets",
        {"extracted": 2, "enriched": 1},
        None,
        leads=[
            {
                "company": "Acme",
                "title_role": "Quality Engineer",
                "contact_name": "Ravi Patel",
                "email": "ravi@acme.example.com",
            },
            {
                "company": "Beta",
                "title_role": "Process Engineer",
                "contact_name": "(not found)",
                "email": "not_attempted",
            },
        ],
    )
    assert "leads (2):" in body
    assert "- Acme | Quality Engineer | Ravi Patel | ravi@acme.example.com" in body
    # a lead the cap or --no-enrich skipped says so plainly, no blank email
    assert "- Beta | Process Engineer | (not found) | not_attempted" in body
