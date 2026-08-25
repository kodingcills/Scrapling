"""lead_engine: lead-gen scraping toolkit built on the tailored Scrapling fork.

Application layer only: target lists, keyword rules, Notion schema. All
reusable anti-detection/throttling behavior lives in the scrapling fork
itself (scrapling.fetchers.LeadEngineFetcher, spiders throttle settings).
"""

from lead_engine.config import CONTACT_EMAIL, SPIDER_DEFAULTS
from lead_engine.models import Company, Lead, Role, TeamMember

__all__ = ["Company", "Role", "TeamMember", "Lead", "CONTACT_EMAIL", "SPIDER_DEFAULTS"]
