"""Tests for scrapers/base.py title classification and keyword extraction."""

from lead_engine.scrapers.base import (
    classify_persona,
    classify_title,
    find_pain_signal,
    find_tech_stack_mention,
)


def test_classify_title_canonical_mapping():
    assert classify_title("Senior Quality Manager") == "Quality Manager"
    assert classify_title("Manufacturing Engineer II") == "Manufacturing Engineer"
    assert classify_title("Applications Engineer - Integrator") == "Applications Engineer (Integrator)"
    assert classify_title("CNC Machinist") == "Other"
    assert classify_title("") == "Other"


def test_classify_persona_routing():
    assert classify_persona("Quality Manager") == "Executive"
    for practitioner in (
        "Quality Engineer",
        "Manufacturing Engineer",
        "Process Engineer",
        "Applications Engineer (Integrator)",
        "OEM Applications Engineer",
    ):
        assert classify_persona(practitioner) == "Practitioner"
    assert classify_persona("Plant Controller") == "Unclassified"
    assert classify_persona("") == "Unclassified"


def test_pain_and_tech_keywords_are_separate_lists():
    pain_only = "We're drowning in rework and downtime."
    tech_only = "Cells run PROFINET with a Keyence vision system."
    assert find_pain_signal(pain_only) and not find_tech_stack_mention(pain_only)
    assert find_tech_stack_mention(tech_only) and not find_pain_signal(tech_only)

    both = "Our PROFINET cells suffer constant downtime."
    assert both.lower() in (find_pain_signal(both) + find_tech_stack_mention(both)).lower() or (
        find_pain_signal(both) and find_tech_stack_mention(both)
    )
