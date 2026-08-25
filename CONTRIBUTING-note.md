# Contributing note — this repo is a tailored Scrapling fork

This repository is a fork of [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling)
with **lead-gen-specific stealth/throttle tailoring**, plus a sibling application
package (`lead_engine/`) that lives inside this checkout but is kept logically
separate.

## Where things live

| Path | What it is | Changes often? |
|---|---|---|
| `scrapling/` | The library source (fork of upstream) | Only generic, reusable tailoring |
| `lead_engine/` | Campaign application code (career pages, integrator directories, team pages, classification keywords, Notion schema/sync) | Yes — this is the fast-moving layer |

### Fork-specific changes vs. upstream (`scrapling/` only)

- `scrapling/fetchers/stealth_chrome.py` — `StealthyFetcher` now supports a
  class-level `profile` of default kwargs and ships a polite
  residential/office browsing baseline
  (`scrapling/engines/toolbelt/profiles.py`).
- `scrapling/fetchers/lead_engine.py` — `LeadEngineFetcher(StealthyFetcher)`
  with campaign defaults: `network_idle`, `solve_cloudflare`, XHR capture on,
  courtesy `From:` contact header.
- `scrapling/spiders/throttle.py` — `AutoThrottle` gained configurable block
  backoff factor and human-like jitter (`sample_delay`).
- `scrapling/spiders/spider.py` + `engine.py` — new spider settings:
  `robots_crawl_delay_floor` (hard per-domain delay floor even without a
  robots.txt Crawl-delay), `autothrottle_block_backoff_factor`,
  `autothrottle_jitter`.

Keep everything you add to `scrapling/` **generically useful** — site-specific
logic (FANUC search endpoints, keyword rules, Notion mapping) belongs in
`lead_engine/`.

## Staying mergeable with upstream

The `upstream` remote points at D4Vinci/Scrapling:

```bash
git fetch upstream && git merge upstream/main
```

Because all campaign/application code lives in `lead_engine/` (and the fork's
changes are small, additive, and confined to the files above), upstream merges
should not fight application-layer code.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"     # installs THIS checkout, editable
scrapling install           # browser binaries

cd lead_engine
pip install -r requirements.txt   # re-asserts -e ../scrapling[all]
pip install -e ".[dev]"
pytest
```
