"""CRM tool — Pinecone-backed store with in-memory fallback for POC."""
from typing import Any
import logging
import os
import uuid

logger = logging.getLogger(__name__)

_NS = "__default__"

# In-memory fallback
_APPLICANTS: dict[str, dict] = {}
_OFFERS: list[dict] = []
_pinecone_index = None


def _get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index
    # Read env vars lazily so load_dotenv() in config.py has already run
    api_key = os.getenv("PINECONE_API_KEY", "")
    index_name = os.getenv("PINECONE_APPLICANTS_INDEX", "applicants")
    if not api_key:
        return None
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        _pinecone_index = pc.Index(index_name)
        logger.info("[crm] connected to Pinecone index '%s'", index_name)
        return _pinecone_index
    except Exception as e:
        logger.warning("[crm] Pinecone unavailable: %s — using in-memory fallback", e)
        return None


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
        "phone": phone or "",
        "email": email or "",
        "budget_pcm": budget,
        "employment_status": employment_status or "",
        "move_date": move_date or "",
        "interested_property": interested_property or "",
        "qualified": True,
    }

    # Always keep in-memory copy
    _APPLICANTS[applicant_id] = record

    # Persist to Pinecone — must succeed before agent confirms to user
    index = _get_pinecone_index()
    if index is not None:
        try:
            text = (
                f"Applicant {name}. "
                f"Budget £{budget}/month. "
                f"Employment: {employment_status}. "
                f"Move date: {move_date}. "
                f"Email: {email}."
            )
            index.upsert_records(
                namespace=_NS,
                records=[{
                    "_id":                applicant_id,
                    "text":               text,
                    "name":               name,
                    "email":              email or "",
                    "phone":              phone or "",
                    "budget_pcm":         budget or 0,
                    "employment_status":  employment_status or "",
                    "move_date":          move_date or "",
                    "interested_property": interested_property or "",
                    "qualified":          True,
                }],
            )
            logger.info("[crm] saved applicant %s (%s) to Pinecone", applicant_id, name)
            record["storage"] = "pinecone"
        except Exception as e:
            logger.error("[crm] Pinecone upsert failed: %s — record kept in-memory only", e)
            record["storage"] = "memory_only"
    else:
        logger.warning("[crm] PINECONE_API_KEY not set — record in-memory only for applicant %s", applicant_id)
        record["storage"] = "memory_only"

    return record


def get_applicant(applicant_id: str) -> dict[str, Any] | None:
    """Retrieve an applicant record — checks in-memory first, then Pinecone."""
    if applicant_id in _APPLICANTS:
        return _APPLICANTS[applicant_id]

    index = _get_pinecone_index()
    if index is None:
        return None

    try:
        result = index.fetch(ids=[applicant_id], namespace=_NS)
        vectors = result.get("vectors") or result.get("records") or {}
        if applicant_id in vectors:
            v = vectors[applicant_id]
            meta = v.get("metadata") or v.get("fields") or {}
            record = {"id": applicant_id, **meta}
            _APPLICANTS[applicant_id] = record
            return record
    except Exception as e:
        logger.error("[crm] Pinecone fetch failed: %s", e)

    return None


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
