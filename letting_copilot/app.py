"""
LettingCopilot — FastAPI application
Exposes:
  /          → Chat UI
  /health    → Health check (public)
  /auth/token → Issue JWT (public)
  /chat      → ADK orchestrator (JWT protected)
  /workflow  → LangGraph pipeline (JWT protected)
  /a2a       → A2A JSON-RPC task endpoint (JWT protected)
  /.well-known/agent.json → A2A AgentCard (public)
  /properties → Property list (JWT protected)
"""
import logging
import uuid
import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from letting_copilot.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Must be set before any google.adk imports
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
os.environ["GOOGLE_API_KEY"] = config.google_api_key
os.environ["GOOGLE_GENAI_API_KEY"] = config.google_api_key

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from letting_copilot.agents import root_agent
from letting_copilot.auth.jwt_handler import create_token, verify_token
from letting_copilot.a2a import agent_card, a2a_router
from letting_copilot.workflow import build_lettings_graph
from letting_copilot.guardrails import check_input, check_output

# ── ADK setup ─────────────────────────────────────────────────────────────────
session_service = InMemorySessionService()


def _before_model_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """
    ADK before-model callback.
    1. Logs agent name + message count.
    2. Runs input guardrail on the last user message.
       If blocked, returns a synthetic LlmResponse so the LLM is never called.
    """
    agent_name = callback_context.agent_name
    contents = llm_request.contents or []
    logger.info("[ADK] before_model agent=%s messages=%d", agent_name, len(contents))

    # Find the last user-role message to guard
    last_user_text = ""
    for content in reversed(contents):
        if getattr(content, "role", None) == "user":
            parts = getattr(content, "parts", [])
            if parts and hasattr(parts[0], "text"):
                last_user_text = parts[0].text
                break

    if last_user_text:
        result = check_input(last_user_text, agent_name=agent_name)
        if result.blocked:
            logger.info(
                "[guardrail:input] blocked agent=%s reason=%s",
                agent_name, result.reason,
            )
            # Return a synthetic LlmResponse — ADK will use this instead of calling Gemini
            return LlmResponse(
                content=Content(
                    role="model",
                    parts=[Part(text=result.suggestion)],
                )
            )

    return None  # proceed normally


def _after_model_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """
    ADK after-model callback.
    1. Logs response preview.
    2. Runs output guardrail — redacts secrets, error bleeds, empty responses.
       If the output is modified, returns a new LlmResponse.
    """
    agent_name = callback_context.agent_name
    parts = llm_response.content.parts if llm_response.content else []
    raw_text = parts[0].text if parts else ""

    logger.info("[ADK] after_model agent=%s preview=%r", agent_name, raw_text[:80])

    cleaned = check_output(raw_text, agent_name=agent_name)
    if cleaned != raw_text:
        return LlmResponse(
            content=Content(
                role="model",
                parts=[Part(text=cleaned)],
            )
        )

    return None  # use original response


# Wire callbacks into root agent (applies to orchestrator + all sub-agents via ADK)
root_agent.before_model_callback = _before_model_callback
root_agent.after_model_callback = _after_model_callback

runner = Runner(
    agent=root_agent,
    app_name="letting_copilot",
    session_service=session_service,
)

# ── LangGraph ─────────────────────────────────────────────────────────────────
lettings_graph = build_lettings_graph()

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="LettingCopilot",
    description="AI lettings agent — ADK + LangGraph + A2A + JWT + Guardrails",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(a2a_router)


# ── Models ────────────────────────────────────────────────────────────────────
class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str = "applicant"


class ChatResponse(BaseModel):
    response: str
    session_id: str
    agent_name: str
    guardrail_triggered: bool = False


class WorkflowRequest(BaseModel):
    message: str
    session_id: str | None = None


# ── Public endpoints ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": config.environment,
        "model": config.model,
        "backend": "google-ai-studio",
        "features": ["adk", "langgraph", "a2a", "jwt", "guardrails"],
    }


@app.get("/.well-known/agent.json")
async def agent_card_endpoint():
    return JSONResponse(content=agent_card)


@app.post("/auth/token")
async def issue_token(req: TokenRequest):
    if not req.client_id or not req.client_secret:
        raise HTTPException(status_code=400, detail="client_id and client_secret required")
    token = create_token(
        subject=req.client_id,
        extra={"client_id": req.client_id, "scope": "chat workflow a2a"},
    )
    return {"access_token": token, "token_type": "bearer", "expires_in": 86400}


