"""
Calendar tool — Google Calendar API integration.

Production: set GOOGLE_CALENDAR_ID and GOOGLE_CALENDAR_SA_JSON env vars.
Fallback:   if either var is missing, uses in-memory fake slots (dev/test).

Service account needs "Make changes to events" permission on the calendar.
"""
from __future__ import annotations
import os
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_CALENDAR_ID   = os.getenv("GOOGLE_CALENDAR_ID", "")          # e.g. you@gmail.com
_SA_JSON       = os.getenv("GOOGLE_CALENDAR_SA_JSON", "")     # full JSON string of SA key
_SLOT_DURATION = int(os.getenv("CALENDAR_SLOT_MINUTES", "60"))
_SLOT_HOURS    = [10, 13, 15, 17]                              # candidate viewing hours
_DAYS_AHEAD    = int(os.getenv("CALENDAR_DAYS_AHEAD", "7"))   # how far ahead to look

_gcal_service = None  # lazy-init
_gcal_service_failed = False  # set True after a 403 so we don't retry until restart


def reset_service_cache():
    """Force re-initialisation of the GCal service (e.g. after enabling the API)."""
    global _gcal_service, _gcal_service_failed
    _gcal_service = None
    _gcal_service_failed = False


def _get_service():
    """Return authenticated Google Calendar service, or None if not configured."""
    global _gcal_service, _gcal_service_failed
    if _gcal_service is not None:
        return _gcal_service
    if _gcal_service_failed:
        return None
    if not _CALENDAR_ID or not _SA_JSON:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(_SA_JSON)
        # "{}" placeholder stored in Secret Manager when calendar not configured
        if not info.get("type") or not info.get("private_key"):
            logger.info("[calendar] SA JSON is placeholder — using mock fallback")
            return None
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        _gcal_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        logger.info("[calendar] Google Calendar API connected, calendar_id=%s", _CALENDAR_ID)
        return _gcal_service
    except Exception as e:
        logger.error("[calendar] failed to initialise Google Calendar API: %s", e)
        _gcal_service_failed = True  # stop retrying until next restart
        return None


# ── In-memory fallback (dev / when GCal not configured) ──────────────────────
# Slots use human-readable datetime strings as IDs so the LLM can pass them back
# after presenting them to the user (e.g. "Thursday 11 June at 9am").
def _build_fake_slots() -> list[dict]:
    base = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    slots = []
    for day_offset in range(5):
        day = base + timedelta(days=day_offset)
        for hour in _SLOT_HOURS:
            dt = day.replace(hour=hour)
            label = dt.strftime("%A %-d %B at %-I%p").replace("AM", "am").replace("PM", "pm")
            slots.append({"id": label, "datetime": label, "available": True})
    return slots

_FAKE_SLOTS: list[dict] = _build_fake_slots()
_FAKE_BOOKINGS: dict[str, dict] = {}


# ── Public tool functions (called by ADK agents) ──────────────────────────────

def get_available_slots(date_hint: str | None = None) -> list[dict[str, Any]]:
    """
    Return the next 4 available viewing slots.
    Uses Google Calendar freebusy query in production; fake slots in dev.
    """
    svc = _get_service()
    if svc is None:
        logger.info("[calendar] using fake slots (GCal not configured)")
        return [s for s in _FAKE_SLOTS if s["available"]][:4]

    try:
        return _gcal_free_slots(svc, date_hint)
    except Exception as e:
        logger.error("[calendar] get_available_slots error: %s — falling back", e)
        return _fake_free_slots()


def book_slot(slot_id: str, applicant_name: str, property_id: str) -> dict[str, Any]:
    """
    Book a viewing slot.
    Creates a Google Calendar event in production; updates fake dict in dev.
    slot_id is either a fake "slot_N" id or an ISO datetime string from GCal.
    """
    svc = _get_service()
    if svc is None:
        return _fake_book(slot_id, applicant_name, property_id)

    try:
        return _gcal_book(svc, slot_id, applicant_name, property_id)
    except Exception as e:
        logger.error("[calendar] book_slot error: %s — falling back", e)
        return _fake_book(slot_id, applicant_name, property_id)


# ── Google Calendar implementation ───────────────────────────────────────────

