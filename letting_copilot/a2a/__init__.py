"""A2A (Agent-to-Agent) protocol — AgentCard + JSON-RPC task endpoint."""
from .card import agent_card
from .router import a2a_router

__all__ = ["agent_card", "a2a_router"]
