"""CRM tool — in-memory store for POC."""
from typing import Any
import uuid

_APPLICANTS: dict[str, dict] = {}
_OFFERS: list[dict] = []


def save_applicant(
    name: str,
    phone: str | None = None,
    email: str | None = None,
    budget: float | None = None,
    employment_status: str | None = None,
    move_date: str | None = None,
    interested_property: str | None = None,
) -> dict[str, Any]:
    """Create or update an applicant record in the CRM."""
    applicant_id = str(uuid.uuid4())[:8]
    record = {
        "id": applicant_id,
        "name": name,
        "phone": phone,
        "email": email,
        "budget_pcm": budget,
        "employment_status": employment_status,
        "move_date": move_date,
        "interested_property": interested_property,
        "qualified": True,
    }
    _APPLICANTS[applicant_id] = record
    return record


def get_applicant(applicant_id: str) -> dict[str, Any] | None:
    """Retrieve an applicant record."""
    return _APPLICANTS.get(applicant_id)


def save_offer(applicant_id: str, property_id: str, offer_amount: float, notes: str = "") -> dict[str, Any]:
    """Record an offer from an applicant."""
    offer = {
        "offer_id": str(uuid.uuid4())[:8],
        "applicant_id": applicant_id,
        "property_id": property_id,
        "offer_amount": offer_amount,
        "notes": notes,
        "status": "pending",
    }
    _OFFERS.append(offer)
    return offer
