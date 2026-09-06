"""Tests against real team-page captures from the live verification run."""

from pathlib import Path

from scrapling.engines.toolbelt.custom import Response

from lead_engine.scrapers.team_pages import build_leads, extract_team_members

FIXTURE = Path(__file__).parent / "fixtures" / "live" / "team" / "conveyor.html"


def test_real_conveyor_team_page_has_named_people_but_no_target_roles():
    response = Response(
        url="https://conveyor-automation.com/our-team", content=FIXTURE.read_bytes(),
        status=200, reason="OK", encoding="utf-8", cookies={}, headers={"content-type": "text/html"},
        request_headers={}, method="GET",
    )
    members = extract_team_members(response)
    names = {member["name"] for member in members}
    assert {"Lilly Sarikas", "Gus Sarikas", "Tim Sylvester"} <= names
    assert not any(member["title"] for member in members)

    leads = build_leads(response, company="Conveyor & Automation Tech")
    named = [lead for lead in leads if lead.is_named]
    assert named
    assert named[0].contact_name == "Lilly Sarikas"
    assert named[0].source_url == "https://conveyor-automation.com/our-team"
    assert all(lead.persona_type == "Unclassified" for lead in named)
