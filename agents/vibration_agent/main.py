"""
Vibration Analysis Agent
------------------------
Capability: "vibration-analysis"

Takes a series of vibration RMS velocity readings (mm/s, ISO 10816 style)
for a machine and scores how anomalous they are.
"""
from __future__ import annotations

import os
import statistics
from urllib.parse import urlparse

from common.agent_app import make_app
from common.models import AgentCard, DataPart, Message, Skill, TaskRequest, TaskResponse, TaskStatus

SELF_URL = os.environ.get("SELF_URL", "http://127.0.0.1:8002")
# Instance identity must be unique per replica, even though replicas share
# the same "vibration-analysis" capability tag -- otherwise two instances
# of this agent would overwrite each other's registry entry (see README's
# scale-out demo, which runs a second replica of this agent).
INSTANCE_NAME = f"vibration-agent@{urlparse(SELF_URL).netloc}"

CARD = AgentCard(
    name=INSTANCE_NAME,
    description="Analyzes machine vibration readings for early fault signatures.",
    url=SELF_URL,
    capabilities=["vibration-analysis"],
    skills=[
        Skill(
            id="analyze-vibration",
            name="Analyze vibration readings",
            description="Scores a series of RMS vibration velocity readings (mm/s) for anomaly severity.",
            tags=["vibration-analysis", "condition-monitoring"],
        )
    ],
)

app, registry = make_app(CARD)

# ISO 10816-3 style zone boundaries (mm/s RMS) for a mid-size rigid-mounted machine.
ZONE_B_MAX = 2.8   # good
ZONE_C_MAX = 4.5   # usable, monitor
ZONE_D_MAX = 7.1   # unsatisfactory, plan action; above this -> danger


def _score(readings: list[float]) -> tuple[float, str, str]:
    mean_v = statistics.fmean(readings)
    peak_v = max(readings)
    if peak_v <= ZONE_B_MAX:
        zone, note = "B", "good — within normal operating range"
    elif peak_v <= ZONE_C_MAX:
        zone, note = "C", "usable — slightly elevated, keep monitoring"
    elif peak_v <= ZONE_D_MAX:
        zone, note = "D", "unsatisfactory — degradation likely, plan maintenance"
    else:
        zone, note = "X", "danger — vibration exceeds safe operating limits"
    # Map peak velocity onto a 0-100 anomaly score, saturating at 2x the danger threshold.
    anomaly_score = min(100.0, round((peak_v / (2 * ZONE_D_MAX)) * 100, 1))
    findings = (
        f"mean={mean_v:.2f} mm/s, peak={peak_v:.2f} mm/s, ISO 10816 zone {zone}: {note}"
    )
    return anomaly_score, zone, findings


@app.post("/tasks/send")
def handle_task(req: TaskRequest) -> TaskResponse:
    data = req.message.data()
    readings: list[float] = data.get("vibration_readings_mm_s", [])
    if not readings:
        return TaskResponse(
            id=req.id,
            status=TaskStatus(state="failed", message=Message(
                role="agent", parts=[{"type": "text", "text": "No vibration_readings_mm_s provided."}]
            )),
        )

    anomaly_score, zone, findings = _score(readings)
    return TaskResponse(
        id=req.id,
        status=TaskStatus(state="completed"),
        artifacts=[{
            "name": "vibration-report",
            "parts": [
                {"type": "text", "text": findings},
                {"type": "data", "data": {
                    "vibration_anomaly_score": anomaly_score,
                    "vibration_zone": zone,
                }},
            ],
        }],
    )
