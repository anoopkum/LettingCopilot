"""Unit tests for all tools — no real GCP calls needed."""
import pytest
from letting_copilot.tools.property_store import search_properties, get_property
from letting_copilot.tools.calendar_tool import get_available_slots, book_slot
from letting_copilot.tools.crm_tool import save_applicant, get_applicant, save_offer
from letting_copilot.tools.notification_tool import send_reminder, send_followup


class TestPropertyStore:
    def test_search_by_budget(self):
        results = search_properties(max_rent=1700)
        assert all(p["rent_pcm"] <= 1700 for p in results)

    def test_search_by_bedrooms(self):
        results = search_properties(max_rent=5000, bedrooms=2)
        assert all(p["bedrooms"] == 2 for p in results)

    def test_search_by_area(self):
        results = search_properties(max_rent=5000, area="Balham")
        assert all("balham" in p["area"].lower() for p in results)

    def test_get_property_exists(self):
        p = get_property("prop_001")
        assert p is not None
        assert p["id"] == "prop_001"

    def test_get_property_missing(self):
        assert get_property("nonexistent") is None


class TestCalendar:
    def test_get_available_slots_structure(self):
        result = get_available_slots()
        assert "slots" in result
        assert "available" in result
        assert "message" in result

    def test_get_available_slots_has_slots(self):
        result = get_available_slots()
        assert result["available"] is True
        assert len(result["slots"]) > 0
        assert all(s["available"] for s in result["slots"])

    def test_book_slot_success(self):
        result = get_available_slots()
        slot_id = result["slots"][0]["id"]
        booking = book_slot(slot_id, "Tom Smith", "prop_001")
        assert booking["success"] is True
        assert booking["applicant"] == "Tom Smith"

    def test_book_slot_by_real_id(self):
        result = get_available_slots()
        assert result["available"], "no slots returned"
        slot_id = result["slots"][0]["id"]
        booking = book_slot(slot_id, "Jane Doe", "prop_001")
        assert booking["success"] is True
        assert booking["booking_id"].startswith("booking_")

    def test_book_slot_fuzzy_time_match(self):
        booking = book_slot("3pm", "Jane Doe", "prop_001")
        assert booking["success"] is True

    def test_book_slot_no_slots_left(self):
        from letting_copilot.tools.calendar_tool import _FAKE_SLOTS
        for s in _FAKE_SLOTS:
            s["available"] = False
        booking = book_slot("anytime", "Jane Doe", "prop_001")
        assert booking["success"] is False
        for s in _FAKE_SLOTS:
            s["available"] = True


class TestCRM:
    def test_save_and_retrieve_applicant(self):
        record = save_applicant(
            name="Alice Brown",
            email="alice@example.com",
            budget=2000,
            employment_status="full-time",
            move_date="2026-07-01",
        )
        assert record["id"] is not None
        retrieved = get_applicant(record["id"])
        assert retrieved["name"] == "Alice Brown"

    def test_save_offer(self):
        applicant = save_applicant(name="Bob Jones", budget=2100)
        offer = save_offer(applicant["id"], "prop_001", 2050.0, "No pets")
        assert offer["offer_amount"] == 2050.0
        assert offer["status"] == "pending"


class TestNotifications:
    def test_send_reminder(self):
        result = send_reminder("Tom", "Thursday 2pm", "12 Balham High Road")
        assert result["sent"] is True

    def test_send_followup(self):
        result = send_followup("Tom", "12 Balham High Road")
        assert result["sent"] is True
