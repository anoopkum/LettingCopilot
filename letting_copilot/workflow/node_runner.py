"""
Runs a single ADK agent as a LangGraph node.
Bridges ADK's async event stream with LangGraph's sync/async node contract.
"""
import logging
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

logger = logging.getLogger(__name__)

# Shared session service per process (ADK agents share context within a session)
_session_service = InMemorySessionService()


async def run_adk_agent(agent: Agent, message: str, state: dict) -> str:
    """
    Run an ADK agent for a single turn.
    Carries session_id from LangGraph state so ADK maintains conversation history
    across node transitions within the same user session.
    """
    session_id = state.get("session_id", "default")
    app_name = f"lg_{agent.name}"

    existing = await _session_service.get_session(
        app_name=app_name, user_id="workflow", session_id=session_id
    )
    if existing is None:
        await _session_service.create_session(
            app_name=app_name, user_id="workflow", session_id=session_id
        )

    runner = Runner(agent=agent, app_name=app_name, session_service=_session_service)
    content = Content(role="user", parts=[Part(text=message)])
    response_text = ""

    async for event in runner.run_async(
        user_id="workflow", session_id=session_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text

    logger.info("[ADK node=%s] %s → %s", agent.name, message[:60], response_text[:60])
    return response_text