# ── Protected endpoints ───────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, claims: dict = Depends(verify_token)):
    """
    ADK orchestrator endpoint with guardrails.

    Input guardrail runs inside before_model_callback — if triggered,
    the LLM is never called and the suggestion is returned directly.
    Output guardrail runs inside after_model_callback — redacts any
    secrets or internal errors that leak into the LLM response.

    A fast-path input check also runs here BEFORE creating a session,
    so truly bad inputs (empty, injection) are rejected immediately
    without touching ADK at all.
    """
    # Fast-path guardrail — catch bad input before any ADK work
    fast_check = check_input(req.message, agent_name="ava_orchestrator")
    if fast_check.blocked:
        logger.info("[guardrail:fast-path] blocked reason=%s", fast_check.reason)
        session_id = req.session_id or str(uuid.uuid4())
        return ChatResponse(
            response=fast_check.suggestion,
            session_id=session_id,
            agent_name="guardrail",
            guardrail_triggered=True,
        )

    session_id = req.session_id or str(uuid.uuid4())
    user_id = claims.get("sub", req.user_id)

    session = await session_service.get_session(
        app_name="letting_copilot", user_id=user_id, session_id=session_id
    )
    if session is None:
        await session_service.create_session(
            app_name="letting_copilot", user_id=user_id, session_id=session_id
        )

    content = Content(role="user", parts=[Part(text=req.message)])
    response_text = ""
    responding_agent = root_agent.name

    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                if hasattr(event, "author"):
                    responding_agent = event.author
    except Exception as e:
        err = str(e)
        logger.error("ADK error: %s", err)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            raise HTTPException(status_code=429, detail="Gemini API quota exceeded — please try again shortly.")
        raise HTTPException(status_code=500, detail=f"Agent error: {err[:200]}")

    if not response_text:
        raise HTTPException(status_code=500, detail="No response from agent")

    # Final output guard (belt-and-braces — ADK callback should already have cleaned it)
    response_text = check_output(response_text, agent_name=responding_agent)

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        agent_name=responding_agent,
    )


@app.post("/workflow")
async def workflow_endpoint(req: WorkflowRequest, claims: dict = Depends(verify_token)):
    from langchain_core.messages import HumanMessage

    # Guardrail before entering LangGraph
    fast_check = check_input(req.message)
    if fast_check.blocked:
        return {
            "response": fast_check.suggestion,
            "session_id": req.session_id or str(uuid.uuid4()),
            "stage": "guardrail",
            "qualified": False,
            "viewing_booked": False,
            "guardrail_triggered": True,
        }

    session_id = req.session_id or str(uuid.uuid4())
    initial_state = {
        "messages": [HumanMessage(content=req.message)],
        "applicant_name": None,
        "budget_pcm": None,
        "employment_status": None,
        "move_date": None,
        "contact": None,
        "enquired_property_id": None,
        "matched_property_id": None,
        "booking_id": None,
        "viewing_datetime": None,
        "stage": "start",
        "qualified": False,
        "needs_matching": False,
        "viewing_booked": False,
        "session_id": session_id,
    }

    try:
        result = await lettings_graph.ainvoke(initial_state)
        last_ai = next(
            (m.content for m in reversed(result["messages"]) if hasattr(m, "content") and m.type == "ai"),
            "No response"
        )
        last_ai = check_output(last_ai)
        return {
            "response": last_ai,
            "session_id": session_id,
            "stage": result.get("stage", "unknown"),
            "qualified": result.get("qualified", False),
            "viewing_booked": result.get("viewing_booked", False),
        }
    except Exception as e:
        logger.error("Workflow error: %s", e)
        raise HTTPException(status_code=500, detail=f"Workflow error: {str(e)[:200]}")


@app.get("/properties")
async def list_properties(claims: dict = Depends(verify_token)):
    import letting_copilot.tools.property_store as ps
    ps._load()
    return ps._PROPERTIES


# ── UI (public) ───────────────────────────────────────────────────────────────
ui_dir = os.path.join(os.path.dirname(__file__), "..", "ui")
if os.path.isdir(ui_dir):
    app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")

    @app.get("/")
    async def serve_ui():
        return FileResponse(os.path.join(ui_dir, "index.html"))
