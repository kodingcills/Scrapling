"""
Reusable fetch behavior profiles and human-timing helpers.

A profile is a dictionary of default fetch/session keyword arguments that a
`BaseFetcher` subclass can ship as a class attribute (``profile``). Explicit
keyword arguments at the call site always win over profile values, so a
profile tunes the *defaults* without removing any flexibility.

The profiles here are biased toward "looks like a normal person browsing from
a residential/office IP" rather than toward beating enterprise bot management:
they are meant for small sites (manufacturer career pages, integrator
directories, company About pages) that see very little traffic.
"""

from random import uniform
from time import sleep as _sleep

from scrapling.core._types import Any, Dict

# A polite, human-like browsing profile for low-security targets.
# - `google_search=False`: arriving with a Google referer on every deep page of a
#   small site is unnatural; direct navigation is what real visitors look like.
# - `disable_resources=False`: load fonts/images like a real browser would;
#   dropping resources is a speed trick that leaves a detectable request pattern.
# - `network_idle=True`: small sites lazy-load content; wait for it to settle.
# - `hide_canvas=True`: cheap canvas-noise defense, harmless on non-WAF targets.
POLITE_BROWSING_PROFILE: Dict[str, Any] = {
    "google_search": False,
    "disable_resources": False,
    "network_idle": True,
    "hide_canvas": True,
}


def merge_profile(kwargs: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a profile under explicit call kwargs; call kwargs win.

    `extra_headers` is merged key-by-key instead of replaced, so a profile can
    contribute courtesy headers while the caller can still override them.
    """
    merged = {**profile, **kwargs}
    profile_headers = profile.get("extra_headers") or {}
    if profile_headers:
        merged["extra_headers"] = {**profile_headers, **(kwargs.get("extra_headers") or {})}
    return merged


def human_delay(base: float, jitter: float = 0.25, minimum: float = 0.0) -> float:
    """Return `base` scaled by a random factor in [1-jitter, 1+jitter], floored at `minimum`.

    Metronome-exact delays are a classic crawler tell; this adds just enough
    randomness to look human without slowing the crawl meaningfully.

    :param base: The delay in seconds before randomization.
    :param jitter: Relative randomization, e.g. 0.25 means ±25%.
    :param minimum: Lowest delay allowed after randomization.
    """
    if base <= 0:
        return max(base, minimum)
    factor = uniform(1.0 - jitter, 1.0 + jitter) if jitter > 0 else 1.0
    return max(base * factor, minimum)


def human_sleep(base: float, jitter: float = 0.25, minimum: float = 0.0) -> None:
    """Blocking sleep for a human-randomized duration. See `human_delay`."""
    _sleep(human_delay(base, jitter, minimum))
