"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response returned by application health probes."""

    status: Literal["ok"]


app = FastAPI(
    title="TNPSC Book RAG API",
    description="Retrieval-augmented generation over Tamil Nadu State Board textbooks.",
    version="0.1.0",
)


@app.get("/health/live", response_model=HealthResponse, tags=["health"])
async def liveness() -> HealthResponse:
    """Report whether the API process is running."""
    return HealthResponse(status="ok")
