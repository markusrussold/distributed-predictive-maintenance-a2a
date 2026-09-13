#!/usr/bin/env python3
"""
Demo client for the distributed predictive-maintenance A2A system.

Deliberately stdlib-only (urllib) so it runs with a plain system `python3`
-- no virtualenv or pip install needed to try the running system.

Simulates sensor readings for a few machines (one healthy, one degrading,
one in a dangerous state) and sends each to the Orchestrator agent, which
dynamically discovers and coordinates the vibration / thermal /
maintenance-scheduling agents to produce a diagnosis.

Usage:
    python3 demo_client.py                 # run all 3 scenarios
    python3 demo_client.py --registry      # also print the live registry contents
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

ORCHESTRATOR_URL = "http://127.0.0.1:8001"
REGISTRY_URL = "http://127.0.0.1:8000"

SCENARIOS = [
    {
        "machine_id": "PUMP-101-healthy",
        "vibration_readings_mm_s": [1.1, 1.3, 1.0, 1.4, 1.2],
        "temperature_readings_c": [45, 47, 46, 48, 46],
        "operating_hours": 1200,
    },
    {
        "machine_id": "MOTOR-207-degrading",
        "vibration_readings_mm_s": [3.8, 4.1, 4.6, 4.3, 4.9],
        "temperature_readings_c": [78, 82, 80, 84, 81],
        "operating_hours": 8600,
    },
    {
        "machine_id": "COMPRESSOR-9-critical",
        "vibration_readings_mm_s": [7.9, 8.4, 9.1, 8.8, 9.6],
        "temperature_readings_c": [96, 99, 101, 98, 100],
        "operating_hours": 21000,
    },
]


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())


def _post(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", action="store_true", help="print live registry contents first")
    args = parser.parse_args()

    if args.registry:
        print("=== Live registry contents (GET /agents) ===")
        print(json.dumps(_get(f"{REGISTRY_URL}/agents"), indent=2))
        print()

    for scenario in SCENARIOS:
        print(f"=== Diagnosing {scenario['machine_id']} ===")
        status, result = _post(f"{ORCHESTRATOR_URL}/diagnose", scenario)
        if status != 200:
            print(f"ERROR {status}: {result}", file=sys.stderr)
            continue
        print("Pipeline trace (dynamic registry lookups this request made):")
        for line in result["pipeline_trace"]:
            print(f"  - {line}")
        print(f"Vibration report:   {result['vibration_report']}")
        print(f"Thermal report:     {result['thermal_report']}")
        print(f"Recommendation:     {result['maintenance_recommendation']}")
        print(f"(elapsed: {result['elapsed_seconds']}s)")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
