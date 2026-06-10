"""
LangGraph workflow — typed StateGraph for the lettings pipeline.
Nodes map 1-to-1 with ADK agents. Conditional edges drive the flow.
"""
from __future__ import annotations
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import logging

logger = logging.getLogger(__name__)


# ── Typed state ───────────────────────────────────────────────────────────────
class LettingsState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

    # Applicant data collected during qualification
    applicant_name: str | None
    budget_pcm: float | None
    employment_status: str | None
    move_date: str | None
    contact: str | None

    # Property & booking
    enquired_property_id: str | None
    matched_property_id: str | None
    booking_id: str | None
    viewing_datetime: str | None

    # Flow control
    stage: Literal[
        "start",
        "qualifying",
        "matching",
        "booking",
        "followup",
        "complete",
    ]
    qualified: bool
    needs_matching: bool
    viewing_booked: bool


# ── Node functions ─────────────────────────────────────────────────────────────
async def qualify_node(state: LettingsState) -> dict:
    """Run qualification agent — collect applicant details."""
    from letting_copilot.agents.qualification import qualification_agent
    from letting_copilot.workflow.node_runner import run_adk_agent

    last_msg = state["messages"][-1].content if state["messages"] else ""
    response = await run_adk_agent(qualification_agent, last_msg, state)

    qualified = bool(
        state.get("applicant_name") and
        state.get("budget_pcm") and
        state.get("employment_status") and
        state.get("move_date") and
        state.get("contact")
    )
    # Always run matching after qualification — even if a specific property was enquired about,
    # we confirm availability and show alternatives via matching_agent.
    needs_matching = qualified

    return {
        "messages": [AIMessage(content=response)],
        "stage": "qualifying",
        "qualified": qualified,
        "needs_matching": needs_matching,
    }


async def match_node(state: LettingsState) -> dict:
    """Run matching agent — find suitable properties."""
    from letting_copilot.agents.matching import matching_agent
    from letting_copilot.workflow.node_runner import run_adk_agent

    last_msg = state["messages"][-1].content if state["messages"] else ""
    response = await run_adk_agent(matching_agent, last_msg, state)

    return {
        "messages": [AIMessage(content=response)],
        "stage": "matching",
    }


async def book_node(state: LettingsState) -> dict:
    """Run booking agent — find slot and confirm viewing."""
    from letting_copilot.agents.booking import booking_agent
    from letting_copilot.workflow.node_runner import run_adk_agent

    last_msg = state["messages"][-1].content if state["messages"] else ""
    response = await run_adk_agent(booking_agent, last_msg, state)

    viewing_booked = state.get("booking_id") is not None

    return {
        "messages": [AIMessage(content=response)],
        "stage": "booking",
        "viewing_booked": viewing_booked,
    }


async def followup_node(state: LettingsState) -> dict:
    """Run followup agent — reminders, feedback, offers."""
    from letting_copilot.agents.followup import followup_agent
    from letting_copilot.workflow.node_runner import run_adk_agent

    last_msg = state["messages"][-1].content if state["messages"] else ""
    response = await run_adk_agent(followup_agent, last_msg, state)

    return {
        "messages": [AIMessage(content=response)],
        "stage": "complete",
    }


# ── Conditional edge functions ────────────────────────────────────────────────
def route_after_qualify(state: LettingsState) -> str:
    """Single-turn mode: qualify once then stop. Multi-turn chaining via /chat."""
    if state.get("needs_matching"):
        return "match"
    return END


def route_after_match(state: LettingsState) -> str:
    return "book"


def route_after_book(state: LettingsState) -> str:
    if not state.get("viewing_booked"):
        return END          # booking needs more info — return to caller
    return "followup"


# ── Graph builder ─────────────────────────────────────────────────────────────
def build_lettings_graph() -> StateGraph:
    g = StateGraph(LettingsState)

    g.add_node("qualify", qualify_node)
    g.add_node("match", match_node)
    g.add_node("book", book_node)
    g.add_node("followup", followup_node)

    g.set_entry_point("qualify")

    g.add_conditional_edges(
        "qualify",
        route_after_qualify,
        {"match": "match", END: END},
    )
    g.add_conditional_edges(
        "match",
        route_after_match,
        {"book": "book"},
    )
    g.add_conditional_edges(
        "book",
        route_after_book,
        {"followup": "followup", END: END},
    )
    g.add_edge("followup", END)

    return g.compile()
