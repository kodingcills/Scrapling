"""Minimal Notion API client and property mapping for lead_engine.

Uses the stdlib so the campaign package carries no extra runtime
dependencies; the transport is injectable for tests.
"""

import json
import re
from typing import Any, Dict, Optional

from scrapling.core.utils import log

from lead_engine.models import Lead

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

DEFAULT_STATUS = "New"

# Lead.source_type -> live Notion "Source Type" select options. team_page has
# no clean existing option (automated scraping of a company's own team page —
# not a job posting, not a directory listing, not a human referral), so it
# maps to "Other"; add a real "Team / About Page" option in both places later
# if wanted.
SOURCE_TYPE_NOTION_MAP = {
    "career_page": "Career Page / Job Posting",
    "integrator_directory": "Integrator Directory",
    "team_page": "Other",
}

# Marker identifying "our" draft callout block in the page body — anything
# without this prefix is assumed to be human-written and left alone.
DRAFT_CALLOUT_EMOJI = "🎯"
DRAFT_CALLOUT_MARKER = f"{DRAFT_CALLOUT_EMOJI} Outreach draft:\n"


def build_properties(lead: Lead) -> Dict[str, Any]:
    """Map a Lead onto Notion database properties (schema lives here).

    Status is a plain select (New/Reviewed/Queued/Drafted/Contacted/
    Responded/Disqualified) — NOT the old Notion "status" property type.
    """
    properties: Dict[str, Any] = {
        # Ground truth from the live Notion database: the title property is
        # literally named "Lead Name". The Python field stays `contact_name`;
        # these names are independent on purpose.
        "Lead Name": {"title": [{"text": {"content": lead.contact_name or lead.company or lead.source_url}}]},
        "Company": {"rich_text": [{"text": {"content": lead.company}}]},
        "Source URL": {"url": lead.source_url or None},
        "Title / Role": {"select": {"name": lead.title_role}},
        "Buyer Type": {"select": {"name": lead.buyer_type}},
        "Source Type": {"select": {"name": SOURCE_TYPE_NOTION_MAP.get(lead.source_type, "Other")}},
        "Persona Type": {"select": {"name": lead.persona_type}},
        "Tech Stack / Bottleneck": {"rich_text": [{"text": {"content": lead.tech_stack_bottleneck}}]},
        "Generated Draft": {"rich_text": [{"text": {"content": lead.generated_draft}}]},
        "Status": {"select": {"name": lead.status}},
        "Contact Status": {"select": {"name": lead.contact_status}},
    }
    # "Email" is a Notion EMAIL-type property; only set when we actually have one
    if lead.email:
        properties["Email"] = {"email": lead.email}
    if lead.operational_trigger:
        properties["Operational Trigger"] = {"rich_text": [{"text": {"content": lead.operational_trigger[:2000]}}]}
    if lead.pain_signal:
        properties["Pain Signal"] = {"rich_text": [{"text": {"content": lead.pain_signal[:2000]}}]}
    return properties


# Backwards-compatible alias used by earlier call sites
build_lead_properties = build_properties


def normalize_notion_id(raw: str) -> str:
    """Accept a bare UUID (dashed or not) or a full page/database URL
    pasted from the browser address bar, and return a standard dashed
    UUID.

    Real mistake this guards against: NOTION_DATABASE_ID was set to
    "https://app.notion.com/p/63f8848d11c04873926a9c44530f60c9..." instead
    of the bare id - an easy paste error since the browser address bar is
    the most natural place to grab a database id from, and Notion's API
    rejects it outright ("parent.database_id should be a valid uuid").
    Strip all dashes/slug text and pull the first 32 contiguous hex
    characters, then re-insert standard UUID dashes.
    """
    raw = raw.strip()
    match = re.search(r"[0-9a-fA-F]{32}", raw.replace("-", ""))
    if not match:
        return raw  # not id-shaped at all; let Notion's own error surface
    hex32 = match.group(0)
    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"


