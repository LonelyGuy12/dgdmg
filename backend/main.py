"""
main.py — FastAPI backend for DataHub-Grounded dbt Model Generator.
Exposes SSE streaming endpoint for real-time agent progress.
"""
from __future__ import annotations
import os
import json
import asyncio
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from agent import run_agent

load_dotenv()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

app = FastAPI(
    title="DataHub dbt Model Generator",
    description="Generates production-ready dbt models grounded in DataHub metadata",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    request: str


@app.get("/api/health")
async def health():
    use_mock = os.getenv("USE_MOCK_MCP", "true").lower() == "true"
    github_configured = bool(os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPO"))
    groq_configured = bool(os.getenv("GROQ_API_KEY"))
    return {
        "status": "healthy",
        "config": {
            "useMockMcp": use_mock,
            "githubConfigured": github_configured,
            "groqConfigured": groq_configured,
            "groqModel": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "datahubUrl": os.getenv("DATAHUB_MCP_URL", "mock"),
            "targetRepo": os.getenv("GITHUB_REPO", "not set"),
        }
    }


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """
    Stream SSE events for dbt model generation pipeline.
    Events format: data: {"step": "...", "status": "...", "message": "...", "data": {...}}
    """
    if not req.request.strip():
        return JSONResponse({"error": "Request cannot be empty"}, status_code=400)

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for event in run_agent(req.request.strip()):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)  # yield control to event loop
        except Exception as e:
            error_event = {
                "step": "error",
                "status": "error",
                "message": str(e),
                "data": {}
            }
            yield f"data: {json.dumps(error_event)}\n\n"
        finally:
            yield "data: {\"step\": \"done\", \"status\": \"done\", \"message\": \"Stream complete\", \"data\": {}}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
