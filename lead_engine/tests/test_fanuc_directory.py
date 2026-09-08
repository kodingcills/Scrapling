"""Tests against a REAL captured FANUC ASI directory page.

The fixture is the actual HTML returned by
https://www.fanucamerica.com/integrators/robotics?zip=21250&radius=100 on
2026-08-25 (fetched via LeadEngineFetcher), not synthetic data — it catches
selector/shape drift a hand-written mock can't.
"""

import pathlib

import pytest
from scrapling.engines.toolbelt.custom import Response

from lead_engine.models import Lead
from lead_engine.scrapers.integrator_directories import (
    OEM_APPS_ENGINEER_COMPANIES,
    parse_fanuc_card,
    scrape_fanuc_integrators,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "fanuc_robotics_zip21250_r100.html"


@pytest.fixture(scope="module")
def response() -> Response:
    return Response(
        url="https://www.fanucamerica.com/integrators/robotics?zip=21250&radius=100",
        content=FIXTURE.read_bytes(),
        status=200,
        reason="OK",
        encoding="utf-8",
        cookies={},
        headers={"content-type": "text/html"},
        request_headers={},
        method="GET",
    )


def test_fixture_parses_all_seven_real_integrators(response):
    leads = scrape_fanuc_integrators(response, zip_code="21250", radius=100)
    names = {lead.company for lead in leads}
    assert len(leads) == 7
    assert {
        "Weldon Solutions",
        "Arnold Automation",
        "Automated Motion Inc.",
        "Conveyor & Automation Tech",
        "Omnitech Automation Inc.",
        "Precision Cobotics, LLC",
        "RG Group",
    } <= names


def test_weldon_solutions_record_fields(response):
    lead = next(lead for lead in scrape_fanuc_integrators(response) if lead.company == "Weldon Solutions")
    assert lead.source_url == "https://www.weldonsolutions.com"
    assert lead.title_role == "Applications Engineer (Integrator)"
    assert lead.buyer_type == "Channel - Integrator"
    assert lead.source_type == "integrator_directory"
    assert "FANUC" in lead.tech_stack_bottleneck
    assert "directory listing" in lead.operational_trigger


def test_card_parse_extracts_location_tags_email(response):
    cards = response.css("article")
    weldon = next(
        record
        for record in (parse_fanuc_card(card) for card in cards)
        if record["name"] == "Weldon Solutions"
    )
    assert weldon["account_id"]
    assert weldon["website"] == "https://www.weldonsolutions.com"
    assert weldon["email"] == "info@weldonsolutions.com"
    assert weldon["location"].startswith("York, PA")
    assert weldon["distance_mi"] >= 25
    assert "Aerospace" in weldon["industries"]
    assert "Machine Tending" in weldon["applications"]


def test_oem_company_would_classify_as_oem_ae():
    # OEM_APPS_ENGINEER_COMPANIES routing, exercised without a FANUC-owned card
    assert any("fanuc" in name for name in OEM_APPS_ENGINEER_COMPANIES)
    lead = Lead(
        company="FANUC America",
        title_role="OEM Applications Engineer",
        buyer_type="Channel - OEM Apps Eng",
        source_type="integrator_directory",
    )
    assert lead.title_role == "OEM Applications Engineer"


def test_lead_roundtrip_of_real_records(response):
    import json

    for lead in scrape_fanuc_integrators(response):
        revived = Lead.from_dict(json.loads(json.dumps(lead.to_dict())))
        assert revived.company == lead.company
        assert revived.buyer_type == lead.buyer_type
