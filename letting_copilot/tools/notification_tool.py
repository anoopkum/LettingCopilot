"""
Notification tool — sends emails via SendGrid.

Production: set SENDGRID_API_KEY and SENDGRID_FROM_EMAIL env vars.
Fallback:   logs only when those vars are not set (dev/test).
"""
from __future__ import annotations
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_FROM_NAME = "LettingCopilot"

# Read at call time (not module-load) so Secret Manager env vars are always current
def _api_key() -> str:
    key = os.getenv("SENDGRID_API_KEY", "")
    return "" if key in ("", "not-configured") else key

def _from_email() -> str:
    return os.getenv("SENDGRID_FROM_EMAIL", "noreply@lettingcopilot.ai")


def _send_email(to_email: str, subject: str, body_text: str, body_html: str) -> tuple[bool, str]:
    """Send via SendGrid. Returns (success, error_detail)."""
    key = _api_key()
    if not key:
        logger.info("[notification] SendGrid not configured — logging only TO=%s", to_email)
        return False, "SendGrid not configured"

    try:
        import httpx
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": _from_email(), "name": _FROM_NAME},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body_text},
                {"type": "text/html",  "value": body_html},
            ],
        }
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 202):
            logger.info("[notification] email sent to=%s subject=%s", to_email, subject)
            return True, ""
        else:
            detail = resp.text[:300]
            logger.error("[notification] SendGrid %s: %s", resp.status_code, detail)
            return False, f"SendGrid {resp.status_code}: {detail}"
    except Exception as e:
        logger.error("[notification] email send failed: %s", e)
        return False, str(e)


def send_reminder(
    applicant_name: str,
    viewing_datetime: str,
    property_address: str,
    applicant_email: str = "",
) -> dict[str, Any]:
    """Send a viewing confirmation + reminder email to the applicant."""
    subject = f"Your viewing at {property_address} — {viewing_datetime}"

    body_text = (
        f"Hi {applicant_name},\n\n"
        f"This is a confirmation that your property viewing has been booked:\n\n"
        f"  Property: {property_address}\n"
        f"  Date & Time: {viewing_datetime}\n\n"
        f"Please arrive a few minutes early. If you need to reschedule, just reply to this email.\n\n"
        f"Best regards,\n"
        f"LettingCopilot Team"
    )

    body_html = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <h2 style="color:#1a3c5e">Viewing Confirmed ✓</h2>
  <p>Hi <strong>{applicant_name}</strong>,</p>
  <p>Your property viewing has been booked:</p>
  <table style="border-collapse:collapse;width:100%;margin:16px 0">
    <tr>
      <td style="padding:8px;background:#f0f4f8;font-weight:bold;width:40%">Property</td>
      <td style="padding:8px;border-bottom:1px solid #e0e6ed">{property_address}</td>
    </tr>
    <tr>
      <td style="padding:8px;background:#f0f4f8;font-weight:bold">Date &amp; Time</td>
      <td style="padding:8px;border-bottom:1px solid #e0e6ed">{viewing_datetime}</td>
    </tr>
  </table>
  <p>Please arrive a few minutes early. If you need to reschedule, just reply to this email.</p>
  <p style="color:#888;font-size:12px;margin-top:32px">LettingCopilot — AI Lettings Agent</p>
</div>
"""

    msg = f"Viewing confirmation: {applicant_name} at {property_address} on {viewing_datetime}"
    logger.info("[notification] %s", msg)

    sent = False
    channel = "log"
    error = ""
    if applicant_email:
        sent, error = _send_email(applicant_email, subject, body_text, body_html)
        channel = "sendgrid" if sent else "log"
    else:
        logger.warning("[notification] no email address for applicant %s — log only", applicant_name)
        error = "no email address provided"

    result: dict[str, Any] = {
        "sent": sent,
        "channel": channel,
        "message": msg,
        "to": applicant_email or "(no email)",
    }
    if error:
        result["error"] = error
    return result


def send_followup(
    applicant_name: str,
    property_address: str,
    applicant_email: str = "",
) -> dict[str, Any]:
    """Send a post-viewing follow-up email."""
    subject = f"How was your viewing at {property_address}?"

    body_text = (
        f"Hi {applicant_name},\n\n"
        f"Thanks for viewing {property_address} — we hope it went well!\n\n"
        f"We'd love to know what you thought. Did the property feel like a good fit?\n\n"
        f"If you'd like to make an offer or have any questions, just reply to this email "
        f"or get back to us on the LettingCopilot chat.\n\n"
        f"Best regards,\n"
        f"LettingCopilot Team"
    )

    body_html = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <h2 style="color:#1a3c5e">How was your viewing?</h2>
  <p>Hi <strong>{applicant_name}</strong>,</p>
  <p>Thanks for viewing <strong>{property_address}</strong> — we hope it went well!</p>
  <p>We'd love to know what you thought. Did the property feel like a good fit?</p>
  <p>If you'd like to make an offer or have any questions, just reply to this email
     or get back to us on the LettingCopilot chat.</p>
  <p style="color:#888;font-size:12px;margin-top:32px">LettingCopilot — AI Lettings Agent</p>
</div>
"""

    msg = f"Follow-up sent to {applicant_name} for {property_address}"
    logger.info("[followup] %s", msg)

    sent = False
    channel = "log"
    error = ""
    if applicant_email:
        sent, error = _send_email(applicant_email, subject, body_text, body_html)
        channel = "sendgrid" if sent else "log"
    else:
        error = "no email address provided"

    result: dict[str, Any] = {
        "sent": sent,
        "channel": channel,
        "message": msg,
        "to": applicant_email or "(no email)",
    }
    if error:
        result["error"] = error
    return result
