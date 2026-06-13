"""
HomeData UK property data integration.

Provides address lookup and UPRN resolution for UK properties.
Base URL: https://neo.homedata.co.uk/api
Auth: Authorization: Api-Key <key>

Set HOMEDATA_API_KEY to enable. All functions degrade gracefully without it.

Available with current API key:
  - address_find(query)  → address suggestions with UPRNs
  - address_retrieve(uprn) → full address record for a UPRN

The UPRN returned can be stored against a property so that future endpoints
(EPC, floor area, sold history) can be called as the plan is upgraded.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://neo.homedata.co.uk/api"
_TIMEOUT = 8  # seconds


def _api_key() -> str:
    return os.getenv("HOMEDATA_API_KEY", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Api-Key {_api_key()}",
        "Accept": "application/json",
    }


def address_find(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Search for UK addresses matching a free-text query.

    Returns a list of address suggestions each with a UPRN — the unique
    identifier for every UK property. Returns [] if API key not set or
    request fails.

    Args:
        query: free-text address search, e.g. "12 Balham High Road" or "SW12 9AA"
        limit: max results to return (default 5)
    """
    if not _api_key():
        return []
    try:
        resp = httpx.get(
            f"{_BASE_URL}/address/find",
            params={"q": query},
            headers=_headers(),
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning("[homedata] address/find '%s' → %d", query, resp.status_code)
            return []

        suggestions = resp.json().get("suggestions", [])
        logger.info("[homedata] address/find '%s' → %d results", query, len(suggestions))
        return suggestions[:limit]

    except httpx.RequestError as e:
        logger.error("[homedata] address/find failed: %s", e)
        return []


def resolve_address(address_line: str, postcode: str | None = None) -> dict[str, Any] | None:
    """
    Resolve a property address to its UPRN and normalised address fields.

    Searches HomeData for the address and returns the best match as a dict with:
      uprn, address, address_line_1, address_line_2, town, postcode

    Returns None if no match found or API unavailable.
    """
    query = f"{address_line} {postcode or ''}".strip()
    results = address_find(query, limit=1)
    if not results:
        return None
    return results[0]


def enrich_property(prop: dict[str, Any]) -> dict[str, Any]:
    """
    Add HomeData UPRN to an existing property dict if not already present.

    Looks up the property address in HomeData to resolve the UPRN.
    Returns prop unchanged if API key not set, address not found, or lookup fails.
    The UPRN is stored as prop['uprn'] for use with future API endpoints.
    """
    if not _api_key():
        return prop
    if prop.get("uprn"):
        return prop

    address = prop.get("address", "")
    if not address:
        return prop

    match = resolve_address(address)
    if match and match.get("uprn"):
        prop["uprn"] = match["uprn"]
        # Fill in any missing address fields from HomeData
        if not prop.get("postcode") and match.get("postcode"):
            prop["postcode"] = match["postcode"]
        logger.debug("[homedata] resolved UPRN %s for '%s'", match["uprn"], address)

    return prop


def lookup_postcode_area(postcode: str) -> list[dict[str, Any]]:
    """
    Find all addresses in a postcode area using HomeData address search.

    Returns a list of address suggestions for the postcode. Useful for
    discovering available properties in a neighbourhood. Returns [] if
    API unavailable.
    """
    return address_find(postcode, limit=10)
