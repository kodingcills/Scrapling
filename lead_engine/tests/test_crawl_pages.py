"""Synthetic multi-page crawl tests for CareerPageSpider.

Runs the real CrawlerEngine + SessionManager machinery end to end with a
stubbed session serving small static pages, so link following, the
career-shaped follow filter, the page cap, and cross-page lead aggregation
are all exercised without any network access.

The shipped polite throttling settings (robots obey, crawl-delay floor,
autothrottle) are asserted in test_fork_defaults.py and are NOT touched
here - the spider instances below override them so the tests run fast.
"""
import sys
from pathlib import Path

import pytest
from scrapling.engines.toolbelt.custom import Response
from scrapling.spiders.result import CrawlResult, CrawlStats, ItemList

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lead_engine.models import Lead  # noqa: E402
from lead_engine.scrapers.career_pages import (  # noqa: E402
    CareerPageSpider,
    crawl_leads,
)

SEED = "https://acme.example.com/careers"

HUB_HTML = """
<h1>Careers</h1>
<a href="/careers/engineering">Engineering openings</a>
<a href="/careers/quality">Quality openings</a>
<a href="/about">About us</a>
"""

ENGINEERING_HTML = """
<h1>Engineering Openings</h1>
<a href="/careers/openings/manufacturing-engineer">Manufacturing Engineer</a>
"""

QUALITY_HTML = """
<h1>Quality Openings</h1>
<a href="/careers/openings/quality-engineer">Quality Engineer</a>
"""

PAGES = {
    SEED: HUB_HTML,
    "https://acme.example.com/careers/engineering": ENGINEERING_HTML,
    "https://acme.example.com/careers/quality": QUALITY_HTML,
    # /about is deliberately absent: if the crawler ever fetched it, the
    # stub raises and the request is recorded as failed.
}


class StubSession:
    _is_alive = True

    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, request):
        self.fetched.append(request.url)
        html = self.pages[request.url]
        response = Response(
            url=request.url,
            content=html.encode("utf-8"),
            status=200,
            reason="OK",
            encoding="utf-8",
            cookies={},
            headers={"content-type": "text/html"},
            request_headers={},
            method="GET",
        )
        response.request = request
        response.meta = {}
        return response


class StubSessionManager:
    def __init__(self, session):
        self._session = session

    @property
    def default_session_id(self):
        return "default"

    async def fetch(self, request):
        return await self._session.fetch(request)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_spider(pages, seed=SEED, company="Acme", max_pages=15):
    spider = CareerPageSpider(seed_url=seed, company=company, max_pages=max_pages)
    spider.robots_txt_obey = False
    spider.robots_crawl_delay_floor = 0.0
    spider.autothrottle_enabled = False
    session = StubSession(pages)
    spider._session_manager = StubSessionManager(session)
    return spider, session


def _leads_from(result):
    return [Lead.from_dict(item) for item in result.items if "title_role" in item]


def test_spider_follows_career_links_and_aggregates_leads():
    spider, session = _make_spider(PAGES)
    result = spider.start()

    assert "https://acme.example.com/careers/engineering" in session.fetched
    assert "https://acme.example.com/careers/quality" in session.fetched
    assert "https://acme.example.com/about" not in session.fetched
    assert spider.pages_visited == 3

    leads = _leads_from(result)
    title_roles = {lead.title_role for lead in leads}
    assert "Manufacturing Engineer" in title_roles
    assert "Quality Engineer" in title_roles
    assert all(lead.company == "Acme" for lead in leads)
    assert all(lead.source_type == "career_page" for lead in leads)


def test_spider_page_cap_stops_following():
    spider, session = _make_spider(PAGES, max_pages=2)
    result = spider.start()

    assert spider.pages_visited == 2
    assert len(session.fetched) == 2
    leads = _leads_from(result)
    assert leads, "capped crawl must still yield leads from the pages it did visit"


def test_spider_dedups_repeated_career_links_across_pages():
    pages = dict(PAGES)
    pages["https://acme.example.com/careers/engineering"] = (
        ENGINEERING_HTML + '<a href="/careers/quality">Quality openings</a>'
    )
    spider, session = _make_spider(pages)
    spider.start()

    assert session.fetched.count("https://acme.example.com/careers/quality") == 1


def test_crawl_leads_converts_items_and_raises_on_dead_seed(monkeypatch):
    def fake_start_ok(self):
        self.pages_visited = 3
        lead = Lead(
            company="Acme",
            source_url=SEED,
            title_role="Quality Engineer",
        )
        return CrawlResult(stats=CrawlStats(), items=ItemList([lead.to_dict()]))

    monkeypatch.setattr(CareerPageSpider, "start", fake_start_ok)
    leads = crawl_leads(SEED, company="Acme")
    assert len(leads) == 1
    assert leads[0].title_role == "Quality Engineer"

    def fake_start_dead(self):
        self.pages_visited = 0
        return CrawlResult(stats=CrawlStats(failed_requests_count=1), items=ItemList())

    monkeypatch.setattr(CareerPageSpider, "start", fake_start_dead)
    with pytest.raises(RuntimeError, match="visited 0 pages"):
        crawl_leads(SEED, company="Acme")
