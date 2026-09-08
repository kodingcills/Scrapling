"""Tests for the Lead/Company/Role dataclasses themselves (no Notion)."""

import pytest

from lead_engine.models import (
    BUYER_TYPE_OPTIONS,
    CONTACT_STATUS_OPTIONS,
    PERSONA_TYPE_OPTIONS,
    SOURCE_TYPE_OPTIONS,
    STATUS_OPTIONS,
    TITLE_ROLE_OPTIONS,
    Company,
    Lead,
    Role,
    TeamMember,
)


def test_company_roundtrip():
    company = Company(
        name="Acme Robotics",
        website="https://acmerobotics.example.com",
        kind="integrator",
        roles=[Role(title="Controls Engineer", url="https://x/jobs/1", company="Acme", category="engineering")],
        team=[TeamMember(name="Jane Smith", title="CEO", email="jane@acme.example.com")],
        notes="Small shop, 40 employees.",
    )
    data = company.to_dict()
    assert data["name"] == "Acme Robotics"
    assert len(data["roles"]) == 1
    assert data["team"][0]["email"] == "jane@acme.example.com"


def test_lead_enum_option_sets():
    assert PERSONA_TYPE_OPTIONS == {"Executive", "Practitioner", "Unclassified"}
    assert STATUS_OPTIONS == {
        "New", "Reviewed", "Queued", "Drafted", "Contacted", "Responded", "Disqualified",
    }
    assert CONTACT_STATUS_OPTIONS == {"not_attempted", "valid", "uncertain", "invalid", "no_credits"}
    assert "Applications Engineer (Integrator)" in TITLE_ROLE_OPTIONS
    assert BUYER_TYPE_OPTIONS == {
        "Buyer - Quality",
        "Gatekeeper - Process/Mfg Eng",
        "Channel - Integrator",
        "Channel - OEM Apps Eng",
        "Unclassified",
    }
    assert "integrator_directory" in SOURCE_TYPE_OPTIONS


@pytest.mark.parametrize(
    "field,value",
    [
        ("persona_type", "Wizard"),
        ("status", "Not started"),
        ("contact_status", "maybe"),
        ("title_role", "CFO"),
        ("buyer_type", "Whale"),
        ("source_type", "linkedin"),
    ],
)
def test_lead_rejects_invalid_enum_values(field, value):
    with pytest.raises(ValueError, match=field):
        Lead(**{field: value})


def test_lead_from_dict_ignores_unknown_keys():
    lead = Lead.from_dict({"company": "Acme", "not_a_real_field": 123})
    assert lead.company == "Acme"
