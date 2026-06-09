import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Free-tier Gemini API (Google AI Studio — no GCP billing)
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    use_vertexai: bool = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"

    model: str = os.getenv("AVA_MODEL", "gemini-2.0-flash")
    environment: str = os.getenv("ENVIRONMENT", "dev")
    port: int = int(os.getenv("PORT", "8080"))


config = Config()

if not config.google_api_key:
    raise EnvironmentError("GOOGLE_API_KEY is not set. Copy .env.example to .env and add your key.")
