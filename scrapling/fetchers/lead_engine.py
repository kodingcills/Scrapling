"""Project-specific fetcher defaults for the lead-engine campaign.

This subclass only hardcodes *defaults*; every call site in the lead_engine
application package can simply do::

    from scrapling.fetchers import LeadEngineFetcher

    page = LeadEngineFetcher.fetch("https://example.com/careers")

and get polite, human-paced stealth fetching with XHR capture enabled, without
repeating five keyword arguments everywhere. Site-specific logic (FANUC's
search endpoint, career-page spiders, classification) stays in lead_engine.
"""

import os

from scrapling.fetchers.stealth_chrome import StealthyFetcher

# robots.txt courtesy convention: identify ourselves with a real contact
# address. Override per deployment with the LEAD_ENGINE_CONTACT_EMAIL env var.
CONTACT_EMAIL = os.environ.get("LEAD_ENGINE_CONTACT_EMAIL", "scraping-ops@example.com")

# Capture JSON/XML endpoints (job boards and directory search usually answer
# through these instead of server-rendered HTML). NOTE: exactly one leading
# (?i); Python >=3.11 rejects inline flags that aren't at the start.
XHR_PATTERN = r"(?i)(?:\.(?:json|xml)(?:\?|$)|/(?:api|jobs|careers|positions|search))"


class LeadEngineFetcher(StealthyFetcher):
    """`StealthyFetcher` tuned for manufacturer/integrator lead-gen crawling."""

    profile = {
        # Polite browsing baseline from the fork's profile module
        **StealthyFetcher.profile,
        # Small sites lazy-load their job widgets; wait for the network to settle
        "network_idle": True,
        # Some integrator directories sit behind Cloudflare turnstiles anyway
        "solve_cloudflare": True,
        # Direct navigation looks human on small sites; no fake Google referer
        "google_search": False,
        # Match the offices we claim to browse from (US manufacturing market)
        "locale": "en-US",
        # Wire XHR capture on so `response.captured_xhr` is always populated
        "capture_xhr": XHR_PATTERN,
        # Courtesy identification per the robots.txt convention
        "extra_headers": {
            "From": CONTACT_EMAIL,
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
