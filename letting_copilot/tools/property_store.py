"""
Property store — Pinecone vector search (production) with in-memory fallback (dev).

Production: set PINECONE_API_KEY and PINECONE_INDEX env vars.
Vectors are upserted on first use from data/properties.json.
Semantic search uses Pinecone's built-in inference (multilingual-e5-large).
Exact filters (budget, bedrooms) are applied as Pinecone metadata filters.

Fallback: plain in-memory filter when Pinecone is not configured.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
_PINECONE_INDEX   = os.getenv("PINECONE_INDEX", "lettingcopilot-properties")

# In-memory store — always loaded as fallback
_PROPERTIES: list[dict] = []
_pinecone_index = None   # lazy-init
_pinecone_seeded = False


# ── Load seed data ────────────────────────────────────────────────────────────

def _load() -> None:
    global _PROPERTIES
    if _PROPERTIES:
        return
    seed = Path(__file__).parents[2] / "data" / "properties.json"
    if seed.exists():
        _PROPERTIES = json.loads(seed.read_text())
        logger.info("[property_store] loaded %d properties from seed", len(_PROPERTIES))


# ── Pinecone setup ────────────────────────────────────────────────────────────

def _get_pinecone_index():
    """Lazy-init Pinecone index; returns None if not configured."""
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index
    if not _PINECONE_API_KEY:
        return None
    try:
        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=_PINECONE_API_KEY)

        # Create index if it doesn't exist (integrated inference — no embedding model needed locally)
        existing = [idx.name for idx in pc.list_indexes()]
        if _PINECONE_INDEX not in existing:
            logger.info("[pinecone] creating index '%s'", _PINECONE_INDEX)
            pc.create_index_for_model(
                name=_PINECONE_INDEX,
                cloud="aws",
                region="us-east-1",
                embed={
                    "model": "multilingual-e5-large",
                    "field_map": {"text": "text"},
                },
            )

        _pinecone_index = pc.Index(_PINECONE_INDEX)
        logger.info("[pinecone] connected to index '%s'", _PINECONE_INDEX)
        _seed_pinecone(_pinecone_index)
        return _pinecone_index

    except ImportError:
        logger.warning("[pinecone] pinecone package not installed — using in-memory fallback")
        return None
    except Exception as e:
        logger.error("[pinecone] init failed: %s — using in-memory fallback", e)
        return None


def _seed_pinecone(index) -> None:
    """Upsert all properties as vectors if not already seeded."""
    global _pinecone_seeded
    if _pinecone_seeded:
        return
    _load()
    if not _PROPERTIES:
        return
    try:
        records = []
        for p in _PROPERTIES:
            # Text field is what Pinecone embeds for semantic search
            text = (
                f"{p['bedrooms']}-bedroom {p.get('description', '')} "
                f"in {p['area']}. "
                f"£{p['rent_pcm']}/month. "
                f"Features: {', '.join(p.get('features', []))}. "
                f"Available from {p.get('available_from', 'now')}."
            )
            records.append({
                "_id":      p["id"],   # SDK requires _id (not id) for upsert_records
                "text":     text,
                # Metadata for exact filters
                "area":         p["area"].lower(),
                "bedrooms":     p["bedrooms"],
                "rent_pcm":     p["rent_pcm"],
                "available_from": p.get("available_from", ""),
                "address":      p["address"],
            })

        index.upsert_records(namespace="properties", records=records)
        _pinecone_seeded = True
        logger.info("[pinecone] upserted %d property vectors", len(records))
    except Exception as e:
        logger.error("[pinecone] seed failed: %s", e)


# ── Public tool functions ─────────────────────────────────────────────────────

def search_properties(
    max_rent: float,
    bedrooms: int | None = None,
    area: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """
    Search available properties.

    Uses Pinecone semantic search when configured — pass a natural language
    query like "quiet flat near tube for young professional" to get best matches.
    Falls back to in-memory exact filter when Pinecone is not configured.

    Args:
        max_rent: maximum monthly rent (required)
        bedrooms: exact bedroom count filter (optional)
        area:     area name filter (optional)
        query:    natural language description (optional, used for semantic search)
    """
    index = _get_pinecone_index()

    if index is not None:
        try:
            return _pinecone_search(index, max_rent, bedrooms, area, query)
        except Exception as e:
            logger.error("[pinecone] search failed: %s — falling back", e)

    # In-memory fallback
    return _memory_search(max_rent, bedrooms, area)


def get_property(property_id: str) -> dict[str, Any] | None:
    """Return a single property by ID."""
    _load()
    return next((p for p in _PROPERTIES if p["id"] == property_id), None)


# ── Pinecone search ───────────────────────────────────────────────────────────

def _pinecone_search(
    index,
    max_rent: float,
    bedrooms: int | None,
    area: str | None,
    query: str | None,
) -> list[dict[str, Any]]:
    """Query Pinecone with metadata filters + semantic ranking."""
    # Build metadata filter
    filters: dict[str, Any] = {"rent_pcm": {"$lte": max_rent}}
    if bedrooms:
        filters["bedrooms"] = {"$eq": bedrooms}
    if area:
        filters["area"] = {"$eq": area.lower()}

    # Use query for semantic search, or a generic text if not provided
    search_text = query or f"{bedrooms or 'any'} bedroom flat under £{max_rent}/month"
    if area:
        search_text += f" in {area}"

    results = index.search(
        namespace="properties",
        top_k=5,
        inputs={"text": search_text},
        filter=filters,
    )

    # SDK returns SearchRecordsResponse with results.result.hits (object, not dict)
    hits = results.result.hits if hasattr(results, "result") else []
    logger.info("[pinecone] search returned %d hits for '%s'", len(hits), search_text[:60])

    # Hydrate full property records from in-memory store (contains all fields)
    _load()
    found = []
    for hit in hits:
        hit_id = hit.id if hasattr(hit, "id") else hit.get("id") or hit.get("_id")
        prop = next((p for p in _PROPERTIES if p["id"] == hit_id), None)
        if prop:
            score = hit.score if hasattr(hit, "score") else hit.get("_score", 0)
            found.append({**prop, "_score": round(score, 3)})

    return found


# ── In-memory fallback ────────────────────────────────────────────────────────

def _memory_search(
    max_rent: float,
    bedrooms: int | None,
    area: str | None,
) -> list[dict[str, Any]]:
    _load()
    results = []
    for p in _PROPERTIES:
        if p["rent_pcm"] > max_rent:
            continue
        if bedrooms and p["bedrooms"] != bedrooms:
            continue
        if area and area.lower() not in p["area"].lower():
            continue
        results.append(p)
    logger.info("[property_store] in-memory search returned %d results", len(results))
    return results[:5]
