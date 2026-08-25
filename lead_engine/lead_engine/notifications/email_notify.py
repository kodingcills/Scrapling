"""End-of-run email notifications. Optional, dependency-free (stdlib smtplib)."""

import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional

from scrapling.core.utils import log

from lead_engine.config import settings


def _subject(command: str, counts: Dict[str, int]) -> str:
    summary = ", ".join(f"{value} {key}" for key, value in counts.items()) or "no activity"
    return f"[lead-engine] {command}: {summary}"


def _body(command: str, counts: Dict[str, int], errors: Optional[List[str]]) -> str:
    lines = [f"lead_engine run finished: {command}", ""]
    for key, value in counts.items():
        lines.append(f"{key}: {value}")
    if errors:
        lines.append("")
        lines.append(f"errors ({len(errors)}):")
        for error in errors[:5]:
            lines.append(f"  - {error}")
        if len(errors) > 5:
            lines.append(f"  ... and {len(errors) - 5} more")
    return "\n".join(lines)


def send_run_summary(command: str, counts: Dict[str, int], errors: Optional[List[str]] = None) -> None:
    """Email a short run summary. Never raises: notification failures are
    logged and swallowed so they can't fail the underlying pipeline command.

    No-ops when SMTP isn't configured (settings.notifications_configured).
    """
    if not settings.notifications_configured:
        log.debug("Email notifications not configured (SMTP_* / NOTIFY_TO_ADDRESS); skipping run summary")
        return

    message = EmailMessage()
    message["Subject"] = _subject(command, counts)
    message["From"] = settings.smtp_from_address
    message["To"] = settings.notify_to_address
    message.set_content(_body(command, counts, errors))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        log.info(f"Run summary emailed to {settings.notify_to_address}")
    except Exception:
        # A notification failure must never fail the scrape/enrich/draft command.
        log.exception("Failed to send run-summary email; continuing")


__all__ = ["send_run_summary"]
