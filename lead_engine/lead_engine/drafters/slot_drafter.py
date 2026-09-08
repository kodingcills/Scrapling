"""Slot-Filling Drafter Engine.

Turns classified Leads into short, rule-bound outreach drafts.

Golden rules are enforced by a validator on every draft (template or LLM):
- 75-word target, 80-word absolute max (subject not counted)
- banned vocabulary list
- no bold/italic markup, no bullet/numbered lists in the body
- no throat-clearing openers, no padded closers
- exactly one CTA and it must be a binary yes/no ask tied to a concrete asset
- subject line: short, specific, references the company/plant/trigger

Two generation modes:
- template (default): deterministic slot-filling into a fixed skeleton
- LLM (when config.settings.anthropic_api_key is set): prose polish of the
  same three slots within the same skeleton; validated with the SAME
  validator, retried once with the failure reason appended, then falls back
  to template mode rather than syncing a rule-violating draft.
"""

import re
from copy import deepcopy
from typing import List, Optional, Tuple

from scrapling.core.utils import log

from lead_engine.config import settings
from lead_engine.models import Lead

WORD_TARGET = 75
WORD_MAX = 80

BANNED_WORDS = (
    "delve", "streamline", "cutting-edge", "innovative", "robust",
    "holistic", "paradigm", "leverage", "synergy", "seamless",
    "optimize", "empower",
)

THROAT_CLEARING_OPENERS = (
    "when it comes to",
    "i noticed that",
    "i hope this finds you well",
)

PADDED_CLOSERS = (
    "looking forward to hearing from you",
    "i look forward to hearing from you",
)

# A valid CTA is a binary yes/no question tied to a concrete asset.
ASSET_CTA_PATTERN = re.compile(
    r"would you (?:like|be interested in|want) (?:me to send|a link to|the) .+?\?",
    re.IGNORECASE,
)
GENERIC_CTA_PATTERNS = (
    re.compile(r"hop on a call", re.IGNORECASE),
    re.compile(r"(do you have|got) \d+ minutes", re.IGNORECASE),
    re.compile(r"let'?s (talk|chat|schedule)", re.IGNORECASE),
)
MARKUP_PATTERN = re.compile(r"(\*\*?[^*\n]+\*?!?|_[^_\n]+_)")
LIST_LINE_PATTERN = re.compile(r"^\s*([-*+]|\d+[.)])\s+", re.MULTILINE)


def count_body_words(draft_body: str) -> int:
    return len(draft_body.split())


def find_banned_words(text: str) -> List[str]:
    lowered = text.lower()
    return [word for word in BANNED_WORDS if word in lowered]


def has_markup(text: str) -> bool:
    """Detect bold/italic markup (*, **, _ wrapping any span)."""
    return bool(MARKUP_PATTERN.search(text))


def has_list_items(body: str) -> bool:
    return bool(LIST_LINE_PATTERN.search(body))


def has_throat_clearing(body: str) -> bool:
    lowered = body.lower()
    return any(opener in lowered for opener in THROAT_CLEARING_OPENERS)


def has_padded_closer(body: str) -> bool:
    lowered = body.lower()
    return any(closer in lowered for closer in PADDED_CLOSERS)


def cta_violations(body: str) -> List[str]:
    """Return every CTA-rule violation found in the body."""
    problems: List[str] = []
    generic_hits = [p.pattern for p in GENERIC_CTA_PATTERNS if p.search(body)]
    if generic_hits:
        problems.append(f"generic CTA language used: {generic_hits}")
    question_count = body.count("?")
    asset_cta_count = len(ASSET_CTA_PATTERN.findall(body))
    if question_count == 0:
        problems.append("no CTA found; exactly one binary asset-tied ask required")
    elif asset_cta_count > 1:
        problems.append(f"{asset_cta_count} asset CTAs found; exactly one allowed")
    elif asset_cta_count == 0:
        problems.append("CTA is not a binary yes/no ask tied to a concrete asset")
    return problems


