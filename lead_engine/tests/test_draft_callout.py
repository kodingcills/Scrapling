"""Tests for the draft callout page-body block (mocked Notion transport)."""

import json

import pytest

from lead_engine.models import Lead
from lead_engine.notion_sync.client import DRAFT_CALLOUT_MARKER, NotionClient


class CalloutTransport:
    """Simulates the blocks endpoints around a set of existing children."""

    def __init__(self, existing_children=None):
        self.children = list(existing_children or [])
        self.calls = []

    def __call__(self, method, url, headers, body):
        payload = json.loads(body) if body else None
        self.calls.append((method, url, payload))
        if "/query" in url and url.endswith("/query"):
            return 200, {"results": []}
        if url.endswith("/pages") and method == "POST":
            return 201, {"id": "page-1"}
        if "/pages/" in url and method == "PATCH":
            return 200, {"id": url.rsplit("/", 1)[-1]}
        if url.endswith("/children") and method == "GET":
            return 200, {"results": self.children}
        if url.endswith("/children") and method == "PATCH":
            self.children.extend(payload["children"])
            return 200, {"results": payload["children"]}
        if "/blocks/" in url and method == "PATCH":
            block_id = url.rsplit("/", 1)[-1]
            for block in self.children:
                if block["id"] == block_id:
                    block.update(payload)
            return 200, {"id": block_id}
        raise AssertionError(f"unexpected {method} {url}")

    def callout_blocks(self):
        return [b for b in self.children if b.get("type") == "callout"]


def _lead_with_draft():
    return Lead(
        company="Acme",
        source_url="https://acme.example.com/team/jane",
        contact_name="Jane Smith",
        generated_draft="Subject: acme\n\nDraft body.",
        status="Drafted",
    )


def _callout(block_id, content):
    return {
        "object": "block",
        "id": block_id,
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "plain_text": content, "text": {"content": content}}],
            "icon": {"type": "emoji", "emoji": "🎯"},
        },
    }


def test_no_existing_callout_appends_new_one():
    transport = CalloutTransport(existing_children=[])
    client = NotionClient("secret", "db-id", transport=transport)

    client.upsert_lead(_lead_with_draft())

    appended = [c for m, u, c in transport.calls if u.endswith("/children") and c and "children" in c]
    assert len(appended) == 1
    block = appended[0]["children"][0]
    assert block["type"] == "callout"
    assert block["callout"]["icon"]["emoji"] == "🎯"
    assert block["callout"]["rich_text"][0]["text"]["content"].startswith(DRAFT_CALLOUT_MARKER)


def test_existing_callout_with_marker_is_patched_not_duplicated():
    transport = CalloutTransport(
        existing_children=[_callout("ours-1", DRAFT_CALLOUT_MARKER + "old draft text")]
    )
    client = NotionClient("secret", "db-id", transport=transport)
    before = len(transport.children)

    client.upsert_lead(_lead_with_draft())

    patch_calls = [
        (u, p)
        for m, u, p in transport.calls
        if "/blocks/ours-1" in u and not u.endswith("/children")
    ]
    assert patch_calls, "existing callout should be updated in place"
    updated = patch_calls[0][1]["callout"]["rich_text"][0]["text"]["content"]
    assert "Draft body." in updated
    # No second callout was appended
    assert [c for m, u, c in transport.calls if u.endswith("/children") and c and "children" in c] == []
    assert len(transport.children) == before


def test_human_block_without_marker_is_left_alone():
    human_note = _callout("human-1", "Jane is on leave until August — try Bob instead.")
    transport = CalloutTransport(existing_children=[human_note])
    client = NotionClient("secret", "db-id", transport=transport)

    client.upsert_lead(_lead_with_draft())

    # The human's block must never be PATCHed
    assert not any("/blocks/human-1" in u for m, u, p in transport.calls if not u.endswith("/children"))
    # A NEW callout with our marker is appended alongside it
    appended = [c for m, u, c in transport.calls if u.endswith("/children") and c and "children" in c]
    assert len(appended) == 1
    assert appended[0]["children"][0]["callout"]["rich_text"][0]["text"]["content"].startswith(DRAFT_CALLOUT_MARKER)
    assert transport.children[0] is human_note


def test_callout_skipped_when_no_draft():
    transport = CalloutTransport()
    client = NotionClient("secret", "db-id", transport=transport)
    lead = _lead_with_draft()
    lead.generated_draft = ""

    client.upsert_lead(lead)

    assert not any(u.endswith("/children") for m, u, p in transport.calls)


def test_callout_failure_does_not_fail_upsert():
    class ExplodingChildren(CalloutTransport):
        def __call__(self, method, url, headers, body):
            if url.endswith("/children") and method != "GET":
                raise RuntimeError("notion hiccup")
            return super().__call__(method, url, headers, body)

    transport = ExplodingChildren()
    client = NotionClient("secret", "db-id", transport=transport)
    page_id = client.upsert_lead(_lead_with_draft())
    assert page_id == "page-1"
