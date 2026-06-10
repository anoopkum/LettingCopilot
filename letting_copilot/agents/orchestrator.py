"""Orchestrator agent — entry point for all lettings enquiries."""
from google.adk.agents import Agent
from google.adk.tools import AgentTool
from letting_copilot.config import config
from .qualification import qualification_agent
from .matching import matching_agent
from .booking import booking_agent
from .followup import followup_agent

# Wrap each sub-agent as an AgentTool so the orchestrator can invoke them
# programmatically with a typed call, not just via natural-language delegation.
qualify_tool  = AgentTool(agent=qualification_agent)
match_tool    = AgentTool(agent=matching_agent)
book_tool     = AgentTool(agent=booking_agent)
followup_tool = AgentTool(agent=followup_agent)

root_agent = Agent(
    name="ava_orchestrator",
    model=config.model,
    description="Ava — the AI lettings agent. Handles all enquiries from first contact to viewing booked.",
    instruction="""
You are Ava, a professional and friendly AI lettings agent.

Your job is to handle lettings enquiries end-to-end using the tools available to you:

1. Greet the applicant warmly and confirm which property they're enquiring about.
2. Call `qualification_agent` to gather their details (name, budget, employment, move date, contact).
3. If they don't qualify for that property, call `matching_agent` to find alternatives.
4. Once qualified and a property is confirmed, call `booking_agent` to schedule a viewing.
5. After a viewing is booked, call `followup_agent` for reminders and post-viewing feedback.

Always be warm, concise, and professional. Never ask for more than one piece of information at a time.
If the applicant seems unsuitable for all properties, politely let them know and wish them well.
""",
    tools=[qualify_tool, match_tool, book_tool, followup_tool],
)
