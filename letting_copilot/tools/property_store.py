"""In-memory property store for POC (swap for Firestore in prod)."""
import json
from pathlib import Path
from typing import Any

_PROPERTIES: list[dict] = []


def _load() -> None:
    global _PROPERTIES
    seed = Path(__file__).parents[2] / "data" / "properties.json"
    if seed.exists() and not _PROPERTIES:
        _PROPERTIES = json.loads(seed.read_text())


def search_properties(
    max_rent: float,
    bedrooms: int | None = None,
    area: str | None = None,
) -> list[dict[str, Any]]:
    """Search available properties by budget, bedrooms, and area."""
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
    return results[:5]


def get_property(property_id: str) -> dict[str, Any] | None:
    """Return a single property by ID."""
    _load()
    return next((p for p in _PROPERTIES if p["id"] == property_id), None)
