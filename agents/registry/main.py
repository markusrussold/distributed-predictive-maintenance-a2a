"""
Registry Agent (dynamic service discovery)
-------------------------------------------
Every other agent registers its AgentCard here on startup and renews it
with a heartbeat. Callers (chiefly the Orchestrator) never hardcode which
host/port serves a given capability -- they ask this registry for
whoever currently advertises it. Entries that stop heartbeating expire
and silently drop out of lookup results, so the registry always reflects
which agents are actually alive right now.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.models import AgentCard, RegisteredAgent

_STORE: dict[str, RegisteredAgent] = {}


class RegisterRequest(BaseModel):
    card: AgentCard
    ttl_seconds: float = 30.0


def _is_alive(entry: RegisteredAgent) -> bool:
    return (time.time() - entry.last_seen) <= entry.ttl_seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Registry Agent", lifespan=lifespan)


@app.get("/.well-known/agent.json")
def agent_card() -> AgentCard:
    return AgentCard(
        name="registry",
        description="Dynamic service discovery for the predictive-maintenance agent fleet.",
        url="/",
        capabilities=["registry"],
        skills=[],
    )


@app.post("/register")
def register(req: RegisterRequest) -> dict:
    _STORE[req.card.name] = RegisteredAgent(
        card=req.card, last_seen=time.time(), ttl_seconds=req.ttl_seconds
    )
    return {"status": "registered", "name": req.card.name}


@app.post("/heartbeat/{name}")
def heartbeat(name: str) -> dict:
    entry = _STORE.get(name)
    if entry is None:
        raise HTTPException(404, f"Unknown agent '{name}'; register first.")
    entry.last_seen = time.time()
    return {"status": "ok", "name": name}


@app.delete("/agents/{name}")
def deregister(name: str) -> dict:
    _STORE.pop(name, None)
    return {"status": "deregistered", "name": name}


@app.get("/agents")
def list_agents() -> list[RegisteredAgent]:
    """All agents currently known to be alive."""
    return [entry for entry in _STORE.values() if _is_alive(entry)]


@app.get("/lookup")
def lookup(capability: str) -> list[RegisteredAgent]:
    """The core dynamic-lookup endpoint: who can currently do X?"""
    return [
        entry
        for entry in _STORE.values()
        if _is_alive(entry) and capability in entry.card.capabilities
    ]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "known_agents": len(_STORE), "live_agents": len(list_agents())}
