"""Integrator-directory scraping (FANUC/UR/ABB style listing pages).

FANUC America ASI directory — VERIFIED against the live site 2026-08-25:
https://www.fanucamerica.com/integrators/robotics is a Craft CMS page with
integrator records SERVER-RENDERED in <article> cards (no JSON search XHR;
capture_xhr confirmed nothing matching fires). Search params are plain GET
query strings: ?zip=<postal>&radius=<25|50|100|150>[&industry=][&application=].
robots.txt allows /integrators/* (disallows only /cpresources/, /vendor/,
/.env, /cache/, some /assets/ paths, and /tools/) and specifies no Crawl-delay.
"""

import json
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, urljoin, urlparse

from scrapling import Selector
from scrapling.engines.toolbelt.custom import Response
from scrapling.fetchers import LeadEngineFetcher
from scrapling.spiders import Spider

from lead_engine.models import Lead

JSON_TYPES = ("application/json",)

FANUC_BASE_URL = "https://www.fanucamerica.com/integrators/robotics"

# Selectors CONFIRMED against the live rendered page (2026-08-25) — not guesses.
FANUC_SELECTORS = {
    "card": "article",
    "name": "h3 a",
    "website": "a[href^='http']:not([href*='google.com']):not([href*='fanucamerica.com'])",
    "email": "a[href^='mailto:']",
    "location_link": "a[href*='google.com/maps/dir']",
    "industry_tags": "a[href*='?industry=']",
    "application_tags": "a[href*='?application=']",
}

# Companies whose directory contact is an OEM applications engineer rather
# than an independent integrator.
OEM_APPS_ENGINEER_COMPANIES = {
    "fanuc", "abb", "kuka", "universal robots", "yaskawa", "motoman",
    "kawasaki", "fanuc america", "epson robots", "denso robotics",
}

LOCATION_DISTANCE_RE = re.compile(r"^(.*?)\s*-\s*(\d+)\s*mi$")


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def parse_fanuc_card(card) -> Dict[str, Any]:
    """Parse one verified <article> integrator card into a record dict."""
    record: Dict[str, Any] = {
        "account_id": "",
        "name": "",
        "website": "",
        "email": "",
        "location": "",
        "distance_mi": None,
        "industries": [],
        "applications": [],
    }

    # data-account-* live on the contact buttons inside the card, not on <article>
    account_buttons = card.css("button[data-account-id]")
    if account_buttons:
        record["account_id"] = (account_buttons[0].attrib.get("data-account-id") or "").strip()

    name_anchor = card.css(FANUC_SELECTORS["name"])
    if name_anchor:
        record["name"] = _clean(name_anchor[0].text)
        href = name_anchor[0].attrib.get("href", "")
        if href.startswith("http"):
            record["website"] = href

    mailto = card.css(FANUC_SELECTORS["email"])
    if mailto:
        parsed = urlparse(mailto[0].attrib.get("href", ""))
        record["email"] = parsed.path.strip()

    location_anchor = card.css(FANUC_SELECTORS["location_link"])
    if location_anchor:
        raw = _clean(location_anchor[0].text)
        match = LOCATION_DISTANCE_RE.match(raw)
        if match:
            record["location"] = match.group(1).strip()
            record["distance_mi"] = int(match.group(2))
        else:
            record["location"] = raw

    for key, selector in (("industries", FANUC_SELECTORS["industry_tags"]), ("applications", FANUC_SELECTORS["application_tags"])):
        tags = []
        for tag in card.css(selector):
            label = _clean(tag.text)
            if label:
                tags.append(label)
        record[key] = tags

    return record


