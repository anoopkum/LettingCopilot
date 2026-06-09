"""Calendar tool — in-memory slots for POC."""
from datetime import datetime, timedelta
from typing import Any

# Seed with some available slots starting tomorrow
_BASE = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
_SLOTS: list[dict] = [
    {"id": f"slot_{i}", "datetime": (_BASE + timedelta(hours=i * 3)).isoformat(), "available": True}
    for i in range(10)
]
_BOOKINGS: dict[str, dict] = {}


def get_available_slots(date_hint: str | None = None) -> list[dict[str, Any]]:
    """Return the next available viewing slots."""
    return [s for s in _SLOTS if s["available"]][:4]


def book_slot(slot_id: str, applicant_name: str, property_id: str) -> dict[str, Any]:
    """Book a viewing slot for an applicant."""
    slot = next((s for s in _SLOTS if s["id"] == slot_id), None)
    if not slot:
        return {"success": False, "error": "Slot not found"}
    if not slot["available"]:
        return {"success": False, "error": "Slot already taken"}
    slot["available"] = False
    booking = {
        "booking_id": f"booking_{slot_id}",
        "slot_id": slot_id,
        "datetime": slot["datetime"],
        "applicant": applicant_name,
        "property_id": property_id,
    }
    _BOOKINGS[booking["booking_id"]] = booking
    return {"success": True, **booking}
