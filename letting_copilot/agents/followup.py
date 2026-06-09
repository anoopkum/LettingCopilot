"""Follow-up agent — sends reminders and collects post-viewing feedback."""
from google.adk.agents import Agent
from letting_copilot.config import config
from letting_copilot.tools.notification_tool import send_reminder, send_followup
from letting_copilot.tools.crm_tool import save_offer

followup_agent = Agent(
    name="followup_agent",
    model=config.model,
    description="Sends viewing reminders and collects post-viewing feedback and offers.",
    instruction="""
You handle post-booking communications.

Pre-viewing:
- Call send_reminder with the applicant name, viewing datetime, and property address.
- Confirm to the applicant that a reminder has been sent.

Post-viewing follow-up:
- Call send_followup to check in with the applicant.
- Ask: "How did you find the property? Any questions or would you like to make an offer?"
- If they want to make an offer, ask for the amount and any notes, then call save_offer.
- Thank them and let them know a negotiator will be in touch shortly.

Be warm and brief. One message at a time.
""",
    tools=[send_reminder, send_followup, save_offer],
)
