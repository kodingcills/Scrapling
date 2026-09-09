"""Data models for companies, roles, team contacts, and leads."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

PERSONA_TYPE_OPTIONS = {"Executive", "Practitioner", "Unclassified"}
STATUS_OPTIONS = {
    "New", "Reviewed", "Queued", "Drafted", "Contacted", "Responded", "Disqualified",
}
TITLE_ROLE_OPTIONS = {
    "Quality Manager", "Quality Engineer", "Manufacturing Engineer",
    "Process Engineer", "Applications Engineer (Integrator)",
    "OEM Applications Engineer", "Other",
}
BUYER_TYPE_OPTIONS = {
    "Buyer - Quality",
    "Gatekeeper - Process/Mfg Eng",
    "Channel - Integrator",
    "Channel - OEM Apps Eng",
    "Unclassified",
}
SOURCE_TYPE_OPTIONS = {"career_page", "team_page", "integrator_directory"}
CONTACT_STATUS_OPTIONS = {"not_attempted", "valid", "uncertain", "invalid", "no_credits"}


@dataclass
class Role:
    title: str
    url: str = ""
    location: str = ""
    company: str = ""
    category: str = "other"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "location": self.location,
            "company": self.company,
            "category": self.category,
        }


@dataclass
class TeamMember:
    name: str
    title: str = ""
    email: str = ""
    linkedin: str = ""
    company: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "email": self.email,
            "linkedin": self.linkedin,
            "company": self.company,
        }


@dataclass
class Company:
    name: str
    website: str
    kind: str = "unknown"
    roles: List[Role] = field(default_factory=list)
    team: List[TeamMember] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "website": self.website,
            "kind": self.kind,
            "roles": [r.to_dict() for r in self.roles],
            "team": [m.to_dict() for m in self.team],
            "notes": self.notes,
        }


@dataclass
class Lead:
    company: str = ""
    source_url: str = ""
    contact_name: str = ""
    is_named: bool = False
    title_role: str = "Other"
    buyer_type: str = "Unclassified"
    source_type: str = "career_page"
    operational_trigger: str = ""
    pain_signal: str = ""
    persona_type: str = "Unclassified"
    tech_stack_bottleneck: str = ""
    generated_draft: str = ""
    status: str = "New"
    email: str = ""
    contact_status: str = "not_attempted"
    linkedin: str = ""
    company_description: str = ""

    def __post_init__(self):
        if self.persona_type not in PERSONA_TYPE_OPTIONS:
            raise ValueError(f"persona_type must be one of {sorted(PERSONA_TYPE_OPTIONS)}, got {self.persona_type!r}")
        if self.status not in STATUS_OPTIONS:
            raise ValueError(f"status must be one of {sorted(STATUS_OPTIONS)}, got {self.status!r}")
        if self.title_role not in TITLE_ROLE_OPTIONS:
            raise ValueError(f"title_role must be one of {sorted(TITLE_ROLE_OPTIONS)}, got {self.title_role!r}")
        if self.buyer_type not in BUYER_TYPE_OPTIONS:
            raise ValueError(f"buyer_type must be one of {sorted(BUYER_TYPE_OPTIONS)}, got {self.buyer_type!r}")
        if self.source_type not in SOURCE_TYPE_OPTIONS:
            raise ValueError(f"source_type must be one of {sorted(SOURCE_TYPE_OPTIONS)}, got {self.source_type!r}")
        if self.contact_status not in CONTACT_STATUS_OPTIONS:
            raise ValueError(
                f"contact_status must be one of {sorted(CONTACT_STATUS_OPTIONS)}, got {self.contact_status!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company": self.company,
            "source_url": self.source_url,
            "contact_name": self.contact_name,
            "is_named": self.is_named,
            "title_role": self.title_role,
            "buyer_type": self.buyer_type,
            "source_type": self.source_type,
            "operational_trigger": self.operational_trigger,
            "pain_signal": self.pain_signal,
            "persona_type": self.persona_type,
            "tech_stack_bottleneck": self.tech_stack_bottleneck,
            "generated_draft": self.generated_draft,
        "status": self.status,
        "email": self.email,
        "contact_status": self.contact_status,
        "linkedin": self.linkedin,
        "company_description": self.company_description,
    }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Lead":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


__all__ = [
    "Company",
    "Role",
    "TeamMember",
    "Lead",
    "PERSONA_TYPE_OPTIONS",
    "STATUS_OPTIONS",
    "TITLE_ROLE_OPTIONS",
    "BUYER_TYPE_OPTIONS",
    "SOURCE_TYPE_OPTIONS",
    "CONTACT_STATUS_OPTIONS",
]
