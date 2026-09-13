"""
Thermal Analysis Agent
----------------------
Capability: "thermal-analysis"

Takes a series of bearing/housing temperature readings (°C) for a
machine and scores how anomalous they are.
"""
from __future__ import annotations

import os
import statistics
from urllib.parse import urlparse

from common.agent_app import make_app
from common.models import AgentCard, Message, Skill, TaskRequest, TaskResponse, TaskStatus

SELF_URL = os.environ.get("SELF_URL", "http://127.0.0.1:8003")
# Unique per replica; see the matching comment in vibration_agent/main.py.
INSTANCE_NAME = f"thermal-agent@{urlparse(SELF_URL).netloc}"

CARD = AgentCard(
    name=INSTANCE_NAME,
    description="Analyzes machine temperature readings for overheating risk.",
    url=SELF_URL,
    capabilities=["thermal-analysis"],
    skills=[
        Skill(
            id="analyze-temperature",
            name="Analyze temperature readings",
            description="Scores a series of bearing/housing temperature readings (°C) for anomaly severity.",
            tags=["thermal-analysis", "condition-monitoring"],
        )
    ],
)

app, registry = make_app(CARD)

WARN_C = 80.0
CRITICAL_C = 95.0


def _score(readings: list[float]) -> tuple[float, str, str]:
    mean_t = statistics.fmean(readings)
    peak_t = max(readings)
    if peak_t < WARN_C:
        level, note = "normal", "within safe operating temperature"
    elif peak_t < CRITICAL_C:
        level, note = "warning", "elevated — approaching thermal limits, inspect cooling/lubrication"
    else:
        level, note = "critical", "critical — overheating risk, reduce load or shut down"
    anomaly_score = min(100.0, round((peak_t / (2 * CRITICAL_C)) * 100, 1))
    findings = f"mean={mean_t:.1f}°C, peak={peak_t:.1f}°C, level={level}: {note}"
    return anomaly_score, level, findings


@app.post("/tasks/send")
def handle_task(req: TaskRequest) -> TaskResponse:
    data = req.message.data()
    readings: list[float] = data.get("temperature_readings_c", [])
    if not readings:
        return TaskResponse(
            id=req.id,
            status=TaskStatus(state="failed", message=Message(
                role="agent", parts=[{"type": "text", "text": "No temperature_readings_c provided."}]
            )),
        )

    anomaly_score, level, findings = _score(readings)
    return TaskResponse(
        id=req.id,
        status=TaskStatus(state="completed"),
        artifacts=[{
            "name": "thermal-report",
            "parts": [
                {"type": "text", "text": findings},
                {"type": "data", "data": {
                    "thermal_anomaly_score": anomaly_score,
                    "thermal_level": level,
                }},
            ],
        }],
    )
