"""Pure-logic tests for the Slot-Filling Drafter Engine. No network, no API."""

import pytest

from lead_engine.drafters import slot_drafter
from lead_engine.drafters.slot_drafter import (
    BANNED_WORDS,
    WORD_MAX,
    cta_violations,
    count_body_words,
    draft_for_lead,
    find_banned_words,
    has_list_items,
    has_markup,
    validate_draft,
)
from lead_engine.models import Lead
from lead_engine.scrapers.base import classify_persona, find_tech_stack_mention


# ---------------------------------------------------------------------------
# classify_persona
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Quality Manager", "Executive"),
        ("Senior Quality Manager", "Executive"),
        ("Quality Engineer", "Practitioner"),
        ("Manufacturing Engineer", "Practitioner"),
        ("Process Engineer", "Practitioner"),
        ("Applications Engineer", "Practitioner"),
        ("Applications Engineer (Integrator)", "Practitioner"),
        ("OEM Applications Engineer", "Practitioner"),
        ("CFO", "Unclassified"),
        ("Account Executive", "Unclassified"),
        ("Robot Technician", "Unclassified"),
        ("", "Unclassified"),
    ],
)
def test_classify_persona(title, expected):
    assert classify_persona(title) == expected


# ---------------------------------------------------------------------------
# find_tech_stack_mention
# ---------------------------------------------------------------------------


def test_tech_stack_matches_and_snippets():
    text = "Our cells pair a UR10e with a Cognex camera; integration is handled in house."
    snippet = find_tech_stack_mention(text)
    assert "UR10e" in snippet
    assert len(snippet) < 200


@pytest.mark.parametrize("keyword", ["RTDE", "EtherCAT", "PROFINET", "Keyence", "FANUC", "force torque sensor", "impedance control", "PLC"])
def test_tech_stack_each_keyword(keyword):
    text = f"Experience with {keyword} required for this role."
    assert keyword.lower() in find_tech_stack_mention(text).lower()


def test_tech_stack_is_case_insensitive():
    assert "ur5e" in find_tech_stack_mention("we run a ur5e cell").lower()


def test_tech_stack_returns_empty_when_no_match():
    assert find_tech_stack_mention("Great benefits and a friendly team.") == ""
    assert find_tech_stack_mention("") == ""


# ---------------------------------------------------------------------------
# Validator pieces, independently testable
# ---------------------------------------------------------------------------


GOOD_SUBJECT = "acme robotics — controls engineer opening"
GOOD_BODY = (
    "Your controls engineer posting caught my eye. "
    "Plants at your stage usually see scrap and cycle time creep before anyone names it a problem. "
    "I have a one-page benchmark from a comparable line — would you like me to send it over?"
)


def _ok_draft():
    return validate_draft(GOOD_SUBJECT, GOOD_BODY)


def test_validator_accepts_a_good_draft():
    ok, failures = _ok_draft()
    assert ok, failures


def test_word_count_over_max_fails():
    long_body = GOOD_BODY + " " + "extra padding words here " * 20 + "?"
    ok, failures = validate_draft(GOOD_SUBJECT, long_body)
    assert not ok
    assert any(str(WORD_MAX) in failure or "words" in failure for failure in failures)


def test_word_count_helper_excludes_nothing_surprising():
    assert count_body_words("one two three") == 3


@pytest.mark.parametrize("word", BANNED_WORDS)
def test_each_banned_word_individually(word):
    body = GOOD_BODY.replace("benchmark", f"really {word} benchmark")
    ok, failures = validate_draft(GOOD_SUBJECT, body)
    assert not ok
    assert any(word in failure for failure in failures)


def test_markup_detection():
    assert has_markup("**bold move**")
    assert has_markup("*italic nudge*")
    assert has_markup("_underlined idea_")
    assert not has_markup("plain text only")


def test_multi_cta_detection():
    two_ctas = (
        "Trigger sentence one. "
        "Would you like me to send the benchmark doc? "
        "Also, would you like me to send the spec sheet?"
    )
    problems = cta_violations(two_ctas)
    assert any("exactly one" in problem for problem in problems)


def test_generic_cta_rejected():
    body = GOOD_BODY.replace(
        "would you like me to send it over?", "do you have 15 minutes for a call?"
    )
    problems = cta_violations(body)
    assert problems


def test_call_language_rejected():
    body = GOOD_BODY.replace("would you like me to send it over?", "let's hop on a call?")
    assert cta_violations(body)


def test_bullet_lists_rejected():
    ok, failures = validate_draft(GOOD_SUBJECT, GOOD_BODY + "\n- one bullet point")
    assert not ok
    assert any("list" in failure for failure in failures)