def _gcal_free_slots(svc, date_hint: str | None) -> list[dict[str, Any]]:
    """
    Query freebusy for the next _DAYS_AHEAD days and return free slots
    at the candidate hours (_SLOT_HOURS) that don't overlap any existing event.
    """
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=_DAYS_AHEAD)

    body = {
        "timeMin": now.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": _CALENDAR_ID}],
    }
    result = svc.freebusy().query(body=body).execute()
    busy_periods = result.get("calendars", {}).get(_CALENDAR_ID, {}).get("busy", [])

    busy_ranges = [
        (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
        for b in busy_periods
    ]

    slots = []
    day = now.date()
    while len(slots) < 4 and (datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) - now).days < _DAYS_AHEAD:
        for hour in _SLOT_HOURS:
            slot_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=hour)
            slot_end   = slot_start + timedelta(minutes=_SLOT_DURATION)

            if slot_start < now:
                continue

            # Check no overlap with busy periods
            overlaps = any(
                not (slot_end <= busy_start or slot_start >= busy_end)
                for busy_start, busy_end in busy_ranges
            )
            if not overlaps:
                slots.append({
                    "id": slot_start.isoformat(),   # ISO datetime as slot ID
                    "datetime": slot_start.strftime("%A %-d %B at %-I%p").replace("AM","am").replace("PM","pm"),
                    "datetime_iso": slot_start.isoformat(),
                    "available": True,
                })
            if len(slots) >= 4:
                break
        day += timedelta(days=1)

    logger.info("[calendar] found %d free slots via GCal freebusy", len(slots))
    return slots


def _gcal_book(svc, slot_id: str, applicant_name: str, property_id: str) -> dict[str, Any]:
    """
    Create a Google Calendar event for the viewing.
    slot_id is the ISO datetime string returned by get_available_slots.
    """
    try:
        start = datetime.fromisoformat(slot_id)
    except ValueError:
        return {"success": False, "error": f"Invalid slot_id format: {slot_id}"}

    end = start + timedelta(minutes=_SLOT_DURATION)
    booking_id = f"booking_{uuid.uuid4().hex[:8]}"

    event = {
        "summary": f"Viewing — {applicant_name} — {property_id}",
        "description": (
            f"Property viewing\n"
            f"Applicant: {applicant_name}\n"
            f"Property: {property_id}\n"
            f"Booking ID: {booking_id}"
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": "Europe/London"},
        "end":   {"dateTime": end.isoformat(),   "timeZone": "Europe/London"},
        "attendees": [],
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email",  "minutes": 1440},   # 24h before
                {"method": "popup",  "minutes": 60},     # 1h before
            ],
        },
    }

    created = svc.events().insert(calendarId=_CALENDAR_ID, body=event).execute()
    logger.info("[calendar] event created id=%s link=%s", created["id"], created.get("htmlLink"))

    return {
        "success": True,
        "booking_id": booking_id,
        "event_id": created["id"],
        "calendar_link": created.get("htmlLink", ""),
        "datetime": start.strftime("%A %-d %B at %-I%p").replace("AM","am").replace("PM","pm"),
        "datetime_iso": start.isoformat(),
        "applicant": applicant_name,
        "property_id": property_id,
    }


# ── Fake fallback helpers ─────────────────────────────────────────────────────

def _fake_free_slots() -> list[dict[str, Any]]:
    return [s for s in _FAKE_SLOTS if s["available"]][:4]


def _fake_book(slot_id: str, applicant_name: str, property_id: str) -> dict[str, Any]:
    # Match by exact id first, then by case-insensitive substring so the LLM can
    # pass back a time string like "3pm" or "3:00 PM" and still match a slot.
    slot_id_norm = slot_id.lower().replace(":", "").replace(" ", "")
    slot = next(
        (s for s in _FAKE_SLOTS if s["id"] == slot_id or
         slot_id_norm in s["id"].lower().replace(":", "").replace(" ", "")),
        None,
    )
    if not slot:
        # Last resort — take the first available slot and note the mismatch
        slot = next((s for s in _FAKE_SLOTS if s["available"]), None)
        if not slot:
            return {"success": False, "error": "No available slots"}
        logger.warning("[calendar] slot_id '%s' not matched — using first available: %s", slot_id, slot["id"])
    if not slot["available"]:
        return {"success": False, "error": "Slot already taken"}
    slot["available"] = False
    booking = {
        "success": True,
        "booking_id": f"booking_{slot_id}",
        "event_id": None,
        "calendar_link": None,
        "datetime": slot["datetime"],
        "applicant": applicant_name,
        "property_id": property_id,
    }
    _FAKE_BOOKINGS[booking["booking_id"]] = booking
    return booking
