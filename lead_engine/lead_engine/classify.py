"""Role/buyer classification from titles and page text.

Keyword rules change often; this is the one file to edit when the target
profile shifts. Kept deliberately dependency-free.
"""

from typing import Optional

ENGINEERING_KEYWORDS = (
    "controls engineer", "robotics engineer", "automation engineer",
    " plc ", "programmable logic", "hmi", "scada",
    "fanuc", "abb", "kuka", "universal robots", "ur+", "motoman",
    "machine vision", "integration engineer", "field service engineer",
    "maintenance technician", "electrical engineer", "mechanical engineer",
    # Canonical TITLE_ROLE_OPTIONS titles so they classify as engineering
    # (kept in sync with scrapers/base.py TITLE_ROLE_MAP)
    "quality engineer", "manufacturing engineer", "process engineer",
)

BUYER_KEYWORDS = (
    "procurement", "purchasing manager", "buyer", "sourcing",
    "supply chain", "vendor manager", "category manager",
    "plant manager", "operations manager", "manufacturing engineer",
)

DECISION_MAKER_TITLES = (
    "ceo", "cto", "coo", "cfo", "owner", "president", "vp ",
    "vice president", "director", "general manager", "head of", "chief ",
)


def _matches(text: str, keywords) -> bool:
    lowered = f" {text.lower()} "
    return any(kw in lowered for kw in keywords)


def classify_role(title: str) -> str:
    """Return 'engineering', 'buyer', or 'other' for a job title."""
    if _matches(title, ENGINEERING_KEYWORDS):
        return "engineering"
    if _matches(title, BUYER_KEYWORDS):
        return "buyer"
    return "other"


def is_decision_maker(title: str) -> bool:
    """True when a team-page title looks like a buying decision maker."""
    lowered = title.lower()
    return any(lowered.startswith(kw.strip()) or kw in lowered for kw in DECISION_MAKER_TITLES)


def buyer_signal_score(text: str) -> int:
    """Count buyer-side signals in free text (about pages, role lists)."""
    lowered = text.lower()
    return sum(1 for kw in BUYER_KEYWORDS if kw in lowered)


__all__ = [
    "classify_role",
    "is_decision_maker",
    "buyer_signal_score",
]
