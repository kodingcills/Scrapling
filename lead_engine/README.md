# lead_engine

Lead-gen scraping toolkit built **on top of the tailored Scrapling fork that
lives one directory up** (`../scrapling`), not on PyPI Scrapling.

## Setup

```bash
pip install -r requirements.txt   # installs -e ../scrapling[all] first
pip install -e .                  # installs lead_engine itself
```

Anyone cloning both directories together gets the tailored fork automatically;
the `scrapling>=0.4.15` pin in `pyproject.toml` only prevents a fallback to
stock PyPI Scrapling.

## Layout

- `models.py` — Company / Role / TeamMember / Lead dataclasses
- `classify.py` — role & buyer keyword rules (edit here when targeting shifts)
- `scrapers/base.py` — title/persona classification, pain-signal vs tech-stack keyword extraction
- `scrapers/career_pages.py` — career-page link discovery + job extraction + lead building + spider
- `scrapers/integrator_directories.py` — directory listing extraction + captured-XHR/JSON endpoint discovery (FANUC search endpoint workflow)
- `scrapers/team_pages.py` — about/team page people extraction + lead building + spider
- `drafters/slot_drafter.py` — Slot-Filling Drafter Engine: persona-routed, rule-validated outreach drafts (template mode default; Anthropic LLM polish when `ANTHROPIC_API_KEY` is set)
- `notion_sync/client.py` — Notion schema mapping (incl. Persona Type / Tech Stack / Generated Draft / Status select) + thin REST client with `upsert_lead` deduped by Source URL
- `main.py` — CLI: `python main.py draft <leads.jsonl> [--force] [--no-sync]`

All anti-detection/throttling behavior (fetch defaults, XHR capture,
crawl-delay floors, throttle jitter) lives in the fork under
`../scrapling/scrapling/fetchers/lead_engine.py` and the spiders package; see
`../CONTRIBUTING-note.md`.

## Extending it

- **Notion page body**: `NotionClient.upsert_lead()` also writes the generated
  draft into the page body as a 🎯 callout block (`upsert_draft_callout`),
  idempotent via its marker — human-added blocks without the marker are never
  touched.
- **Email notifications**: each subcommand ends with
  `send_run_summary(command, counts)` (stdlib smtplib, STARTTLS). Set the
  `SMTP_*` / `NOTIFY_TO_ADDRESS` vars in `.env` to enable; unset = no-op, and
  send failures are logged, never fatal. Gmail users: app password at
  https://myaccount.google.com/apppasswords.
