"""Campaign-wide configuration for lead_engine."""

import os

from scrapling.fetchers.lead_engine import CONTACT_EMAIL

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
# Single live database: "Precision Assembly Leads"
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")

SPIDER_DEFAULTS = {
    "robots_txt_obey": True,
    "robots_crawl_delay_floor": 5.0,
    "concurrent_requests": 2,
    "concurrent_requests_per_domain": 1,
    "autothrottle_enabled": True,
    "autothrottle_start_delay": 8.0,
    "autothrottle_max_delay": 90.0,
    "autothrottle_block_backoff_factor": 2.5,
    "autothrottle_jitter": 0.3,
}


class Settings:
    def __init__(self):
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.notion_token = os.environ.get("NOTION_TOKEN", "")
        self.notion_database_id = os.environ.get(
            "NOTION_DATABASE_ID", ""
        )  # "Precision Assembly Leads"
        # https://app.findymail.com — Settings/API in their dashboard
        self.findymail_api_key = os.environ.get("FINDYMAIL_API_KEY") or None

        # Optional end-of-run email notifications (stdlib smtplib; works with
        # Gmail via an app password or any STARTTLS provider).
        self.smtp_host = os.environ.get("SMTP_HOST", "")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_username = os.environ.get("SMTP_USERNAME", "")
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self.smtp_from_address = os.environ.get("SMTP_FROM_ADDRESS", "")
        self.notify_to_address = os.environ.get("NOTIFY_TO_ADDRESS", "")

    @property
    def notifications_configured(self) -> bool:
        """True when every SMTP setting needed to send a run summary is present."""
        return bool(
            self.smtp_host
            and self.smtp_username
            and self.smtp_password
            and self.smtp_from_address
            and self.notify_to_address
        )


settings = Settings()

__all__ = ["CONTACT_EMAIL", "NOTION_TOKEN", "NOTION_DATABASE_ID", "SPIDER_DEFAULTS", "settings", "Settings"]
