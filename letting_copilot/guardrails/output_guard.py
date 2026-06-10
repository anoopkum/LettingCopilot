"""
Output guardrails — run AFTER the LLM produces a response.

Checks:
  1. Response is empty or too short to be useful
  2. LLM leaked a refusal it shouldn't show the user (internal error bleed)
  3. Response contains a raw API key or secret pattern
  4. Response looks like raw JSON / stack trace leaked to the user
"""
from __future__ import annotations
import re
import logging

logger = logging.getLogger(__name__)

# Patterns that indicate an internal error bled into the LLM response
_INTERNAL_BLEED_RE = re.compile(
    r"(traceback \(most recent call|file \".*\.py\", line \d|"
    r"exception:|error:.*at 0x|json\.decoder|keyerror|attributeerror|typeerror)",
    re.IGNORECASE,
)

# API key / secret patterns
_SECRET_RE = re.compile(
    r"(AIza[0-9A-Za-z\-_]{35}|AQ\.[A-Za-z0-9\-_]{20,}|"
    r"eyJ[A-Za-z0-9\-_]{20,}|sk-[a-zA-Z0-9]{32,})",
)

# Raw JSON blob starting with { or [ — likely an unformatted tool result
_RAW_JSON_RE = re.compile(r"^\s*[\[{].*[\]}]\s*$", re.DOTALL)


def check_output(text: str, agent_name: str = "") -> str:
    """
    Inspect the LLM output and return either the original text (clean)
    or a sanitised fallback message.
    """
    if not text or not text.strip():
        logger.warning("[guardrail:output] empty response from agent=%s", agent_name)
        return (
            "I'm working on it — could you send that again? "
            "Sometimes I need a moment to catch up between steps."
        )

    if len(text.strip()) < 10:
        return (
            "Sorry, something went wrong with my response. "
            "Could you try again? I'm happy to help you find the right property."
        )

    if _SECRET_RE.search(text):
        logger.error("[guardrail:output] secret/key pattern detected in response, redacting")
        return (
            "I'm sorry, I encountered an issue putting together my response. "
            "Please try again or contact support."
        )

    if _INTERNAL_BLEED_RE.search(text):
        logger.error("[guardrail:output] internal error bleed detected in response agent=%s", agent_name)
        return (
            "I'm sorry, something went wrong on my end. "
            "Please try your message again — I'm here to help you with your property search."
        )

    if _RAW_JSON_RE.match(text) and len(text) > 200:
        logger.warning("[guardrail:output] raw JSON in response agent=%s", agent_name)
        return (
            "I'm sorry, I had trouble formatting my response. "
            "Could you rephrase your question? For example: 'Show me available 2-bed flats under £1,500.'"
        )

    return text
