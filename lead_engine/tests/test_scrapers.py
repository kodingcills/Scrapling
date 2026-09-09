import pytest
from scrapling import Selector

from lead_engine.scrapers.career_pages import extract_roles, find_career_links
from lead_engine.scrapers.integrator_directories import extract_directory_entries
from lead_engine.scrapers.team_pages import build_leads, extract_team_members
from lead_engine.scrapers.base import extract_meta_description


HOME_HTML = """
<a href="/careers">Careers</a>
<a href="https://external.example.com/jobs">Jobs board</a>
<a href="/about">About</a>
"""

CAREER_HTML = """
<h1>Open Positions</h1>
<a href="/jobs/controls-engineer">Controls Engineer</a>
<a href="/jobs/senior-buyer">Senior Buyer</a>
<a href="/jobs/benefits">Benefits Overview</a>
"""

DIRECTORY_HTML = """
<ul class="listing">
  <li><a href="/integrators/acme"><h3>Acme Robotics</h3></a></li>
  <li><a href="/integrators/beta"><h3>Beta Automation</h3></a></li>
</ul>
"""

TEAM_HTML = """
<html><body>
<div class="team-member"><h3>Jane Smith - Chief Executive Officer</h3>
  <a href="https://www.linkedin.com/in/janesmith/">LinkedIn</a> jane@acme.example.com</div>
<div class="team-member"><h3>Bob Jones, Controls Engineering Manager</h3></div>
</body></html>
"""


def _fake_response(html: str, url: str = "https://site.example.com/page"):
    from scrapling.engines.toolbelt.custom import Response

    return Response(
        url=url,
        content=html.encode("utf-8"),
        status=200,
        reason="OK",
        encoding="utf-8",
        cookies={},
        headers={"content-type": "text/html"},
        request_headers={},
        method="GET",
    )


def test_find_career_links():
    links = find_career_links(HOME_HTML, base_url="https://site.example.com/")
    assert "https://site.example.com/careers" in links
    assert all("/about" != link for link in links)


def test_extract_roles_classifies():
    response = _fake_response(CAREER_HTML)
    roles = extract_roles(response, company="Acme")
    by_title = {role.title: role for role in roles}
    assert by_title["Controls Engineer"].category == "engineering"
    assert by_title["Senior Buyer"].category == "buyer"
    assert by_title["Controls Engineer"].company == "Acme"
    assert "Benefits" not in by_title


# Real false positive from a live run against Creation Technologies'
# careers page: a "Related Insights" blog teaser on the page linked to a
# wpengine-hosted article whose title contained "procurement", matching
# JOB_LINK_TEXT_HINTS, and got synced to Notion as a lead. The teaser link
# points off-domain (creationtech2.wpenginepowered.com, not
# creationtech.com) exactly like a real ATS redirect would, so a
# same-domain check would be the wrong fix - the actual signal is that the
# text is an editorial headline (colon, 60 chars), not a job title.
CREATION_TECH_BLOG_TEASER_HTML = """
<h1>Careers</h1>
<a href="/jobs/quality-engineer">Quality Engineer</a>
<a href="https://creationtech2.wpenginepowered.com/design-for-procurement-a-strategic-approach-to-long-term-cost-optimization-and-risk-mitigation/">Design for Procurement: A Strategic and Proactive Approach</a>
"""


def test_extract_roles_rejects_blog_teaser_false_positive():
    response = _fake_response(CREATION_TECH_BLOG_TEASER_HTML)
    roles = extract_roles(response, company="Creation Technologies")
    titles = {role.title for role in roles}
    assert "Quality Engineer" in titles
    assert not any(title.startswith("Design for Procurement") for title in titles)


def test_extract_directory_entries():
    entries = extract_directory_entries(_fake_response(DIRECTORY_HTML))
    names = {entry["name"] for entry in entries}
    assert {"Acme Robotics", "Beta Automation"} <= names
    urls = {entry["profile_url"] for entry in entries}
    assert any(url.startswith("https://site.example.com/integrators/") for url in urls)


def test_extract_team_members():
    members = extract_team_members(_fake_response(TEAM_HTML))
    by_name = {member["name"]: member for member in members}
    assert "Jane Smith" in by_name
    assert by_name["Jane Smith"]["decision_maker"] is True
    assert by_name["Jane Smith"]["email"] == "jane@acme.example.com"
    assert by_name["Bob Jones"]["decision_maker"] is False


def test_build_leads_carries_linkedin_from_team_page():
    leads = build_leads(_fake_response(TEAM_HTML), company="Acme")
    jane = next(lead for lead in leads if lead.contact_name == "Jane Smith")
    assert jane.linkedin == "https://www.linkedin.com/in/janesmith"
    assert jane.is_named is True
    bob = next(lead for lead in leads if lead.contact_name == "Bob Jones")
    assert bob.linkedin == ""


def test_extract_meta_description_prefers_name_over_og():
    both = _fake_response(
        '<html><head><meta name="description" content="Name description.">'
        '<meta property="og:description" content="OG description."></head></html>'
    )
    assert extract_meta_description(both) == "Name description."

    og_only = _fake_response('<html><head><meta property="og:description" content="OG only."></head></html>')
    assert extract_meta_description(og_only) == "OG only."


def test_extract_meta_description_blank_without_meta_tags():
    no_meta = _fake_response("<html><head><title>Acme</title></head><body><p>text</p></body></html>")
    assert extract_meta_description(no_meta) == ""

    empty_content = _fake_response('<html><head><meta name="description" content="   "></head></html>')
    assert extract_meta_description(empty_content) == ""
