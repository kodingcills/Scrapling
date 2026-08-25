import pytest

from lead_engine.classify import buyer_signal_score, classify_role, is_decision_maker


@pytest.mark.parametrize(
    "title",
    [
        "Controls Engineer",
        "Senior Robotics Engineer",
        "PLC Programmer",
        "FANUC Robot Technician",
        "Field Service Engineer",
    ],
)
def test_engineering_titles(title):
    assert classify_role(title) == "engineering"


@pytest.mark.parametrize(
    "title",
    [
        "Procurement Manager",
        "Senior Buyer",
        "Purchasing Manager",
        "Supply Chain Analyst",
    ],
)
def test_buyer_titles(title):
    assert classify_role(title) == "buyer"


@pytest.mark.parametrize("title", ["Accountant", "HR Generalist", "Receptionist"])
def test_other_titles(title):
    assert classify_role(title) == "other"


@pytest.mark.parametrize("title", ["CEO", "VP of Sales", "Director of Operations", "Plant Owner"])
def test_decision_makers(title):
    assert is_decision_maker(title)


def test_buyer_signal_score_counts_keywords():
    text = "We are hiring a procurement manager and a sourcing specialist for our supply chain team."
    assert buyer_signal_score(text) >= 3
