"""lead_engine CLI.

Usage:
    python main.py targets <targets.yaml> [--out leads.jsonl] [--no-sync]
    python main.py career-pages <url> [--company NAME] [--out leads.jsonl] [--no-sync]
    python main.py fanuc [--zip 21250] [--radius 100] [--out leads.jsonl] [--no-sync]
    python main.py team-page <url> [--company NAME] [--out leads.jsonl] [--no-sync]
    python main.py sync-jsonl <leads.jsonl>
    python main.py enrich <leads.jsonl> [--no-sync]
    python main.py draft <leads.jsonl> [--force] [--no-sync]

`targets` is the real entry point for running this against a company list
(see data/target_companies.yaml) - it loops career-pages (and team-page,
when a target has team_url) across every company in one run, isolating
failures per-company so one bad site doesn't kill the batch, and syncs
everything once at the end. `career-pages`/`team-page` on a single URL
still exist for one-off runs and debugging.
"""

import argparse
import json
import sys

import yaml
from datetime import datetime, timezone
from pathlib import Path

from scrapling.core.utils import log

from lead_engine.config import settings
from lead_engine.drafters.slot_drafter import draft_for_lead
from lead_engine.models import Lead
from lead_engine.notifications.email_notify import send_run_summary


def load_leads(path: Path) -> list:
    leads = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                leads.append(Lead.from_dict(json.loads(line)))
            except (ValueError, TypeError) as error:
                log.warning(f"{path.name}:{line_number}: skipping bad record ({error})")
    return leads


def save_leads(path: Path, leads: list) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for lead in leads:
            handle.write(json.dumps(lead.to_dict(), ensure_ascii=False) + "\n")


