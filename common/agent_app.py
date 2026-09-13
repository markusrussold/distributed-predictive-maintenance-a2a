"""Small factory shared by the specialist agents and the orchestrator so
each `main.py` only has to define its AgentCard and its /tasks/send logic.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.models import AgentCard
from common.registry_client import RegistryClient


def make_app(card: AgentCard) -> tuple[FastAPI, RegistryClient]:
    registry_url = os.environ.get("REGISTRY_URL", "http://127.0.0.1:8000")
    registry = RegistryClient(registry_url, card)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with registry.lifespan():
            yield

    app = FastAPI(title=card.name, lifespan=lifespan)

    @app.get("/.well-known/agent.json")
    def agent_card() -> AgentCard:
        return card

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "agent": card.name}

    return app, registry