def validate_draft(subject: str, body: str) -> Tuple[bool, List[str]]:
    """Validate a draft against every golden rule. Returns (ok, failure reasons)."""
    failures: List[str] = []
    words = count_body_words(body)
    if words > WORD_MAX:
        failures.append(f"body is {words} words; hard max is {WORD_MAX}")
    elif words > WORD_TARGET:
        failures.append(f"body is {words} words; target is {WORD_TARGET}")
    if words < 20:
        failures.append(f"body is only {words} words; too thin to be useful")

    banned = find_banned_words(f"{subject}\n{body}")
    if banned:
        failures.append(f"banned vocabulary used: {banned}")

    full_text = f"{subject}\n{body}"
    if has_markup(full_text):
        failures.append("bold/italic markup detected")
    if has_list_items(body):
        failures.append("bullet/numbered list detected in body")
    if has_throat_clearing(body):
        failures.append("throat-clearing opener detected")
    if has_padded_closer(body):
        failures.append("padded closer detected")

    failures.extend(cta_violations(body))

    if len(subject) > 60:
        failures.append(f"subject is {len(subject)} chars; keep it under 60")
    if not subject.strip():
        failures.append("empty subject line")

    return (not failures), failures


def _slots_for_lead(lead: Lead) -> dict:
    trigger = lead.operational_trigger or f"{lead.company} hiring"
    if lead.persona_type == "Executive":
        # Yield/scrap/cycle-time framing of the problem
        friction = (
            f"scrap and cycle-time pressure around {lead.pain_signal}"
            if lead.pain_signal
            else "yield and cycle-time pressure on the line"
        )
        asset = "a one-page benchmark from a comparable plant"
    else:
        # Specific hardware/math problem from tech_stack_bottleneck when present
        friction = lead.tech_stack_bottleneck or lead.pain_signal or "controller instability during contact transitions"
        asset = "the repo with our reference integration code"
    return {
        "trigger": _clip(trigger, 14),
        "friction": _clip(friction, 20),
        "asset": asset,
    }


def _clip_chars(text: str, max_chars: int) -> str:
    """Character-bounded truncation (unlike _clip(), which bounds by word
    count and cannot guarantee a character budget - see below)."""
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars - 3].rsplit(" ", 1)[0]
    return truncated + "..."


def _template_subject(lead: Lead) -> str:
    """Build a subject line and guarantee it fits validate_draft()'s 60-char
    cap.

    Previously clipped by word count (_clip(..., 10)), which bounds words,
    not characters - every FANUC integrator lead shares a long
    operational_trigger ("FANUC Authorized System Integrator, NN mi from
    21250"), and a 10-word subject built from a long company name plus that
    trigger reliably ran past 60 chars (68-70 chars observed on real leads),
    crashing draft_for_lead() before any subject even shipped. Clip by
    character count instead, which is what's actually being validated.
    """
    trigger = lead.operational_trigger or lead.company
    trigger_short = trigger.split(":")[-1].strip()
    return _clip_chars(f"{lead.company} — {trigger_short}", 60).lower()


_EXEC_TEMPLATE = (
    "{trigger} caught my eye. "
    "When plants add robots at your stage, the usual tax shows up as scrap and cycle time before anyone calls it a problem. "
    "We put together a one-page benchmark on what that actually costs and how teams contain it — would you like me to send it over?"
)

_PRAC_TEMPLATE = (
    "{trigger} caught my eye. "
    "If you're touching {friction}, the usual fixes (retuning, more filtering) tend to move the symptom, not the math underneath it. "
    "I've got a small repo with reference code for exactly that case — would you like me to send the link?"
)


def _clip(text: str, max_words: int) -> str:
    words = text.split()
    return " ".join(words[:max_words]) + ("..." if len(words) > max_words else "")


def _template_generate(lead: Lead) -> Tuple[str, str]:
    slots = _slots_for_lead(lead)
    subject = _template_subject(lead)
    if lead.persona_type == "Executive":
        body = _EXEC_TEMPLATE.format(**slots)
    else:
        body = _PRAC_TEMPLATE.format(**slots)
    return subject, body


