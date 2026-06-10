"""
A2A JSON-RPC task endpoint — /a2a
Implements the Agent-to-Agent protocol task lifecycle:
  tasks/send → run agent, return result
  tasks/get  → retrieve a task by ID
"""
import uuid
import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from letting_copilot.auth.jwt_handler import verify_token

logger = logging.getLogger(__name__)
a2a_router = APIRouter(prefix="/a2a", tags=["A2A"])

# In-memory task store (replace with Redis/Firestore in prod)
_tasks: dict[str, dict] = {}


class A2AMessage(BaseModel):
    role: str
    parts: list[dict[str, Any]]


class A2ATaskRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    method: str  # "tasks/send" | "tasks/get" | "tasks/cancel"
    params: dict[str, Any]


class A2ATaskResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


async def _run_agent_task(task_id: str, skill_id: str, message: str, session_id: str) -> dict:
    """Execute the appropriate agent skill and return structured result."""
    from letting_copilot.agents import root_agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part

    svc = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name="letting_copilot_a2a", session_service=svc)

    await svc.create_session(
        app_name="letting_copilot_a2a", user_id="a2a_client", session_id=session_id
    )
    content = Content(role="user", parts=[Part(text=message)])
    response_text = ""

    async for event in runner.run_async(
        user_id="a2a_client", session_id=session_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text

    return {
        "id": task_id,
        "status": {"state": "completed"},
        "artifacts": [
            {
                "name": "agent_response",
                "parts": [{"type": "text", "text": response_text}],
            }
        ],
    }


@a2a_router.post("", response_model=A2ATaskResponse)
async def a2a_endpoint(
    req: A2ATaskRequest,
    _claims: dict = Depends(verify_token),
):
    task_id = str(uuid.uuid4())

    if req.method == "tasks/send":
        params = req.params
        message_parts = params.get("message", {}).get("parts", [])
        message_text = next((p.get("text", "") for p in message_parts if p.get("type") == "text"), "")
        skill_id = params.get("skill_id", "qualify_applicant")
        session_id = params.get("session_id", str(uuid.uuid4()))

        _tasks[task_id] = {"id": task_id, "status": {"state": "working"}}
        try:
            result = await _run_agent_task(task_id, skill_id, message_text, session_id)
            _tasks[task_id] = result
            return A2ATaskResponse(id=req.id, result=result)
        except Exception as e:
            err = {"code": -32000, "message": str(e)[:200]}
            _tasks[task_id] = {"id": task_id, "status": {"state": "failed"}, "error": str(e)}
            return A2ATaskResponse(id=req.id, error=err)

    elif req.method == "tasks/get":
        task_id_query = req.params.get("id", "")
        task = _tasks.get(task_id_query)
        if not task:
            return A2ATaskResponse(
                id=req.id, error={"code": -32001, "message": "Task not found"}
            )
        return A2ATaskResponse(id=req.id, result=task)

    elif req.method == "tasks/cancel":
        return A2ATaskResponse(
            id=req.id, error={"code": -32002, "message": "Cancel not supported in POC"}
        )

    return A2ATaskResponse(
        id=req.id, error={"code": -32601, "message": f"Method not found: {req.method}"}
    )
