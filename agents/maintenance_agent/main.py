"""
Maintenance Scheduling Agent
----------------------------
Capability: "maintenance-scheduling"

Takes the combined vibration + thermal anomaly scores for a machine
(produced by the other two specialist agents) plus its operating hours,
and turns them into a concrete maintenance recommendation. This is the
step that only makes sense *after* the other two agents have run, which
is what makes the orchestrator's pipeline a real collaboration rather
than three independent calls.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from common.agent_app import make_app
from common.models import AgentCard, Message, Skill, TaskRequest, TaskResponse, TaskStatus

SELF_URL = os.environ.get("SELF_URL", "http://127.0.0.1:8004")
# Unique per replica; see the matching comment in vibration_agent/main.py.
INSTANCE_NAME = f"maintenance-agent@{urlparse(SELF_URL).netloc}"

CARD = AgentCard(
    name=INSTANCE_NAME,
    description="Turns combined condition-monitoring scores into a maintenance recommendation.",
    url=SELF_URL,
    capabilities=["maintenance-scheduling"],
    skills=[
        Skill(
            id="schedule-maintenance",
            name="Recommend maintenance action",
            description="Combines vibration + thermal anomaly scores and operating hours into a priority, action, and re-check interval.",
            tags=["maintenance-scheduling", "decision-support"],
        )
    ],
)

app, registry = make_app(CARD)


def _recommend(vibration_score: float, thermal_score: float, operating_hours: float) -> dict:
    # Weighted combination: sustained heat is treated as slightly more urgent
    # than vibration alone, since it more often precedes rapid failure.
    overall_risk = round(0.45 * vibration_score + 0.55 * thermal_score, 1)

    # Wear factor nudges risk up for heavily-run equipment.
    wear_bonus = min(15.0, operating_hours / 1000.0)
    overall_risk = min(100.0, round(overall_risk + wear_bonus, 1))

    if overall_risk < 25:
        priority = "routine"
        action = "No action needed; continue normal operation."
        next_check_days = 90
    elif overall_risk < 50:
        priority = "scheduled"
        action = "Add to the next scheduled maintenance window for inspection and lubrication."
        next_check_days = 30
    elif overall_risk < 75:
        priority = "urgent"
        action = "Schedule maintenance within 48 hours; inspect bearings, cooling, and alignment."
        next_check_days = 2
    else:
        priority = "immediate"
        action = "Stop equipment and inspect immediately — risk of imminent failure."
        next_check_days = 0

    return {
        "overall_risk_score": overall_risk,
        "priority": priority,
        "recommended_action": action,
        "next_check_in_days": next_check_days,
    }


@app.post("/tasks/send")
def handle_task(req: TaskRequest) -> TaskResponse:
    data = req.message.data()
    try:
        vibration_score = float(data["vibration_anomaly_score"])
        thermal_score = float(data["thermal_anomaly_score"])
    except (KeyError, TypeError, ValueError):
        return TaskResponse(
            id=req.id,
            status=TaskStatus(state="failed", message=Message(
                role="agent",
                parts=[{"type": "text", "text": "Requires vibration_anomaly_score and thermal_anomaly_score."}],
            )),
        )
    operating_hours = float(data.get("operating_hours", 0))

    result = _recommend(vibration_score, thermal_score, operating_hours)
    summary = (
        f"overall_risk={result['overall_risk_score']}, priority={result['priority']}, "
        f"next check in {result['next_check_in_days']} day(s): {result['recommended_action']}"
    )
    return TaskResponse(
        id=req.id,
        status=TaskStatus(state="completed"),
        artifacts=[{
            "name": "maintenance-recommendation",
            "parts": [
                {"type": "text", "text": summary},
                {"type": "data", "data": result},
            ],
        }],
    )
