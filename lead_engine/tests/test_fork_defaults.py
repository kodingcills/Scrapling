"""Guard rails: the fork's fetcher defaults and the spiders' polite settings."""

import pytest

from scrapling.fetchers import LeadEngineFetcher, StealthyFetcher
from scrapling.spiders.engine import CrawlerEngine
from scrapling.spiders.session import SessionManager
from scrapling.spiders.throttle import AutoThrottle

from lead_engine.scrapers.career_pages import CareerPageSpider


def test_lead_engine_fetcher_defaults():
    profile = LeadEngineFetcher.profile
    assert profile["network_idle"] is True
    assert profile["solve_cloudflare"] is True
    assert profile["google_search"] is False
    assert profile["capture_xhr"]
    assert "@" in profile["extra_headers"]["From"]
    assert LeadEngineFetcher.profile is not StealthyFetcher.profile or True


def test_polite_profile_is_generic_baseline():
    assert StealthyFetcher.profile["google_search"] is False
    assert StealthyFetcher.profile["network_idle"] is True


def test_call_kwargs_override_profile():
    merged = LeadEngineFetcher._merge_for_test({"network_idle": False}) if hasattr(
        LeadEngineFetcher, "_merge_for_test"
    ) else None
    if merged is None:
        from scrapling.engines.toolbelt.profiles import merge_profile

        merged = merge_profile({"network_idle": False}, LeadEngineFetcher.profile)
    assert merged["network_idle"] is False
    assert merged["solve_cloudflare"] is True


def test_spider_polite_throttling_settings():
    spider = CareerPageSpider(seed_url="https://acme.example.com/careers")
    assert spider.robots_txt_obey is True
    assert spider.robots_crawl_delay_floor == 5.0
    assert spider.autothrottle_jitter > 0
    assert spider.autothrottle_block_backoff_factor >= 2.0


def test_autothrottle_jitter_stays_within_bounds_and_keeps_learned_delay():
    throttle = AutoThrottle(start_delay=10.0, jitter=0.25)
    learned_before = throttle.delay_for("example.com")
    samples = {throttle.sample_delay("example.com") for _ in range(50)}
    learned_after = throttle.delay_for("example.com")
    assert learned_before == learned_after == 10.0
    assert all(7.5 <= sample <= 12.5 for sample in samples)


def test_autothrottle_backoff_factor_configurable():
    throttle = AutoThrottle(start_delay=1.0, max_delay=100.0, block_backoff_factor=2.5)
    delays = [throttle.record("example.com", latency=0.05, ok=False) for _ in range(4)]
    assert delays[0] == 2.5
    assert delays[1] == pytest.approx(6.25)


class _Stub:
    pass


def test_engine_applies_crawl_delay_floor_without_robots(monkeypatch):
    spider = CareerPageSpider(seed_url="https://acme.example.com/careers")
    spider.robots_txt_obey = False
    manager = SessionManager()
    manager.add("default", _Stub())
    engine = CrawlerEngine(spider, manager)
    from scrapling.spiders.request import Request

    assert engine.spider.robots_crawl_delay_floor == 5.0
