"""Career-page scraping: link discovery, role extraction, and the spider."""

import json
from typing import Any, Dict, Iterator, List
from urllib.parse import urljoin

from scrapling import Selector
from scrapling.core.utils import log
from scrapling.engines.toolbelt.custom import Response
from scrapling.fetchers import LeadEngineFetcher
from scrapling.spiders import Request, Spider

from lead_engine.classify import classify_role
from lead_engine.models import Lead, Role
from lead_engine.scrapers.base import (
    DEFAULT_MAX_PAGES,
    classify_buyer_type,
    classify_persona,
    classify_title,
    domain_from_url,
    find_pain_signal,
    find_tech_stack_mention,
    page_text,
)

CAREER_PATH_HINTS = ("career", "job", "employment", "opening", "join-us", "join-our", "work-with-us", "hiring")

JOB_LINK_TEXT_HINTS = (
    "engineer", "technician", "manager", "operator", "welder", "machinist",
    "assembler", "supervisor", "buyer", "procurement", "purchasing",
)


def find_career_links(html: str, base_url: str = "") -> List[str]:
    """Heuristically locate career-page links on a homepage."""
    page = Selector(content=html)
    links = set()
    for anchor in page.css("a"):
        text = (anchor.text or "").lower()
        href = (anchor.attrib.get("href") or "").strip()
        if not href:
            continue
        combined = f"{text} {href.lower()}"
        if any(hint in combined for hint in CAREER_PATH_HINTS):
            links.add(urljoin(base_url, href) if base_url else href)
    return sorted(links)


def _looks_like_job_title(title: str) -> bool:
    """Reject link text that reads as an editorial headline rather than a
    job title. Real postings are short noun phrases ("Quality Engineer",
    "Senior Buyer") - every title in the live career-page fixtures is under
    50 characters and none contain a colon. A real false positive from a
    "Related Insights" blog teaser on a career page ("Design for
    Procurement: A Strategic and Proactive Approach...") had a colon and
    ran to 97 characters, and was caught by the JOB_LINK_TEXT_HINTS keyword
    match ("procurement") despite not being a job posting at all - the
    keyword match alone isn't enough, the candidate also has to look
    title-shaped. This is a shape check, not a vendor/content blocklist, so
    it stays generic across career-page platforms."""
    return len(title) <= 70 and ":" not in title


def extract_roles(response: Response, company: str = "") -> List[Role]:
    """Extract job postings from a career page's HTML."""
    roles: Dict[str, Role] = {}
    base_url = response.url or ""
    for anchor in response.css("a"):
        title = " ".join((anchor.text or "").split())
        if not title or not _looks_like_job_title(title):
            continue
        lowered = title.lower()
        if any(kw in lowered for kw in JOB_LINK_TEXT_HINTS):
            href = (anchor.attrib.get("href") or "").strip()
            url = urljoin(base_url, href) if href else ""
            key = url or title
            if key not in roles:
                roles[key] = Role(title=title, url=url, company=company, category=classify_role(title))
    return list(roles.values())


def fetch_roles(url: str, company: str = "") -> List[Role]:
    """One-off fetch of a career page using the fork's tuned defaults."""
    response = LeadEngineFetcher.fetch(url)
    return extract_roles(response, company=company)


# Vendor-agnostic XHR job-posting sniffing: any captured JSON that is (or
# contains, one nesting level down) a list of objects with a title-shaped
# field AND a location/apply-url-shaped field is treated as the postings
# feed. This works because of the JSON shape, never because of which
# ATS vendor or URL pattern produced it.
TITLE_SHAPED_KEYS = ("title", "job_title", "position", "name")
LOCATION_URL_SHAPED_KEYS = ("location", "locations", "apply_url", "url")
URL_PREFERENCE_KEYS = ("apply_url", "url")