def _default_out(label: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path("data")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"leads_{label}_{ts}.jsonl"


def _sync_leads(leads: list) -> int:
    """Push leads to Notion (create or update in place, deduped by Source
    URL). Returns the number successfully synced."""
    if not (settings.notion_token and settings.notion_database_id):
        log.warning("NOTION_TOKEN / NOTION_DATABASE_ID not set; skipping Notion sync")
        return 0
    from lead_engine.notion_sync.client import NotionClient

    client = NotionClient(settings.notion_token, settings.notion_database_id)
    synced = 0
    for lead in leads:
        try:
            page_id = client.upsert_lead(lead)
            log.info(f"Synced {lead.source_url or lead.company} -> {page_id}")
            synced += 1
        except Exception as error:  # noqa: BLE001 - one bad row shouldn't stop the batch
            log.error(f"Sync failed for {lead.source_url or lead.company}: {error}")
    return synced


def _load_targets(path: Path) -> list:
    """Load and validate a targets YAML file.

    Expected shape:
        targets:
          - company: "Acme Robotics"
            career_url: "https://acme.example.com/careers"
            team_url: "https://acme.example.com/about/team"   # optional

    Raises ValueError with a specific, actionable message on malformed
    input rather than letting a KeyError/TypeError surface from deep in
    the loop - this runs unattended across many companies, a clear error
    up front beats a confusing traceback three companies in.
    """
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    raw_targets = data.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError(f"{path}: expected a top-level 'targets' list with at least one entry")

    targets = []
    for index, entry in enumerate(raw_targets):
        if not isinstance(entry, dict) or "company" not in entry:
            raise ValueError(f"{path}: targets[{index}] must be a mapping with at least a 'company' key")
        career_url = entry.get("career_url", "")
        team_url = entry.get("team_url", "")
        if not career_url and not team_url:
            raise ValueError(f"{path}: targets[{index}] ({entry['company']!r}) has neither career_url nor team_url")
        targets.append({"company": entry["company"], "career_url": career_url, "team_url": team_url})
    return targets


def cmd_targets(args: argparse.Namespace) -> int:
    from scrapling.fetchers import LeadEngineFetcher

    from lead_engine.scrapers import career_pages, team_pages

    targets_path = Path(args.targets_file)
    if not targets_path.is_file():
        log.error(f"Not a file: {targets_path}")
        return 1

    try:
        targets = _load_targets(targets_path)
    except ValueError as error:
        log.error(str(error))
        return 1

    log.info(f"Loaded {len(targets)} target compan{'y' if len(targets) == 1 else 'ies'} from {targets_path}")

    all_leads = []
    per_company_errors = []
    for target in targets:
        company = target["company"]
        for url_key, label, module in (
            ("career_url", "career page", career_pages),
            ("team_url", "team page", team_pages),
        ):
            url = target[url_key]
            if not url:
                continue
            log.info(f"[{company}] fetching {label}: {url}")
            try:
                response = LeadEngineFetcher.fetch(url)
                leads = module.build_leads(response, company=company)
                log.info(f"[{company}] extracted {len(leads)} lead(s) from {label}")
                all_leads.extend(leads)
            except Exception as error:  # noqa: BLE001 - one company's site being down must not kill the batch
                log.error(f"[{company}] {label} failed, skipping: {error}")
                per_company_errors.append(f"{company} ({label}): {error}")

    out_path = Path(args.out) if args.out else _default_out("targets")
    save_leads(out_path, all_leads)
    log.info(f"Saved {len(all_leads)} total lead(s) -> {out_path}")

    synced = 0 if args.no_sync else _sync_leads(all_leads)
    send_run_summary(
        "targets",
        {
            "companies": len(targets),
            "extracted": len(all_leads),
            "synced": synced,
            "errors": len(per_company_errors),
        },
        errors=per_company_errors or None,
    )
    return 0


def cmd_career_pages(args: argparse.Namespace) -> int:
    from scrapling.fetchers import LeadEngineFetcher

    from lead_engine.scrapers import career_pages

    company = args.company or ""
    log.info(f"Fetching career page: {args.url}")
    response = LeadEngineFetcher.fetch(args.url)
    leads = career_pages.build_leads(response, company=company)
    log.info(f"Extracted {len(leads)} lead(s) from {args.url}")

    out_path = Path(args.out) if args.out else _default_out("career_pages")
    save_leads(out_path, leads)
    log.info(f"Saved -> {out_path}")

    synced = 0 if args.no_sync else _sync_leads(leads)
    send_run_summary("career-pages", {"url": args.url, "extracted": len(leads), "synced": synced})
    return 0


def cmd_fanuc(args: argparse.Namespace) -> int:
    from lead_engine.scrapers.integrator_directories import fetch_fanuc_integrators

    log.info(f"Fetching FANUC ASI directory: zip={args.zip} radius={args.radius}")
    leads = fetch_fanuc_integrators(zip_code=args.zip, radius=args.radius)
    log.info(f"Extracted {len(leads)} integrator lead(s)")

    out_path = Path(args.out) if args.out else _default_out("fanuc")
    save_leads(out_path, leads)
    log.info(f"Saved -> {out_path}")

    synced = 0 if args.no_sync else _sync_leads(leads)
    send_run_summary("fanuc", {"zip": args.zip, "radius": args.radius, "extracted": len(leads), "synced": synced})
    return 0


def cmd_team_page(args: argparse.Namespace) -> int:
    from scrapling.fetchers import LeadEngineFetcher

    from lead_engine.scrapers import team_pages

    company = args.company or ""
    log.info(f"Fetching team page: {args.url}")
    response = LeadEngineFetcher.fetch(args.url)
    leads = team_pages.build_leads(response, company=company)
    log.info(f"Extracted {len(leads)} lead(s) from {args.url}")

    out_path = Path(args.out) if args.out else _default_out("team_page")
    save_leads(out_path, leads)
    log.info(f"Saved -> {out_path}")

    synced = 0 if args.no_sync else _sync_leads(leads)
    send_run_summary("team-page", {"url": args.url, "extracted": len(leads), "synced": synced})
    return 0


def cmd_sync_jsonl(args: argparse.Namespace) -> int:
    path = Path(args.jsonl)
    if not path.is_file():
        log.error(f"Not a file: {path}")
        return 1

    leads = load_leads(path)
    log.info(f"Loaded {len(leads)} lead(s) from {path}")
    synced = _sync_leads(leads)
    send_run_summary("sync-jsonl", {"loaded": len(leads), "synced": synced})
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    path = Path(args.jsonl)
    if not path.is_file():
        log.error(f"Not a file: {path}")
        return 1

    leads = load_leads(path)
    log.info(f"Loaded {len(leads)} lead(s) from {path}")

    drafted = []
    skipped_no_email = 0
    for index, lead in enumerate(leads):
        # A slot drafter writing to nobody in particular is a wasted Notion row:
        # skip leads that are still account-level / have no email.
        if not lead.email:
            skipped_no_email += 1
            continue
        before = lead.generated_draft
        new_lead = draft_for_lead(lead, force=args.force)
        if new_lead.generated_draft and (not before or args.force):
            drafted.append(new_lead)
        leads[index] = new_lead

    if skipped_no_email:
        log.warning(
            f"Skipped drafting {skipped_no_email} lead(s) with no email; run `enrich` first "
            f"(pipeline order: scrape -> enrich -> draft)"
        )

    save_leads(path, leads)
    log.info(f"Drafted {len(drafted)}/{len(leads)} lead(s); rewrote {path} in place")

    if not args.no_sync:
        if not (settings.notion_token and settings.notion_database_id):
            log.warning("NOTION_TOKEN / NOTION_DATABASE_ID not set; skipping Notion sync")
        else:
            from lead_engine.notion_sync.client import NotionClient

            client = NotionClient(settings.notion_token, settings.notion_database_id)
            for lead in drafted:
                page_id = client.upsert_lead(lead)
                log.info(f"Synced {lead.source_url or lead.company} -> {page_id}")

    send_run_summary(
        "draft",
        {"drafted": len(drafted), "loaded": len(leads), "skipped_no_email": skipped_no_email},
    )
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    path = Path(args.jsonl)
    if not path.is_file():
        log.error(f"Not a file: {path}")
        return 1

    from lead_engine.enrichment.waterfall import FindymailClient, enrich_batch

    try:
        client = FindymailClient()
    except ValueError as error:
        log.error(str(error))
        return 1

    leads = load_leads(path)
    log.info(f"Loaded {len(leads)} lead(s) from {path}")

    leads = enrich_batch(leads, client)

    save_leads(path, leads)
    enriched_count = sum(1 for lead in leads if lead.contact_status in ("valid", "uncertain"))
    log.info(
        f"Enriched {enriched_count}/{len(leads)} lead(s) with a contact email; rewrote {path} in place"
    )

    if not args.no_sync:
        if not (settings.notion_token and settings.notion_database_id):
            log.warning("NOTION_TOKEN / NOTION_DATABASE_ID not set; skipping Notion sync")
        else:
            from lead_engine.notion_sync.client import NotionClient

            notion = NotionClient(settings.notion_token, settings.notion_database_id)
            for lead in leads:
                page_id = notion.upsert_lead(lead)
                log.info(f"Synced {lead.source_url or lead.company} -> {page_id}")

    send_run_summary(
        "enrich",
        {
            "loaded": len(leads),
            "enriched": enriched_count,
            "valid": sum(1 for lead in leads if lead.contact_status == "valid"),
            "uncertain": sum(1 for lead in leads if lead.contact_status == "uncertain"),
            "invalid": sum(1 for lead in leads if lead.contact_status == "invalid"),
        },
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lead_engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    targets_parser = subparsers.add_parser(
        "targets", help="Scrape career pages (and team pages) for every company in a targets YAML file"
    )
    targets_parser.add_argument("targets_file", help="Path to a targets YAML file (see data/target_companies.yaml)")
    targets_parser.add_argument("--out", default=None, help="Output jsonl path (default: data/leads_targets_<ts>.jsonl)")
    targets_parser.add_argument("--no-sync", action="store_true", help="Skip pushing to Notion")
    targets_parser.set_defaults(func=cmd_targets)

    cp_parser = subparsers.add_parser("career-pages", help="Scrape one career page for target-role postings")
    cp_parser.add_argument("url", help="Career page URL to scrape")
    cp_parser.add_argument("--company", default="", help="Company name (defaults to blank)")
    cp_parser.add_argument("--out", default=None, help="Output jsonl path (default: data/leads_career_pages_<ts>.jsonl)")
    cp_parser.add_argument("--no-sync", action="store_true", help="Skip pushing to Notion")
    cp_parser.set_defaults(func=cmd_career_pages)

    fanuc_parser = subparsers.add_parser("fanuc", help="Scrape the FANUC authorized integrator directory")
    fanuc_parser.add_argument("--zip", default="21250", help="ZIP/postal code to search from (default: 21250)")
    fanuc_parser.add_argument("--radius", type=int, default=100, help="Search radius in miles (default: 100)")
    fanuc_parser.add_argument("--out", default=None, help="Output jsonl path (default: data/leads_fanuc_<ts>.jsonl)")
    fanuc_parser.add_argument("--no-sync", action="store_true", help="Skip pushing to Notion")
    fanuc_parser.set_defaults(func=cmd_fanuc)

    tp_parser = subparsers.add_parser("team-page", help="Scrape a company About/Team page for named leads")
    tp_parser.add_argument("url", help="Team/About page URL to scrape")
    tp_parser.add_argument("--company", default="", help="Company name (defaults to blank)")
    tp_parser.add_argument("--out", default=None, help="Output jsonl path (default: data/leads_team_page_<ts>.jsonl)")
    tp_parser.add_argument("--no-sync", action="store_true", help="Skip pushing to Notion")
    tp_parser.set_defaults(func=cmd_team_page)

    sj_parser = subparsers.add_parser("sync-jsonl", help="Push a previously saved leads jsonl to Notion (no re-scraping)")
    sj_parser.add_argument("jsonl", help="Path to a leads jsonl file")
    sj_parser.set_defaults(func=cmd_sync_jsonl)

    draft_parser = subparsers.add_parser("draft", help="Generate outreach drafts for leads in a jsonl file")
    draft_parser.add_argument("jsonl", help="Path to leads jsonl; rewritten in place with drafts populated")
    draft_parser.add_argument("--force", action="store_true", help="Re-draft leads that already have a draft")
    draft_parser.add_argument("--no-sync", action="store_true", help="Skip pushing drafts to Notion")
    draft_parser.set_defaults(func=cmd_draft)

    enrich_parser = subparsers.add_parser(
        "enrich", help="Find + verify contact emails (Findymail) for leads in a jsonl file"
    )
    enrich_parser.add_argument("jsonl", help="Path to leads jsonl; rewritten in place with emails populated")
    enrich_parser.add_argument("--no-sync", action="store_true", help="Skip pushing updates to Notion")
    enrich_parser.set_defaults(func=cmd_enrich)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
