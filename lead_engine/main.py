"""lead_engine CLI.

Usage:
    python main.py draft <leads.jsonl> [--force] [--no-sync]
"""

import argparse
import json
import sys
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
