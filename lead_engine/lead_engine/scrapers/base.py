"""Shared classification and extraction helpers used by all scrapers.

One place for the "what do they run" vs "what's hurting" keyword lists:
TECH_STACK_KEYWORDS answers what a site runs, PAIN_KEYWORDS answers what's
hurting. A lead can match one, both, or neither.
"""

from typing import Optional

TITLE_ROLE_MAP = {
    "quality manager": "Quality Manager",
    "quality engineer": "Quality Engineer",
    "manufacturing engineer": "Manufacturing Engineer",
    "process engineer": "Process Engineer",
    "applications engineer": "Applications Engineer (Integrator)",
    "oem applications engineer": "OEM Applications Engineer",
}

EXECUTIVE_TITLES = ("quality manager",)
PRACTITIONER_TITLES = (
    "quality engineer",
    "manufacturing engineer",
    "process engineer",
    "applications engineer",
    "oem applications engineer",
)

PAIN_KEYWORDS = (
    "downtime", "scrap rate", "rework", "cycle time", "bottleneck",
    "changeover", "defect", "tolerance", "calibration", "integration challenge",
)

TECH_STACK_KEYWORDS = (
    "UR5e", "UR10e", "UR3e", "RTDE", "ROS2", "ROS", "cobot", "EtherCAT",
    "PROFINET", "Cognex", "Keyence", "FANUC", "ABB", "KUKA",
    "force torque sensor", "impedance control", "Cartesian", "gripper",
    "end effector", "PLC",
)


def classify_title(title_role: str) -> str:
    """Map a free-text job title onto our canonical TITLE_ROLE vocabulary."""
    lowered = title_role.lower().strip()
    if not lowered:
        return "Other"
    for needle, canonical in TITLE_ROLE_MAP.items():
        if needle in lowered:
            return canonical
    return "Other"


BUYER_TYPE_BY_TITLE_ROLE = {
    "Quality Manager": "Buyer - Quality",
    "Quality Engineer": "Buyer - Quality",
    "Manufacturing Engineer": "Gatekeeper - Process/Mfg Eng",
    "Process Engineer": "Gatekeeper - Process/Mfg Eng",
    "Applications Engineer (Integrator)": "Channel - Integrator",
    "OEM Applications Engineer": "Channel - OEM Apps Eng",
}


def classify_buyer_type(title_role: str) -> str:
    """Map a canonical title_role (from classify_title()) onto the real
    Notion "Buyer Type" select vocabulary. Anything else — including
    "Other" or empty — is "Unclassified"; never guess."""
    return BUYER_TYPE_BY_TITLE_ROLE.get(title_role, "Unclassified")


def _snippet(text: str, keyword: str, window: int = 60) -> str:
    """Extract a short snippet around the first case-insensitive occurrence of `keyword`."""
    idx = text.lower().find(keyword.lower())
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(keyword) + window // 2)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def find_pain_signal(text: str) -> str:
    """Return a short snippet around the first pain-keyword hit, or ''."""
    if not text:
        return ""
    for keyword in PAIN_KEYWORDS:
        if keyword.lower() in text.lower():
            return _snippet(text, keyword)
    return ""


def find_tech_stack_mention(text: str) -> str:
    """Return a short snippet around the first tech-stack mention, or ''.

    Mirrors find_pain_signal()'s extraction pattern but with its own keyword
    list: this answers "what do they run", not "what's hurting".
    """
    if not text:
        return ""
    for keyword in TECH_STACK_KEYWORDS:
        if keyword.lower() in text.lower():
            return _snippet(text, keyword)
    return ""


def classify_persona(title_role: str) -> str:
    """Classify a lead's persona from their role/title.

    Executive: Quality Manager — owns budget, evaluated on plant-level outcomes.
    Practitioner: Quality/Manufacturing/Process/Applications Engineers —
    individual contributors closer to the hardware.
    Unclassified for anything else or empty input; never guess.
    """
    lowered = title_role.lower().strip()
    if not lowered:
        return "Unclassified"
    if any(t in lowered for t in EXECUTIVE_TITLES):
        return "Executive"
    if any(t in lowered for t in PRACTITIONER_TITLES):
        return "Practitioner"
    return "Unclassified"


def page_text(response) -> str:
    """Best-effort plain text of a fetched page, for keyword scanning."""
    try:
        return response.get_all_text(" ")
    except Exception:
        try:
            return response.body.decode(response.encoding, errors="replace")
        except Exception:
            return ""


__all__ = [
    "classify_title",
    "classify_persona",
    "classify_buyer_type",
    "find_pain_signal",
    "find_tech_stack_mention",
    "page_text",
    "PAIN_KEYWORDS",
    "TECH_STACK_KEYWORDS",
]
