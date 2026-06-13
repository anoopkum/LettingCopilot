"""
Input guardrails — run BEFORE the LLM sees the message.

Checks:
  1. Empty / whitespace-only input
  2. Gibberish (too many non-alpha chars, no recognisable words)
  3. Prompt injection attempts
  4. Off-topic / completely unrelated domains
  5. Agent-specific field validation (budget, date format, etc.)

Returns a GuardrailResult. If blocked=True, the caller short-circuits
the LLM call and returns the suggestion directly to the user.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Prompt injection patterns ─────────────────────────────────────────────────
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"forget\s+(everything|all|your\s+instructions?)",
    r"you\s+are\s+now\s+(a|an)\s+\w+",
    r"act\s+as\s+(if\s+you\s+(are|were)|a|an)\s+",
    r"pretend\s+(you\s+are|to\s+be)",
    r"jailbreak",
    r"dan\s+mode",
    r"system\s+prompt",
    r"reveal\s+your\s+(prompt|instructions?|training)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# ── Off-topic domains (clearly nothing to do with lettings) ───────────────────
_OFF_TOPIC_PATTERNS = [
    r"\b(stock|share|crypto|bitcoin|forex|trading|invest)\b",
    r"\b(recipe|cook|bake|ingredient|cuisine)\b",
    r"\b(movie|film|actor|actress|celebrity|sport|football|cricket)\b",
    r"\b(homework|essay|thesis|exam|assignment)\b",
    r"\b(hack|exploit|malware|virus|ddos|ransomware)\b",
    r"\b(weather|forecast|temperature|climate)\b",
]
_OFF_TOPIC_RE = re.compile("|".join(_OFF_TOPIC_PATTERNS), re.IGNORECASE)

# ── Agent-context validators ──────────────────────────────────────────────────
_BUDGET_RE      = re.compile(r"\b(\d{3,5})\s*(pcm|pm|/month|per\s+month|£|gbp|pounds?)?\b", re.IGNORECASE)
_DATE_HINTS_RE  = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"next\s+month|asap|immediately|soon|this\s+month|in\s+\d+\s+(weeks?|months?)|\d{1,2}[/-]\d{1,2})\b",
    re.IGNORECASE,
)


@dataclass
class GuardrailResult:
    blocked: bool
    reason: str        # internal log label
    suggestion: str    # natural-language reply sent to user


def check_input(text: str, agent_name: str = "") -> GuardrailResult:
    """
    Run all input checks. Returns a GuardrailResult.
    blocked=False means the input is fine — let the LLM handle it.
    """
    stripped = text.strip()

    # 1. Empty input
    if not stripped:
        return GuardrailResult(
            blocked=True,
            reason="empty_input",
            suggestion="It looks like your message was empty. Could you let me know what you're looking for? "
                       "For example: 'I'm looking for a 2-bed flat in London around £1,400/month.'",
        )

    # 2. Too short to be meaningful — single char or pure punctuation only.
    # Short natural replies (no, ok, yes, thanks, hi) must pass through to the LLM.
    if re.fullmatch(r"[^a-zA-Z0-9]+", stripped) or (len(stripped) == 1 and not stripped.isalpha()):
        return GuardrailResult(
            blocked=True,
            reason="too_short_or_gibberish",
            suggestion=f"I didn't quite catch that — '{stripped}' doesn't look like a full message. "
                       "Could you give me a bit more detail? I'm here to help you find and book a rental property.",
        )

    # 3. Gibberish — very high ratio of non-alphanumeric characters
    alpha_ratio = sum(c.isalpha() for c in stripped) / len(stripped)
    if len(stripped) > 10 and alpha_ratio < 0.3:
        return GuardrailResult(
            blocked=True,
            reason="gibberish_high_symbol_ratio",
            suggestion="That message doesn't look like readable text. Could you rephrase? "
                       "For example, tell me your budget, preferred area, or when you're looking to move.",
        )

    # 4. Prompt injection
    if _INJECTION_RE.search(stripped):
        logger.warning("[guardrail] prompt injection attempt: %r", stripped[:100])
        return GuardrailResult(
            blocked=True,
            reason="prompt_injection",
            suggestion="I'm sorry, I can't process that request. I'm a lettings agent — "
                       "I'm here to help you find and book rental properties. How can I help you today?",
        )

    # 5. Completely off-topic
    if _OFF_TOPIC_RE.search(stripped):
        topic = _OFF_TOPIC_RE.search(stripped).group()
        return GuardrailResult(
            blocked=True,
            reason="off_topic",
            suggestion=f"I'm sorry, I'm not able to help with '{topic}' — I'm a specialist lettings agent. "
                       "I can help you search for rental properties, qualify your application, or book a viewing. "
                       "What are you looking for in a rental home?",
        )

    # 6. Budget/date checks — apply to any agent context, not just qualification
    result = _check_qualification_context(stripped)
    if result:
        return result

    return GuardrailResult(blocked=False, reason="ok", suggestion="")


def _check_qualification_context(text: str) -> GuardrailResult | None:
    """
    Check budget and date plausibility. Only fires when the message is
    clearly about stating a budget or move date — not general search queries.
    """
    # "my budget is loads" / "I can afford that" — budget keyword but no number
    # Only block if it reads like a direct answer (short, no "looking for" / "around" context)
    budget_keywords = re.search(r"\b(budget|afford|pay|pcm|per month|monthly)\b", text, re.IGNORECASE)
    search_context  = re.search(r"\b(looking|searching|want|need|find|around|about)\b", text, re.IGNORECASE)
    if budget_keywords and not search_context and not re.search(r"\d", text):
        return GuardrailResult(
            blocked=True,
            reason="budget_no_number",
            suggestion="I need a number for your monthly budget — for example, '£1,200 per month' or just '1200'. "
                       "What's your approximate monthly budget?",
        )

    # Budget stated as under £500 — only trigger when text is SHORT (< 12 words)
    # and not a search query, to avoid false positives on "around £1,400"
    words = text.split()
    budget_match = _BUDGET_RE.search(text)
    if budget_match and len(words) <= 10 and not search_context:
        amount = int(budget_match.group(1))
        if amount < 500:
            return GuardrailResult(
                blocked=True,
                reason="budget_too_low",
                suggestion=f"A budget of £{amount}/month is below the minimum for any of our current listings. "
                           "Our properties start from £1,400/month. "
                           "Could you confirm your budget, or would you like to hear about upcoming affordable listings?",
            )

    # Looks like a move date answer but is unrecognisable.
    # Do NOT fire if the message is a search/area query (contains "looking", "area", "in", city names etc.)
    date_keywords = re.search(r"\b(move|moving|start|from|available|date)\b", text, re.IGNORECASE)
    location_context = re.search(r"\b(area|city|town|street|road|place|flat|house|looking|searching|want|need|find|near|in)\b", text, re.IGNORECASE)
    if date_keywords and not location_context and not _DATE_HINTS_RE.search(text) and not re.search(r"\d", text):
        return GuardrailResult(
            blocked=True,
            reason="move_date_unrecognisable",
            suggestion="I didn't catch a clear move date from that. Could you say something like "
                       "'next month', 'August', or give a rough date? That helps me find properties "
                       "that are available when you need them.",
        )

    return None
