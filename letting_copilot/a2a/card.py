"""
A2A AgentCard — published at /.well-known/agent.json
Describes this agent's capabilities to other agents and orchestrators.
"""
from typing import Any

agent_card: dict[str, Any] = {
    "schema_version": "0.2",
    "name": "LettingCopilot",
    "description": (
        "AI lettings agent. Qualifies applicants, matches properties, "
        "books viewings, and collects offers."
    ),
    "url": "https://letting-copilot-ruzwhtmsaq-uc.a.run.app",
    "version": "0.1.0",
    "capabilities": {
        "streaming": False,
        "push_notifications": False,
        "state_transition_history": True,
    },
    "authentication": {
        "schemes": ["bearer"]
    },
    "skills": [
        {
            "id": "qualify_applicant",
            "name": "Qualify Applicant",
            "description": "Collect income, employment, move date, budget from an applicant.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "enquiry_text": {"type": "string"},
                    "property_id": {"type": "string"},
                },
                "required": ["enquiry_text"],
            },
        },
        {
            "id": "book_viewing",
            "name": "Book Viewing",
            "description": "Check availability and book a viewing slot for a qualified applicant.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "applicant_id": {"type": "string"},
                    "property_id": {"type": "string"},
                },
                "required": ["applicant_id", "property_id"],
            },
        },
        {
            "id": "match_property",
            "name": "Match Property",
            "description": "Find suitable properties for an applicant based on budget and preferences.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "budget_pcm": {"type": "number"},
                    "bedrooms": {"type": "integer"},
                    "area": {"type": "string"},
                },
                "required": ["budget_pcm"],
            },
        },
    ],
}