def _posting_shaped(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    keys = {str(key).lower() for key in obj}
    has_title = any(key in keys for key in TITLE_SHAPED_KEYS)
    has_loc_or_url = any(key in keys for key in LOCATION_URL_SHAPED_KEYS)
    return has_title and has_loc_or_url


def _posting_lists(data: Any) -> Iterator[List[Dict[str, Any]]]:
    """Yield lists of posting-shaped dicts from a top-level list, or a list
    sitting directly under one key of a top-level dict."""
    if isinstance(data, list) and data and all(_posting_shaped(item) for item in data):
        yield data
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and all(_posting_shaped(item) for item in value):
                yield value


def _first_str(obj: Dict[str, Any], keys) -> str:
    for key in keys:
        for obj_key, value in obj.items():
            if obj_key.lower() == key and isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _location_text(value: Any) -> str:
    """Flatten a JSON location field (string, or list of strings/dicts)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                for key in ("canonical_name", "name", "city", "state"):
                    if isinstance(item.get(key), str) and item[key].strip():
                        parts.append(item[key].strip())
                        break
        return ", ".join(parts)
    return ""


def extract_roles_from_captured_xhr(response: Response, company: str = "") -> List[Role]:
    """Extract Role candidates from any captured XHR whose JSON body looks
    like a job-postings feed. Vendor-agnostic by construction."""
    roles: Dict[str, Role] = {}
    for xhr in getattr(response, "captured_xhr", None) or []:
        body = getattr(xhr, "body", None)
        if not body:
            continue
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            continue
        for postings in _posting_lists(data):
            for obj in postings:
                title = _first_str(obj, TITLE_SHAPED_KEYS)
                if not title:
                    continue
                url = _first_str(obj, URL_PREFERENCE_KEYS)
                location = _location_text(next((obj[k] for k in obj if k.lower() in ("location", "locations")), ""))
                key = url or title
                if key not in roles:
                    roles[key] = Role(
                        title=title, url=url, location=location, company=company, category=classify_role(title)
                    )
    return list(roles.values())


def build_leads(response: Response, company: str = "") -> List[Lead]:
    """Turn scraped roles into Leads with persona and tech-stack populated
    from the same page text/title already being scraped."""
    text = page_text(response)
    tech = find_tech_stack_mention(text)
    pain = find_pain_signal(text)
    leads: Dict[str, Lead] = {}
    # When a captured XHR looks like the postings feed, use its JSON fields
    # instead of DOM link text; otherwise fall back to DOM extraction.
    roles = extract_roles_from_captured_xhr(response, company=company)
    if not roles:
        roles = extract_roles(response, company=company)
    for role in roles:
        if role.category == "other":
            continue
        title_role = classify_title(role.title)
        persona = classify_persona(role.title) if title_role != "Other" else "Unclassified"
        key = role.url or role.title
        if key in leads:
            continue
        leads[key] = Lead(
            company=role.company or company,
            source_url=role.url or (response.url or ""),
            contact_name="",
            is_named=False,
            title_role=title_role,
            buyer_type=classify_buyer_type(title_role),
            source_type="career_page",
            operational_trigger=f"open req: {role.title}" + (f" at {company}" if company else ""),
            pain_signal=pain,
            persona_type=persona,
            tech_stack_bottleneck=tech,
        )
    return list(leads.values())


class CareerPageSpider(Spider):
    """Crawl a site's career section with polite, human-paced throttling.

    Starts at the seed career URL, follows only links that look like
    career-section pages (the same CAREER_PATH_HINTS signal
    find_career_links() uses, so there is one definition of "looks like a
    careers link"), extracts full Leads on every page via build_leads()
    (single source of truth for taxonomy/persona classification), and
    stops following once max_pages pages have been processed. All
    anti-detection/throttling tailoring comes from class attributes here;
    the reusable behavior lives in the scrapling fork.
    """

    name = "career_pages"
    robots_txt_obey = True
    robots_crawl_delay_floor = 5.0
    concurrent_requests = 2
    concurrent_requests_per_domain = 1
    autothrottle_enabled = True
    autothrottle_start_delay = 8.0
    autothrottle_max_delay = 90.0
    autothrottle_block_backoff_factor = 2.5
    autothrottle_jitter = 0.3

    def __init__(self, seed_url: str, company: str = "", max_pages: int = DEFAULT_MAX_PAGES):
        self.seed_url = seed_url
        self.company = company
        self.max_pages = max(1, max_pages)
        self.pages_visited = 0
        self._follows_enqueued = 0
        self.start_urls = [seed_url]
        self.allowed_domains = {domain_from_url(seed_url)}
        super().__init__()

    def configure_sessions(self, manager) -> None:
        # Same tuned browsing profile as LeadEngineFetcher (headless, XHR
        # capture, Cloudflare solving): a plain FetcherSession would miss
        # job feeds served via XHR and regressed live lead counts.
        from scrapling.fetchers import AsyncStealthySession
        from scrapling.fetchers.lead_engine import LeadEngineFetcher

        manager.add("default", AsyncStealthySession(headless=True, **LeadEngineFetcher.profile))

    async def parse(self, response: Response):
        self.pages_visited += 1
        for lead in build_leads(response, company=self.company):
            yield lead.to_dict()
        if self.pages_visited >= self.max_pages:
            self.logger.info(
                f"[{self.company or self.seed_url}] reached the {self.max_pages}-page crawl cap"
            )
            return
        html = response.body.decode(response.encoding, errors="replace")
        for link in find_career_links(html, base_url=response.url or ""):
            if link == response.url:
                continue
            if self.pages_visited + self._follows_enqueued >= self.max_pages:
                return
            self._follows_enqueued += 1
            yield Request(link)


def crawl_leads(url: str, company: str = "", max_pages: int = DEFAULT_MAX_PAGES) -> List[Lead]:
    """Run CareerPageSpider to completion and return the aggregated Leads.

    Raises RuntimeError when the seed page itself could not be fetched, so
    a dead site surfaces as a per-company error instead of a silent zero.
    """
    spider = CareerPageSpider(seed_url=url, company=company, max_pages=max_pages)
    result = spider.start()
    if spider.pages_visited == 0:
        stats = result.stats
        raise RuntimeError(
            f"crawl visited 0 pages (seed fetch failed or disallowed: "
            f"failed={stats.failed_requests_count}, blocked={stats.blocked_requests_count}, "
            f"robots_disallowed={stats.robots_disallowed_count})"
        )
    leads = [Lead.from_dict(item) for item in result.items if "title_role" in item]
    log.info(f"Crawled {spider.pages_visited} page(s) at {url}; extracted {len(leads)} lead(s)")
    return leads


__all__ = [
    "find_career_links",
    "extract_roles",
    "extract_roles_from_captured_xhr",
    "fetch_roles",
    "build_leads",
    "crawl_leads",
    "CareerPageSpider",
    "DEFAULT_MAX_PAGES",
]
