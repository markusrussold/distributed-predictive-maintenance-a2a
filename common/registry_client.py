"""
Helper mixed into every agent (including the orchestrator) for talking to
the Registry agent: registering an AgentCard on startup, sending periodic
heartbeats so the registry entry stays "live", deregistering on shutdown,
and looking up peers by capability at call time (never by a hardcoded
host:port).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx

from common.models import AgentCard, RegisteredAgent

logger = logging.getLogger("registry_client")


class RegistryClient:
    def __init__(self, registry_url: str, card: AgentCard, heartbeat_seconds: float = 5.0):
        self.registry_url = registry_url.rstrip("/")
        self.card = card
        self.heartbeat_seconds = heartbeat_seconds
        self._task: asyncio.Task | None = None
        self._client = httpx.AsyncClient(timeout=5.0)

    async def register(self) -> None:
        for attempt in range(1, 11):
            try:
                resp = await self._client.post(
                    f"{self.registry_url}/register",
                    json={"card": self.card.model_dump(), "ttl_seconds": self.heartbeat_seconds * 3},
                )
                resp.raise_for_status()
                logger.info("Registered %s with registry at %s", self.card.name, self.registry_url)
                return
            except httpx.HTTPError as exc:
                logger.warning(
                    "Registry not reachable yet (attempt %d/10): %s", attempt, exc
                )
                await asyncio.sleep(1.5)
        logger.error("Giving up registering %s with the registry", self.card.name)

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                await self._client.post(f"{self.registry_url}/heartbeat/{self.card.name}")
            except httpx.HTTPError as exc:
                logger.warning("Heartbeat failed, re-registering: %s", exc)
                await self.register()

    async def deregister(self) -> None:
        try:
            await self._client.delete(f"{self.registry_url}/agents/{self.card.name}")
        except httpx.HTTPError:
            pass
        await self._client.aclose()

    async def lookup(self, capability: str) -> list[RegisteredAgent]:
        resp = await self._client.get(
            f"{self.registry_url}/lookup", params={"capability": capability}
        )
        resp.raise_for_status()
        return [RegisteredAgent(**item) for item in resp.json()]

    @asynccontextmanager
    async def lifespan(self):
        """FastAPI lifespan context: register + heartbeat on startup, deregister on shutdown."""
        await self.register()
        self._task = asyncio.create_task(self._heartbeat_loop())
        try:
            yield
        finally:
            if self._task:
                self._task.cancel()
            await self.deregister()
