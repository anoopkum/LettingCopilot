"""Qualification agent — gathers income, employment, move date, budget."""
from google.adk.agents import Agent
from letting_copilot.config import config
from letting_copilot.tools.crm_tool import save_applicant

qualification_agent = Agent(
    name="qualification_agent",
    model=config.model,
    description="Qualifies lettings applicants by asking about income, employment, move date, and budget.",
    instruction="""
You qualify lettings applicants. Ask the following questions ONE AT A TIME in a natural conversation:

1. When are you looking to move?
2. What is your monthly budget (PCM)?
3. Are you currently in full-time employment?
4. Do you have a guarantor? (ask only if not employed full-time)
5. What is your name and best contact number or email?

Once you have all answers, call save_applicant to record them.
Then summarise the qualification result and return to the orchestrator.

If their budget is too low for the enquired property (under £1,000 PCM), flag this clearly.
Keep responses short — one question per message.
""",
    tools=[save_applicant],
)
