"""
Shared data models for the agent-to-agent (A2A) protocol used by every
agent in this system.

The shapes here are a deliberately small subset of the public A2A
protocol spec (https://google.github.io/A2A/): an AgentCard advertises
identity + capabilities, and Task/Message/Part/Artifact carry work
between agents. Trimming the spec keeps every agent's HTTP surface to
two endpoints (`/.well-known/agent.json` and `/tasks/send`) while still
being recognizably "A2A shaped" rather than a bespoke ad-hoc API.
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Agent discovery (Agent Card)
# --------------------------------------------------------------------------

class Skill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    """Self-description an agent publishes and registers with the Registry."""

    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: list[str] = Field(
        default_factory=list,
        description="Capability tags other agents can look up in the registry.",
    )
    skills: list[Skill] = Field(default_factory=list)


class RegisteredAgent(BaseModel):
    """What the Registry stores/returns: an AgentCard plus liveness info."""

    card: AgentCard
    last_seen: float
    ttl_seconds: float


# --------------------------------------------------------------------------
# Task messages (A2A-style)
# --------------------------------------------------------------------------

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class DataPart(BaseModel):
    type: Literal["data"] = "data"
    data: dict[str, Any] = Field(default_factory=dict)


Part = TextPart | DataPart


class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]

    def text(self) -> str:
        return "\n".join(p.text for p in self.parts if isinstance(p, TextPart))

    def data(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for p in self.parts:
            if isinstance(p, DataPart):
                merged.update(p.data)
        return merged


class TaskStatus(BaseModel):
    state: Literal["submitted", "working", "completed", "failed"]
    message: Message | None = None


class Artifact(BaseModel):
    name: str | None = None
    parts: list[Part] = Field(default_factory=list)


class TaskRequest(BaseModel):
    id: str
    message: Message


class TaskResponse(BaseModel):
    id: str
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)

    def data(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for a in self.artifacts:
            for p in a.parts:
                if isinstance(p, DataPart):
                    merged.update(p.data)
        return merged

    def text(self) -> str:
        chunks = []
        for a in self.artifacts:
            for p in a.parts:
                if isinstance(p, TextPart):
                    chunks.append(p.text)
        return "\n".join(chunks)
