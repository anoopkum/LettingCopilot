"""Booking agent — finds available slots and confirms viewing appointments."""
from google.adk.agents import Agent
from letting_copilot.config import config
from letting_copilot.tools.calendar_tool import get_available_slots, book_slot
from letting_copilot.tools.crm_tool import save_applicant

booking_agent = Agent(
    name="booking_agent",
    model=config.model,
    description="Books viewing appointments by checking team availability and confirming with the applicant.",
    instruction="""
Your job is to book a viewing for a qualified applicant.

Steps:
1. Call get_available_slots to find the next 3–4 free slots.
2. Present them clearly to the applicant (e.g., "Thursday 2pm or Friday 11am?").
3. Once they choose, call book_slot with the slot_id, applicant name, and property_id.
4. Confirm the booking to the applicant with date, time, and property address.
5. Let them know they'll receive a reminder before the viewing.

Keep it efficient — don't offer more than 4 options at once.
Return the booking confirmation details to the orchestrator.
""",
    tools=[get_available_slots, book_slot, save_applicant],
)