def _llm_system_prompt() -> str:
    return (
        "You write short B2B outreach emails for an industrial robotics services "
        "engineer. Hard constraints, enforced by a validator after you:\n"
        f"- Body must be at most {WORD_MAX} words (target {WORD_TARGET}); subject excluded.\n"
        "- Never use these words anywhere: "
        + ", ".join(BANNED_WORDS)
        + ".\n"
        "- No markdown: no bold/italic markup, no bullets or numbered lists.\n"
        "- No throat-clearing openers ('When it comes to...', 'I noticed that...', 'I hope this finds you well') "
        "and no padding closers ('Looking forward to hearing from you'). A plain signoff line is fine.\n"
        "- Exactly one call to action, phrased as a binary yes/no question tied to a concrete asset "
        "(benchmark doc, spec sheet, repo link). Never 'hop on a call' or 'do you have 15 minutes'.\n"
        "- Subject line: short, specific, lowercase-style, references the company/plant/trigger. Not a pitch.\n"
        "You receive three extracted slot values and a persona voice. Polish the prose within the fixed "
        "three-sentence shape (trigger -> technical friction in the persona's terms -> asset offer as the ask). "
        "Do not invent facts beyond the slots."
    )


def _llm_user_prompt(slots: dict, persona: str, extra: str = "") -> str:
    return (
        f"Persona voice: {persona}\n"
        f"Trigger slot: {slots['trigger']}\n"
        f"{'Bottleneck' if persona == 'Executive' else 'Friction'} slot: {slots['friction']}\n"
        f"Asset slot: {slots['asset']}\n"
        "Return format:\nSubject: <subject line>\n\n<body>\n"
        + (f"\nThe previous attempt failed validation: {extra}. Fix only that." if extra else "")
    )


def _parse_llm_output(text: str) -> Tuple[Optional[str], Optional[str]]:
    match = re.match(r"\s*subject\s*:\s*(.+?)\s*\n+(.*)", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def _anthropic_complete(system: str, user: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _llm_generate(lead: Lead) -> Tuple[Optional[str], Optional[str]]:
    slots = _slots_for_lead(lead)
    system = _llm_system_prompt()

    ok, failures, subject, body = False, ["never ran"], None, None
    for attempt in range(2):
        extra = "" if attempt == 0 else "; ".join(failures)
        raw = _anthropic_complete(system, _llm_user_prompt(slots, lead.persona_type, extra))
        subject, body = _parse_llm_output(raw)
        if subject is None or body is None:
            failures = ["output missing Subject:/body structure"]
            continue
        ok, failures = validate_draft(subject, body)
        if ok:
            break

    if ok:
        return subject, body
    log.warning(
        f"LLM draft for lead {lead.source_url or lead.company} failed validation after retry "
        f"({failures}); falling back to template mode"
    )
    return None, None


def draft_for_lead(lead: Lead, force: bool = False) -> Lead:
    """Return a copy of `lead` with generated_draft populated.

    Leaves the lead unchanged when persona_type is Unclassified (logged
    warning, never guess a voice) or when a non-empty generated_draft already
    exists, unless force=True.
    """
    if lead.persona_type == "Unclassified":
        log.warning(
            f"Skipping drafting for lead {lead.source_url or lead.company}: persona Unclassified, refusing to guess a voice"
        )
        return lead
    if lead.generated_draft and not force:
        return lead

    new_lead = deepcopy(lead)
    subject, body = None, None
    if settings.anthropic_api_key:
        try:
            subject, body = _llm_generate(new_lead)
        except ImportError:
            log.warning("anthropic package not installed; falling back to template mode")
        except Exception as error:
            log.warning(f"LLM generation failed ({error}); falling back to template mode")

    if subject is None or body is None:
        subject, body = _template_generate(new_lead)

    ok, failures = validate_draft(subject, body)
    if not ok:  # Template drafts are constructed to pass; this is a guard, not a path
        raise RuntimeError(f"Internal error: template draft violated rules: {failures}")

    new_lead.generated_draft = f"Subject: {subject}\n\n{body}"
    new_lead.status = "Drafted"
    return new_lead


__all__ = [
    "draft_for_lead",
    "validate_draft",
    "count_body_words",
    "find_banned_words",
    "has_markup",
    "has_list_items",
    "has_throat_clearing",
    "has_padded_closer",
    "cta_violations",
    "BANNED_WORDS",
    "WORD_MAX",
    "WORD_TARGET",
]
