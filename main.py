"""Entry point — run with: python main.py or uvicorn main:app"""
import uvicorn
from letting_copilot.app import app
from letting_copilot.config import config

if __name__ == "__main__":
    uvicorn.run(
        "letting_copilot.app:app",
        host="0.0.0.0",
        port=config.port,
        reload=config.environment == "dev",
        log_level="info",
    )
