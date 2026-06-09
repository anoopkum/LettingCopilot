"""FastAPI app — uses Google AI Studio free-tier Gemini API via ADK."""
import logging
import uuid
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from letting_copilot.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set ADK to use free-tier API (not Vertex AI)
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
os.environ["GOOGLE_API_KEY"] = config.google_api_key

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part
from letting_copilot.agents import root_agent

app = FastAPI(
    title="LettingCopilot",
    description="AI-powered lettings qualification and booking agent (POC)",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

session_service = InMemorySessionService()
runner = Runner(
    agent=root_agent,
    app_name="letting_copilot",
    session_service=session_service,
)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str = "applicant"


class ChatResponse(BaseModel):
    response: str
    session_id: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "environment": config.environment,
        "model": config.model,
        "backend": "google-ai-studio",
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    try:
        await session_service.get_session(
            app_name="letting_copilot",
            user_id=req.user_id,
            session_id=session_id,
        )
    except Exception:
        await session_service.create_session(
            app_name="letting_copilot",
            user_id=req.user_id,
            session_id=session_id,
        )

    content = Content(role="user", parts=[Part(text=req.message)])
    response_text = ""

    async for event in runner.run_async(
        user_id=req.user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text

    if not response_text:
        raise HTTPException(status_code=500, detail="No response from agent")

    return ChatResponse(response=response_text, session_id=session_id)


@app.get("/properties")
async def list_properties():
    from letting_copilot.tools.property_store import _load, _PROPERTIES
    _load()
    return _PROPERTIES


# Serve the simple chat UI
ui_dir = os.path.join(os.path.dirname(__file__), "..", "ui")
if os.path.isdir(ui_dir):
    app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")

    @app.get("/")
    async def serve_ui():
        return FileResponse(os.path.join(ui_dir, "index.html"))
