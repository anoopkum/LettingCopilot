"""Notification tool — prints/logs for POC, replace with Twilio/SendGrid in prod."""
import logging

logger = logging.getLogger(__name__)


def send_reminder(applicant_name: str, viewing_datetime: str, property_address: str) -> dict:
    """Send a viewing reminder to the applicant."""
    msg = f"Reminder: {applicant_name}, your viewing at {property_address} is on {viewing_datetime}."
    logger.info("[NOTIFICATION] %s", msg)
    return {"sent": True, "message": msg, "channel": "log"}


def send_followup(applicant_name: str, property_address: str) -> dict:
    """Send a post-viewing follow-up message."""
    msg = f"Hi {applicant_name}, thanks for viewing {property_address}. How did you find it? Any questions?"
    logger.info("[FOLLOWUP] %s", msg)
    return {"sent": True, "message": msg, "channel": "log"}
