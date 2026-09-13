"""
Orchestrator Agent
------------------
Capability: "predictive-maintenance-coordination"

The entry point of the system. Given raw sensor readings for a machine,
it does NOT know or hardcode which host/port runs vibration analysis,
thermal analysis, or maintenance scheduling. For every step it asks the
Registry agent "who can do X right now?", picks a live provider, and
calls that provider's own `/tasks/send` endpoint. The maintenance step
only fires once both analysis results are in, so this is a genuine
three-agent pipeline, not three isolated calls.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from common.agent_app import make_app
from common.models import (
    AgentCard,
    DataPart,
    Message,
    Skill,
    TaskRequest,
    TaskResponse,
    TaskStatus,
    TextPart,
)

SELF_URL = os.environ.get("SELF_URL", "http://127.0.0.1:8001")
# Unique per replica; see the matching comment in vibration_agent/main.py.
INSTANCE_NAME = f"orchestrator-agent@{urlparse(SELF_URL).netloc}"

CARD = AgentCard(
    name=INSTANCE_NAME,
    description="Coordinates vibration, thermal, and maintenance-scheduling agents into one diagnosis.",
    url=SELF_URL,
    capabilities=["predictive-maintenance-coordination"],
    skills=[
        Skill(
            id="diagnose-machine",
            name="Diagnose machine health",
            description="Runs vibration + thermal analysis, then requests a maintenance recommendation, for one machine.",
            tags=["predictive-maintenance-coordination"],
        )
    ],
)

app, registry = make_app(CARD)

_http = httpx.AsyncClient(timeout=10.0)


async def _call_agent(url: str, data: dict, prompt: str) -> TaskResponse:
    task_id = str(uuid.uuid4())
    payload = TaskRequest(
        id=task_id,
        message=Message(role="user", parts=[TextPart(text=prompt), DataPart(data=data)]),
    )
    resp = await _http.post(f"{url}/tasks/send", json=payload.model_dump())
    resp.raise_for_status()
    return TaskResponse(**resp.json())


async def _call_capability(capability: str, data: dict, prompt: str) -> tuple[TaskResponse, str]:
    """Look up every live provider of `capability` and call one, load-balancing
    across replicas and falling back to another if the chosen one turns out to
    be unreachable (e.g. it crashed a moment ago and its heartbeat just hasn't
    expired from the registry yet -- the normal detection-window trade-off of
    any TTL-based registry)."""
    candidates = await registry.lookup(capability)
    if not candidates:
        raise HTTPException(503, f"No live agent currently advertises capability '{capability}'.")
    random.shuffle(candidates)  # load-balance across replicas

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            resp = await _call_agent(candidate.card.url, data, prompt)
            trace = f"registry lookup -> {capability} served by '{candidate.card.name}' @ {candidate.card.url}"
            return resp, trace
        except httpx.HTTPError as exc:
            last_error = exc
            continue
    raise HTTPException(
        502,
        f"All {len(candidates)} registered provider(s) of '{capability}' were unreachable "
        f"(last error: {last_error}).",
    )


async def diagnose(machine_id: str, vibration_readings: list[float],
                    temperature_readings: list[float], operating_hours: float) -> dict:
    trace: list[str] = []

    (vibration_resp, vib_trace), (thermal_resp, therm_trace) = await asyncio.gather(
        _call_capability(
            "vibration-analysis",
            {"machine_id": machine_id, "vibration_readings_mm_s": vibration_readings},
            f"Analyze vibration readings for machine {machine_id}",
        ),
        _call_capability(
            "thermal-analysis",
            {"machine_id": machine_id, "temperature_readings_c": temperature_readings},
            f"Analyze temperature readings for machine {machine_id}",
        ),
    )
    trace.extend([vib_trace, therm_trace])
    if vibration_resp.status.state != "completed" or thermal_resp.status.state != "completed":
        raise HTTPException(502, "A specialist agent failed to complete its analysis.")

    combined = {**vibration_resp.data(), **thermal_resp.data(), "operating_hours": operating_hours}

    maintenance_resp, maint_trace = await _call_capability(
        "maintenance-scheduling",
        combined,
        f"Recommend maintenance action for machine {machine_id}",
    )
    trace.append(maint_trace)
    if maintenance_resp.status.state != "completed":
        raise HTTPException(502, "The maintenance-scheduling agent failed to complete.")

    return {
        "machine_id": machine_id,
        "vibration_report": vibration_resp.text(),
        "thermal_report": thermal_resp.text(),
        "maintenance_recommendation": maintenance_resp.text(),
        "details": maintenance_resp.data(),
        "pipeline_trace": trace,
    }


@app.post("/tasks/send")
async def handle_task(req: TaskRequest) -> TaskResponse:
    data = req.message.data()
    required = ("machine_id", "vibration_readings_mm_s", "temperature_readings_c")
    if not all(k in data for k in required):
        return TaskResponse(
            id=req.id,
            status=TaskStatus(state="failed", message=Message(
                role="agent",
                parts=[TextPart(text=f"Requires {', '.join(required)} (+ optional operating_hours).")],
            )),
        )

    result = await diagnose(
        data["machine_id"],
        data["vibration_readings_mm_s"],
        data["temperature_readings_c"],
        data.get("operating_hours", 0),
    )
    return TaskResponse(
        id=req.id,
        status=TaskStatus(state="completed"),
        artifacts=[{
            "name": "diagnosis-report",
            "parts": [
                {"type": "text", "text": result["maintenance_recommendation"]},
                {"type": "data", "data": result},
            ],
        }],
    )


@app.post("/diagnose")
async def diagnose_endpoint(payload: dict) -> dict:
    """Convenience REST endpoint for the demo/README (skips the A2A envelope)."""
    required = ("machine_id", "vibration_readings_mm_s", "temperature_readings_c")
    if not all(k in payload for k in required):
        raise HTTPException(400, f"Requires {', '.join(required)} (+ optional operating_hours).")
    start = time.monotonic()
    result = await diagnose(
        payload["machine_id"],
        payload["vibration_readings_mm_s"],
        payload["temperature_readings_c"],
        payload.get("operating_hours", 0),
    )
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return result
