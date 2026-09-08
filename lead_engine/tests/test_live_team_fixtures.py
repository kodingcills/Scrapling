"""Tests against real team-page captures from the live verification run."""

from pathlib import Path

from scrapling.engines.toolbelt.custom import Response

from lead_engine.scrapers.team_pages import build_leads, extract_team_members

FIXTURES = Path(__file__).parent / "fixtures" / "live" / "team"


def _team_response(name, url):
    return Response(
        url=url, content=(FIXTURES / name).read_bytes(), status=200, reason="OK",
        encoding="utf-8", cookies={}, headers={"content-type": "text/html"},
        request_headers={}, method="GET",
    )


def test_real_conveyor_team_page_has_named_people_but_no_target_roles():
    response = _team_response("conveyor.html", "https://conveyor-automation.com/our-team")
    members = extract_team_members(response)
    names = {member["name"] for member in members}
    assert {"Lilly Sarikas", "Gus Sarikas", "Tim Sylvester"} <= names
    assert not any(member["title"] for member in members)

    # Name-sanity filter: junk headings dropped, all real people kept.
    assert "Mechanical Engineering" not in names
    assert "CAD Drafting Services" not in names
    assert "Project Management" not in names
    assert "Product Development" not in names
    assert "This website uses cookies." not in names
    assert len(members) == 8

    leads = build_leads(response, company="Conveyor & Automation Tech")
    named = [lead for lead in leads if lead.is_named]
    assert named
    assert named[0].contact_name == "Lilly Sarikas"
    assert named[0].source_url == "https://conveyor-automation.com/our-team"
    assert all(lead.persona_type == "Unclassified" for lead in named)


def test_real_rg_group_capture_has_no_false_positive_people():
    # RG Group has no real team page; the bio-card heuristic previously
    # "found" a corporate-office heading and a phone number. All junk must
    # now be rejected — zero person matches is the correct result.
    response = _team_response("rg.html", "https://www.rggroup.com/about/")
    assert extract_team_members(response) == []