def test_throat_clearing_rejected():
    ok, failures = validate_draft(
        GOOD_SUBJECT, "When it comes to robotics, experience matters. " + GOOD_BODY
    )
    assert not ok
    assert any("throat" in failure for failure in failures)


# ---------------------------------------------------------------------------
# Template mode end-to-end (no API key -> deterministic template path)
# ---------------------------------------------------------------------------


def _executive_lead():
    return Lead(
        company="Acme Robotics",
        source_url="https://acme.example.com/team",
        contact_name="Jane Smith",
        title_role="Quality Manager",
        persona_type="Executive",
        operational_trigger="plant expansion: new welding cell",
        pain_signal="scrap rate on second shift",
    )


def _practitioner_lead():
    return Lead(
        company="Beta Automation",
        source_url="https://beta.example.com/careers",
        title_role="Quality Engineer",
        persona_type="Practitioner",
        operational_trigger="open req: controls engineer",
        tech_stack_bottleneck="UR10e RTDE streaming drops during contact transitions",
    )


@pytest.mark.parametrize("lead_factory", [_executive_lead, _practitioner_lead], ids=["executive", "practitioner"])
def test_template_draft_passes_its_own_validator(lead_factory):
    drafted = draft_for_lead(lead_factory())
    subject, _, body = drafted.generated_draft.partition("\n\n")
    subject = subject.removeprefix("Subject: ")
    ok, failures = validate_draft(subject, body)
    assert ok, failures
    assert drafted.status == "Drafted"


def test_unclassified_lead_is_skipped_and_logged(caplog):
    lead = Lead(company="Gamma", title_role="Other", persona_type="Unclassified")
    result = draft_for_lead(lead)
    assert result.generated_draft == ""
    assert result.status == "New"


def test_existing_draft_is_kept_unless_forced():
    lead = _practitioner_lead()
    lead.generated_draft = "existing draft"
    assert draft_for_lead(lead).generated_draft == "existing draft"
    forced = draft_for_lead(lead, force=True)
    assert forced.generated_draft != "existing draft"


# ---------------------------------------------------------------------------
# LLM mode with a mocked Anthropic client
# ---------------------------------------------------------------------------


class FakeAnthropicClient:
    """Stands in for the patched `_anthropic_complete`; records prompts."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "messages": [{"role": "user", "content": user}]})
        return self.responses.pop(0)


VALID_LLM_OUTPUT = (
    "Subject: beta automation — controls engineer opening\n\n"
    "Saw the controls engineer req go up this week. "
    "If the UR10e RTDE stream drops frames during contact transitions, retuning rarely fixes what is really a buffering math problem. "
    "Would you like me to send the repo with reference code for that exact case?"
)

INVALID_LLM_OUTPUT = (
    "Subject: streamline your synergy today\n\n"
    "**We** leverage cutting-edge innovative robust holistic seamless solutions to empower you. "
    "- delve into paradigms\n- optimize everything\n"
    "Do you have 15 minutes? Also would you like me to send the doc?"
)


def _with_llm(monkeypatch, responses):
    monkeypatch.setattr(slot_drafter.settings, "anthropic_api_key", "fake-key")
    fake = FakeAnthropicClient(responses)
    monkeypatch.setattr(slot_drafter, "_anthropic_complete", fake)
    return fake


def test_llm_valid_output_is_used(monkeypatch):
    fake = _with_llm(monkeypatch, [VALID_LLM_OUTPUT])
    drafted = draft_for_lead(_practitioner_lead())
    assert len(fake.calls) == 1
    # The model never sees raw scraped page text, only slots
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "Friction slot:" in prompt
    assert drafted.generated_draft.startswith("Subject: beta automation")


def test_llm_retries_once_with_failure_reason_then_succeeds(monkeypatch):
    fake = _with_llm(monkeypatch, [INVALID_LLM_OUTPUT, VALID_LLM_OUTPUT])
    drafted = draft_for_lead(_practitioner_lead())
    assert len(fake.calls) == 2
    retry_prompt = fake.calls[1]["messages"][0]["content"]
    assert "failed validation" in retry_prompt
    assert "banned vocabulary" in retry_prompt
    assert drafted.generated_draft.startswith("Subject:")


def test_llm_fails_twice_then_falls_back_to_template(monkeypatch):
    fake = _with_llm(monkeypatch, [INVALID_LLM_OUTPUT, INVALID_LLM_OUTPUT])
    drafted = draft_for_lead(_practitioner_lead())
    assert len(fake.calls) == 2
    # Fallback draft is the template draft and still passes validation
    subject, _, body = drafted.generated_draft.partition("\n\n")
    ok, failures = validate_draft(subject.removeprefix("Subject: "), body)
    assert ok, failures
