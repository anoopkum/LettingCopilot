"""Matching agent — finds alternative properties when the original isn't suitable."""
from google.adk.agents import Agent
from letting_copilot.config import config
from letting_copilot.tools.property_store import search_properties

matching_agent = Agent(
    name="matching_agent",
    model=config.model,
    description="Finds alternative properties in the portfolio when an applicant doesn't fit their original enquiry.",
    instruction="""
An applicant doesn't quite fit the property they enquired about. Your job is to find a better match.

You know their:
- Monthly budget (PCM)
- Number of bedrooms required
- Preferred area (if stated)

Call search_properties with their criteria. Present up to 3 matching properties clearly:
- Property name and address
- Rent PCM
- Number of bedrooms
- Key features

Ask which property they'd like to enquire about. Once they pick one, return the chosen property_id to the orchestrator.
If nothing matches, apologise and suggest they register their interest for future listings.
""",
    tools=[search_properties],
)