def scrape_fanuc_integrators(
    response: Response,
    company: str = "",
    zip_code: str = "21250",
    radius: int = 100,
) -> List[Lead]:
    """Turn a live/fixture FANUC ASI directory response into Lead objects.

    Integrator records classify as Applications Engineer (Integrator) with
    buyer_type Channel - Integrator; companies in OEM_APPS_ENGINEER_COMPANIES
    become OEM Applications Engineer instead.
    """
    records = [parse_fanuc_card(card) for card in response.css(FANUC_SELECTORS["card"])]
    leads: List[Lead] = []
    seen_ids = set()
    for record in records:
        if not record["name"]:
            continue
        key = record["account_id"] or record["website"] or record["name"]
        if key in seen_ids:
            continue
        seen_ids.add(key)

        is_oem = any(oem in record["name"].lower() for oem in OEM_APPS_ENGINEER_COMPANIES)
        title_role = "OEM Applications Engineer" if is_oem else "Applications Engineer (Integrator)"
        trigger = "directory listing: FANUC Authorized System Integrator"
        if record["distance_mi"] is not None:
            trigger += f", {record['distance_mi']} mi from {zip_code}"

        leads.append(
            Lead(
                company=record["name"],
                source_url=record["website"] or f"{FANUC_BASE_URL}?zip={zip_code}&radius={radius}",
                contact_name="",
                is_named=False,
                title_role=title_role,
                buyer_type="Channel - Integrator",
                source_type="integrator_directory",
                operational_trigger=trigger,
                pain_signal="",
                persona_type="Unclassified",
                tech_stack_bottleneck="FANUC robots (Authorized System Integrator)",
                status="New",
            )
        )
    return leads


def fetch_fanuc_integrators(zip_code: str = "21250", radius: int = 100) -> List[Lead]:
    """One-off live fetch through the fork's tuned defaults."""
    response = LeadEngineFetcher.fetch(f"{FANUC_BASE_URL}?zip={zip_code}&radius={radius}", wait=2000)
    return scrape_fanuc_integrators(response, zip_code=zip_code, radius=radius)


def extract_directory_entries(response: Response) -> List[Dict[str, str]]:
    """Extract {name, profile_url} entries from a directory listing page."""
    entries: Dict[str, Dict[str, str]] = {}
    for card in response.css("article, .card, .listing, li"):
        anchors = card.css("a[href]")
        if not anchors:
            continue
        anchor = anchors[0]
        heading = card.css("h2, h3, h4, .title, .name")
        name = " ".join(((heading[0].text if heading else anchor.text) or "").split())
        href = (anchor.attrib.get("href") or "").strip()
        if not name or not href:
            continue
        url = urljoin(response.url or "", href)
        if url not in entries:
            entries[url] = {"name": name, "profile_url": url}
    return list(entries.values())


def captured_json_endpoints(response: Response) -> List[Dict[str, Any]]:
    """Return parsed JSON bodies from XHRs captured via `capture_xhr`.

    This is how site-specific search endpoints (e.g. FANUC's integrator
    search) get discovered: fetch the directory page once through
    `LeadEngineFetcher`, then inspect what the page's own JavaScript asked for.
    """
    found: List[Dict[str, Any]] = []
    seen = set()
    for xhr in response.captured_xhr:
        content_type = ""
        for key in ("content-type", "Content-Type"):
            content_type = xhr.headers.get(key, "") or ""
            if content_type:
                break
        if JSON_TYPES[0] not in content_type:
            continue
        try:
            body = json.loads(xhr.body)
        except (ValueError, TypeError):
            continue
        if id(body) in seen:
            continue
        seen.add(id(body))
        found.append({"url": xhr.url, "data": body})
    return found


class IntegratorDirectorySpider(Spider):
    """Crawl integrator directory listing and detail pages politely."""

    name = "integrator_directories"
    start_urls: list[str] = []
    allowed_domains: set[str] = set()

    robots_txt_obey = True
    robots_crawl_delay_floor = 5.0
    concurrent_requests = 2
    concurrent_requests_per_domain = 1
    autothrottle_enabled = True
    autothrottle_start_delay = 8.0
    autothrottle_max_delay = 90.0
    autothrottle_block_backoff_factor = 2.5
    autothrottle_jitter = 0.3

    async def parse(self, response: Response):
        for entry in extract_directory_entries(response):
            yield {"type": "directory_entry", **entry}
        for endpoint in captured_json_endpoints(response):
            yield {
                "type": "json_endpoint",
                "url": endpoint["url"],
                "keys": sorted(endpoint["data"].keys())[:20] if isinstance(endpoint["data"], dict) else [],
            }


__all__ = [
    "extract_directory_entries",
    "captured_json_endpoints",
    "parse_fanuc_card",
    "scrape_fanuc_integrators",
    "fetch_fanuc_integrators",
    "FANUC_SELECTORS",
    "FANUC_BASE_URL",
    "OEM_APPS_ENGINEER_COMPANIES",
    "IntegratorDirectorySpider",
]
