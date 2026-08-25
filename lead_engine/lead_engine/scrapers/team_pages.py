"""Team/About-page scraping: find people, titles, emails, LinkedIn URLs."""

import re
from typing import List

from scrapling.engines.toolbelt.custom import Response
from scrapling.fetchers import LeadEngineFetcher
from scrapling.spiders import Spider

from lead_engine.classify import is_decision_maker
from lead_engine.models import Lead
from lead_engine.scrapers.base import (
    classify_persona,
    classify_title,
    find_pain_signal,
    find_tech_stack_mention,
    page_text,
)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%-]+/?")
NAME_TITLE_SPLIT_RE = re.compile(r"\s*[-–—,]\s+")


def extract_team_members(response: Response) -> List[dict]:
    """Heuristically pull people out of a team/about page."""
    members: List[dict] = []
    seen_names = set()

    html_text = response.body.decode(response.encoding, errors="replace")
    linkedin_urls = {m.group(0).rstrip("/?") for m in LINKEDIN_RE.finditer(html_text)}
    emails = {m.group(0).lower() for m in EMAIL_RE.finditer(html_text)}

    for node in response.css("h2, h3, h4, .team-member, .person, .staff"):
        raw = " ".join((node.text or "").split())
        if not (8 <= len(raw) <= 120):
            continue
        parts = NAME_TITLE_SPLIT_RE.split(raw, maxsplit=1)
        name = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ""
        if not name or len(name.split()) > 5 or name.lower() in seen_names:
            continue
        scope_text = (
            node.parent.get_all_text(" ") if node.parent is not None and node.parent.tag != "body" else raw
        )
        member_email = next(
            (e for e in sorted(emails) if any(p.lower() in e for p in name.lower().split()) and e in scope_text), ""
        )
        member_linkedin = ""
        slug_hits = [
            u for u in linkedin_urls if all(part.lower() in u.rsplit("/", 1)[-1].lower() for part in name.lower().split())
        ]
        if slug_hits:
            member_linkedin = slug_hits[0]
            linkedin_urls.discard(member_linkedin)
        member = {
            "name": name,
            "title": title,
            "email": member_email,
            "linkedin": member_linkedin,
            "decision_maker": is_decision_maker(title),
        }
        seen_names.add(name.lower())
        members.append(member)
    return members


def fetch_team(url: str) -> List[dict]:
    """One-off fetch of an about/team page using the fork's tuned defaults."""
    return extract_team_members(LeadEngineFetcher.fetch(url))


def build_leads(response: Response, company: str = "") -> List[Lead]:
    """Turn scraped team members into Leads with persona and tech-stack
    populated from the same page text/titles already being scraped."""
    text = page_text(response)
    tech = find_tech_stack_mention(text)
    pain = find_pain_signal(text)
    leads: List[Lead] = []
    for member in extract_team_members(response):
        title_role = classify_title(member["title"])
        persona = classify_persona(member["title"]) if title_role != "Other" else "Unclassified"
        leads.append(
            Lead(
                company=member.get("company") or company,
                source_url=response.url or "",
                contact_name=member["name"],
                is_named=bool(member["name"].strip()),
                title_role=title_role,
                buyer_type="Budget Owner" if member.get("decision_maker") else "Unknown",
                source_type="team_page",
                operational_trigger=f"team page contact: {member['name']}" + (f" ({company})" if company else ""),
                pain_signal=pain,
                persona_type=persona,
                tech_stack_bottleneck=tech,
            )
        )
    return leads


class TeamPageSpider(Spider):
    """Crawl team/about pages politely."""

    name = "team_pages"
    start_urls: list[str] = []
    allowed_domains: set[str] = set()

    robots_txt_obey = True
    robots_crawl_delay_floor = 5.0
    autothrottle_enabled = True
    autothrottle_start_delay = 8.0
    autothrottle_max_delay = 90.0
    autothrottle_block_backoff_factor = 2.5
    autothrottle_jitter = 0.3

    async def parse(self, response: Response):
        for member in extract_team_members(response):
            yield {"type": "team_member", **member}


__all__ = [
    "extract_team_members",
    "fetch_team",
    "build_leads",
    "TeamPageSpider",
]