class NotionClient:
    """Thin Notion REST client for the single "Precision Assembly Leads" database."""

    def __init__(self, token: str, database_id: str, transport=None):
        """
        :param token: Notion integration secret.
        :param database_id: The leads database to sync into.
        :param transport: Callable(method, url, headers, body) -> (status, body); defaults to urllib.
        """
        self.database_id = normalize_notion_id(database_id)
        self._token = token
        self._transport = transport or self._default_transport

    @staticmethod
    def _default_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes]):
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def _call(self, method: str, path: str, payload: Optional[dict] = None):
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        return self._transport(method, f"{API_BASE}{path}", headers, body)

    def _query_id(self, property_name: str, condition: dict) -> Optional[str]:
        status, data = self._call(
            "POST",
            f"/databases/{self.database_id}/query",
            {"filter": {"property": property_name, **condition}},
        )
        if status != 200:
            return None
        results = data.get("results", [])
        return results[0]["id"] if results else None

    def find_lead_by_source_url(self, source_url: str) -> Optional[str]:
        """Dedup leads by their Source URL."""
        if not source_url:
            return None
        return self._query_id("Source URL", {"url": {"equals": source_url}})

    def upsert_lead(self, lead: Lead) -> str:
        """Create or update (in place, deduped by Source URL) a lead row.

        Create-time Status default is "New" via a plain select — the old
        {"status": {"name": ...}} property type is gone from the schema.
        When the lead carries a generated draft, a callout block is also
        written into the page body so the draft reads full-width.
        """
        page_id = self.find_lead_by_source_url(lead.source_url)
        properties = build_properties(lead)
        if page_id:
            status, data = self._call("PATCH", f"/pages/{page_id}", {"properties": properties})
        else:
            payload = {
                "parent": {"database_id": self.database_id},
                "properties": properties,
            }
            status, data = self._call("POST", "/pages", payload)
        if status not in (200, 201):
            raise RuntimeError(f"Notion API error {status}: {data}")
        page_id = data["id"]

        if lead.generated_draft:
            try:
                self.upsert_draft_callout(page_id, lead.generated_draft)
            except Exception as error:
                # The row is already saved; a body-callout failure shouldn't
                # fail the whole sync.
                log.warning(f"Draft callout update failed for {page_id}: {error}")
        return page_id

    def upsert_draft_callout(self, page_id: str, draft_text: str) -> None:
        """Write the generated draft into the page body as a 🎯 callout block.

        Idempotent: identified by DRAFT_CALLOUT_MARKER, an existing callout is
        updated in place (PATCH), otherwise one new callout is appended. Any
        other blocks on the page — including human-written ones without the
        marker — are left untouched.
        """
        existing_block_id = None
        status, data = self._call("GET", f"/blocks/{page_id}/children")
        if status == 200:
            for block in data.get("results", []):
                if block.get("type") != "callout":
                    continue
                content = "".join(
                    piece.get("plain_text", "") for piece in block.get("callout", {}).get("rich_text", [])
                )
                if content.startswith(DRAFT_CALLOUT_MARKER):
                    existing_block_id = block["id"]
                    break

        rich_text = [{"type": "text", "text": {"content": DRAFT_CALLOUT_MARKER + draft_text}}]
        if existing_block_id:
            self._call("PATCH", f"/blocks/{existing_block_id}", {"callout": {"rich_text": rich_text}})
        else:
            self._call(
                "PATCH",
                f"/blocks/{page_id}/children",
                {
                    "children": [
                        {
                            "object": "block",
                            "type": "callout",
                            "callout": {"icon": {"type": "emoji", "emoji": DRAFT_CALLOUT_EMOJI}, "rich_text": rich_text},
                        }
                    ]
                },
            )


__all__ = [
    "NotionClient",
    "build_properties",
    "DEFAULT_STATUS",
    "DRAFT_CALLOUT_MARKER",
    "SOURCE_TYPE_NOTION_MAP",
]
