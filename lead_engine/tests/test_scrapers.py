import pytest
from scrapling import Selector

from lead_engine.scrapers.career_pages import extract_roles, find_career_links
from lead_engine.scrapers.integrator_directories import extract_directory_entries
from lead_engine.scrapers.team_pages import extract_team_members


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
