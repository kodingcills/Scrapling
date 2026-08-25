"""Contact-waterfall enrichment worker.

Finds and verifies a contact email for each Lead using Findymail
(https://app.findymail.com — email find + verify ONLY; there is no phone
endpoint, direct-dial numbers would be a second provider / separate task).

Waterfall per lead:
1. Already have an email verified `valid` -> skip (idempotent re-runs).
2. Named lead (`is_named`) -> POST api/search/name with the domain parsed
   from source_url.
3. Account-level lead -> POST api/search/domain with roles=[title_role];
   a hit backfills the contact name, upgrading the lead to a named contact.
4. Any found (or stale) email is re-gated through POST api/verify:
   verified=true -> "valid"; verified=false -> "uncertain" (kept for manual
   review; catch-all domains are often reachable, just unconfirmed).
5. No email found at all -> "invalid", email left empty.

Batch runs pre-check GET api/credits, estimate 2 calls per lead (finder +
verify), warn and truncate rather than silently burning to zero, and cap
concurrent domain searches at 5 per Findymail's documented limit.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from scrapling.core.utils import log

from lead_engine.config import settings
from lead_engine.models import Lead

DEFAULT_BASE_URL = "https://app.findymail.com/api"
MAX_CONCURRENT_DOMAIN_SEARCHES = 5
ESTIMATED_CALLS_PER_LEAD = 2  # finder + verify


class FindymailError(RuntimeError):
    pass


class FindymailClient:
    """Thin Findymail REST client with an injectable transport for tests."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL, transport=None):
        """
        :param api_key: Findymail API key; defaults to config.settings.findymail_api_key.
        :param base_url: API base URL (confirm against your account's key page if this 404s).
        :param transport: Callable(method, url, headers, json_body) -> (status, body_dict);
            defaults to a `requests.Session` capped at MAX_CONCURRENT_DOMAIN_SEARCHES.
        """
        self.api_key = api_key or settings.findymail_api_key
        self.base_url = base_url.rstrip("/")
        if not self.api_key:
            raise ValueError("Findymail API key missing; set FINDYMAIL_API_KEY")
        if transport is not None:
            self._transport = transport
        else:
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_maxsize=MAX_CONCURRENT_DOMAIN_SEARCHES)
            session.mount("https://", adapter)
            self._session = session
            self._transport = self._requests_transport

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _requests_transport(self, method: str, url: str, headers: Dict[str, str], json_body):
        response = self._session.request(method, url, headers=headers, json=json_body, timeout=30)
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.status_code, body

    def _call(self, method: str, path: str, json_body=None):
        status, body = self._transport(method, f"{self.base_url}/{path.lstrip('/')}", self._headers(), json_body)
        if status != 200:
            raise FindymailError(f"Findymail {method} {path} failed with {status}: {body}")
        return body

    def search_name(self, name: str, domain: str) -> Optional[Dict[str, Any]]:
        """POST api/search/name -> {"contact": {...}} or None when nothing was found."""
        body = self._call("POST", "search/name", {"name": name, "domain": domain})
        return body.get("contact") or None

    def search_domain(self, domain: str, roles: List[str]) -> List[Dict[str, Any]]:
        """POST api/search/domain -> list of contacts (max 3 roles allowed)."""
        body = self._call("POST", "search/domain", {"domain": domain, "roles": roles[:3]})
        return body.get("contacts") or []

    def verify(self, email: str) -> bool:
        """POST api/verify -> verified bool."""
        body = self._call("POST", "verify", {"email": email})
        return bool(body.get("verified"))

    def credits(self) -> Dict[str, int]:
        """GET api/credits -> {"credits", "verifier_credits"}."""
        return self._call("GET", "credits")


def domain_from_url(url: str) -> str:
    """Parse the bare registrable domain ('www.' stripped) from a URL."""
    netloc = urlparse(url).netloc.lower()
    return netloc.removeprefix("www.")


def enrich_lead(lead: Lead, client: FindymailClient) -> Lead:
    """Return a copy of `lead` with email/contact_status populated."""
    if lead.email and lead.contact_status == "valid":
        return lead

    new_lead = deepcopy(lead)
    domain = domain_from_url(lead.source_url)

    email = ""
    try:
        if not lead.email:
            if lead.is_named and lead.contact_name and domain:
                contact = client.search_name(lead.contact_name, domain)
                if contact:
                    email = contact.get("email", "")
            elif domain:
                contacts = client.search_domain(domain, [lead.title_role])
                if contacts:
                    match = contacts[0]
                    email = match.get("email", "")
                    if match.get("name"):
                        # Upgrade from account-level to a named contact
                        new_lead.contact_name = match["name"]
                        new_lead.is_named = True

        if not email:
            if lead.email:
                # Stale/never-verified email: re-check it instead of re-finding
                email = lead.email
            else:
                new_lead.email = ""
                new_lead.contact_status = "invalid"
                log.info(f"No email found for {new_lead.company or new_lead.source_url}; marked invalid")
                return new_lead

        verified = client.verify(email)
        new_lead.email = email
        # Keep the email even when unconfirmed; catch-all domains are often reachable.
        new_lead.contact_status = "valid" if verified else "uncertain"
        if not verified:
            log.warning(f"Email {email} failed verification; flagged uncertain for manual review")
    except FindymailError as error:
        log.warning(f"Findymail enrichment failed for {lead.source_url}: {error}")
        new_lead.contact_status = "no_credits" if "credit" in str(error).lower() else "not_attempted"
        return new_lead

    return new_lead


def enrich_batch(leads: List[Lead], client: Optional[FindymailClient] = None) -> List[Lead]:
    """Enrich a batch with a credits pre-check and a 5-way concurrency cap."""
    client = client or FindymailClient()

    try:
        remaining = client.credits()
    except FindymailError as error:
        log.error(f"Could not read Findymail credits ({error}); aborting batch before spending anything")
        return [
            deepcopy(lead)
            if not (lead.email and lead.contact_status == "valid")
            else lead
            for lead in leads
        ]

    finder_credits = int(remaining.get("credits", 0))
    verifier_credits = int(remaining.get("verifier_credits", 0))
    usable = min(finder_credits, verifier_credits)
    max_leads = max(usable // ESTIMATED_CALLS_PER_LEAD, 0)

    pending = [lead for lead in leads if not (lead.email and lead.contact_status == "valid")]
    skipped = len(pending) - min(len(pending), max_leads)
    if skipped > 0:
        log.warning(
            f"Findymail credits low (finder={finder_credits}, verifier={verifier_credits}): "
            f"processing only {max_leads} of {len(pending)} pending lead(s), skipping {skipped}"
        )

    to_process = []
    results: List[Lead] = []
    for index, lead in enumerate(leads):
        if lead.email and lead.contact_status == "valid":
            results.append(lead)
        elif len(to_process) < max_leads:
            to_process.append(index)
            results.append(None)  # placeholder
        else:
            results.append(deepcopy(lead))
            if lead.contact_status == "not_attempted":
                lead_copy = results[-1]
                lead_copy.contact_status = "no_credits"

    if to_process:
        batch = [leads[i] for i in to_process]
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOMAIN_SEARCHES) as pool:
            enriched = list(pool.map(lambda lead: enrich_lead(lead, client), batch))
        for index, enriched_lead in zip(to_process, enriched):
            results[index] = enriched_lead

    return results


__all__ = [
    "FindymailClient",
    "FindymailError",
    "enrich_lead",
    "enrich_batch",
    "domain_from_url",
    "MAX_CONCURRENT_DOMAIN_SEARCHES",
]
