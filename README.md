# Distributed Predictive-Maintenance A2A System

A multi-process, multi-agent system where **5 separate agents**, each its
own OS process (and, via Docker, its own container on its own port),
collaborate over an **A2A-style HTTP protocol** to diagnose industrial
equipment health. No agent hardcodes another agent's address — every
lookup goes through a dedicated **Registry agent** that agents join and
renew membership in at runtime, so the fleet can scale, restart, and
recover without touching any other agent's configuration.

## Domain: predictive maintenance for industrial equipment

You submit raw sensor readings for a machine (vibration + temperature +
operating hours). The system runs them through a three-stage pipeline:

1. **Vibration Analysis Agent** scores an ISO-10816-style vibration
   severity zone from RMS velocity readings.
2. **Thermal Analysis Agent** scores an overheating-risk level from
   temperature readings.
3. **Maintenance Scheduling Agent** *only runs after 1 and 2 complete* —
   it combines both anomaly scores with the machine's operating hours
   into a priority (`routine` / `scheduled` / `urgent` / `immediate`), a
   concrete recommended action, and a re-check interval.

The **Orchestrator Agent** is the entry point: it never knows in advance
which host/port serves "vibration-analysis" — for every request it asks
the **Registry Agent** "who can do this right now?", picks a live
provider (load-balancing if there is more than one), and only then calls
that agent's own `/tasks/send` endpoint. This is a genuine 3-step
collaboration, not three isolated services glued together after the
fact: step 3's input literally doesn't exist until steps 1 and 2 finish.

## Architecture

```
                         ┌─────────────────────┐
                         │   Registry Agent     │  :8000
                         │ (dynamic discovery)  │
                         └──────────▲───────────┘
                     register/heartbeat/lookup
                ┌────────────┬──────┴──────┬────────────┐
                │            │             │            │
        ┌───────┴──────┐ ┌───┴────────┐ ┌──┴─────────┐ │
        │  Vibration   │ │  Thermal   │ │ Maintenance│ │
        │    Agent     │ │   Agent    │ │ Scheduling │ │
        │    :8002     │ │   :8003    │ │   Agent    │ │
        └───────▲──────┘ └─────▲──────┘ │   :8004    │ │
                │              │        └──────▲─────┘ │
                │  1. analyze  │  2. analyze    │ 3. recommend
                │  vibration   │  temperature   │  (needs 1+2's output)
                └──────────────┴────────┬───────┘
                                         │
                              ┌──────────┴───────────┐
                              │  Orchestrator Agent   │  :8001
                              │ (coordinates 1 → 2 → 3│
                              │  via registry lookup) │
                              └───────────▲───────────┘
                                          │ POST /diagnose
                                       (you / demo_client.py)
```

Every agent process is independent: it can be started, killed, restarted,
or scaled to multiple replicas without editing any other agent's code or
config, because discovery is entirely dynamic (see below).

## The A2A-style protocol

Each agent (registry excluded) exposes the same two endpoints, a trimmed
subset of the public [A2A protocol spec](https://google.github.io/A2A/):

- `GET /.well-known/agent.json` → an **AgentCard**: name, description,
  URL, and a list of `capabilities` (tags other agents look up) and
  `skills` (human-readable description of what it does).
- `POST /tasks/send` → accepts a `TaskRequest` (`id` + a `Message` whose
  `parts` mix free text and structured `data`) and returns a
  `TaskResponse` (`status.state` + `artifacts`, each with text/data
  parts) — see `common/models.py`.

The Orchestrator additionally exposes `POST /diagnose`, a plain-JSON
convenience wrapper around the same pipeline for easy `curl`/demo use.

## Dynamic registry lookup

The Registry agent (`agents/registry/main.py`) is a tiny in-memory
service with 5 endpoints: `POST /register`, `POST /heartbeat/{name}`,
`DELETE /agents/{name}`, `GET /agents`, `GET /lookup?capability=X`.

- Every agent registers its AgentCard on startup and **re-registers every
  5 seconds** (`common/registry_client.py`). Entries older than their TTL
  (15s) are treated as dead and silently excluded from `/lookup` and
  `/agents` — no manual deregistration required if a process just dies.
- The Orchestrator calls `/lookup?capability=vibration-analysis` (etc.)
  **on every request**, not once at startup. If you start a second
  replica of an agent, the orchestrator starts load-balancing across
  both immediately; if you kill one, it stops being selected within one
  TTL window, and any in-flight request that happens to hit a
  just-died replica transparently retries against another live one (see
  `_call_capability` in `agents/orchestrator/main.py`).
- This is demonstrated concretely in the [scale-out / failover demo](#scale-out--failover-demo)
  below.

## Repository layout

```
common/                 shared A2A models + registry client used by every agent
agents/registry/        the Registry (discovery) agent
agents/orchestrator/     the coordinating agent (entry point)
agents/vibration_agent/  specialist agent #1
agents/thermal_agent/    specialist agent #2
agents/maintenance_agent/specialist agent #3
demo_client.py          simulates 3 machines and calls the orchestrator
run_local.sh / stop_local.sh   run all 5 agents as local processes (no Docker)
Dockerfile / docker-compose.yml   run all 5 agents as separate containers
```

## Prerequisites

- Python 3.10+ (for the local, non-Docker route)
- Docker + Docker Compose v2 (for the containerized route) — check with
  `docker compose version`

## Running it — option A: Docker Compose (recommended, matches "different containers")

```bash
docker compose up -d --build
```

This builds one shared image and starts **5 separate containers**, each
on its own port, each its own process, talking to each other only over
the Docker network (agents register with `http://<service-name>:<port>`,
never `localhost`):

| Service             | Container name         | Port |
|----------------------|------------------------|------|
| registry              | pm-registry             | 8000 |
| orchestrator           | pm-orchestrator          | 8001 |
| vibration-agent        | pm-vibration-agent       | 8002 |
| thermal-agent          | pm-thermal-agent         | 8003 |
| maintenance-agent      | pm-maintenance-agent     | 8004 |

Check they're all up and registered:

```bash
docker compose ps
curl -s http://127.0.0.1:8000/agents | python3 -m json.tool
```

Run the demo:

```bash
python3 demo_client.py --registry
```

Tear down:

```bash
docker compose down
```

## Running it — option B: plain local processes (no Docker)

```bash
./run_local.sh      # creates .venv, installs deps, starts all 5 agents on 127.0.0.1
python3 demo_client.py --registry
./stop_local.sh      # stops everything
```

## Trying it by hand with curl

```bash
# 1. Discover a specialist agent's capabilities (AgentCard)
curl -s http://127.0.0.1:8002/.well-known/agent.json | python3 -m json.tool

# 2. Call a specialist agent directly via the raw A2A task endpoint
curl -s -X POST http://127.0.0.1:8002/tasks/send -H "Content-Type: application/json" -d '{
  "id": "demo-task-1",
  "message": {"role":"user","parts":[
    {"type":"text","text":"check vibration"},
    {"type":"data","data":{"vibration_readings_mm_s":[6.5,7.0,7.3]}}
  ]}
}' | python3 -m json.tool

# 3. Ask the orchestrator to run the full 3-agent pipeline
curl -s -X POST http://127.0.0.1:8001/diagnose -H "Content-Type: application/json" -d '{
  "machine_id": "COMPRESSOR-9",
  "vibration_readings_mm_s": [7.9, 8.4, 9.1, 8.8, 9.6],
  "temperature_readings_c": [96, 99, 101, 98, 100],
  "operating_hours": 21000
}' | python3 -m json.tool

# 4. See who is currently registered / who currently serves a capability
curl -s http://127.0.0.1:8000/agents | python3 -m json.tool
curl -s "http://127.0.0.1:8000/lookup?capability=thermal-analysis" | python3 -m json.tool
```

## Scale-out / failover demo

This is the clearest demonstration of *dynamic* registry lookup: add and
remove a vibration-agent replica while the system is running, with zero
config changes anywhere else.

```bash
# with docker compose already up:
docker run -d --name pm-vibration-agent-2 --network ex2_default \
  -e REGISTRY_URL=http://registry:8000 -e SELF_URL=http://pm-vibration-agent-2:8005 \
  pm-agents:latest uvicorn agents.vibration_agent.main:app --host 0.0.0.0 --port 8005

# the registry now lists two independent vibration-analysis providers:
curl -s "http://127.0.0.1:8000/lookup?capability=vibration-analysis" \
  | python3 -c "import json,sys; print([a['card']['name'] for a in json.load(sys.stdin)])"

# fire a few diagnoses — the orchestrator load-balances across both replicas
for i in 1 2 3 4; do
  curl -s -X POST http://127.0.0.1:8001/diagnose -H "Content-Type: application/json" \
    -d '{"machine_id":"LB-TEST","vibration_readings_mm_s":[2,2.1],"temperature_readings_c":[55,56]}' \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(next(t for t in d['pipeline_trace'] if 'vibration-analysis' in t))"
done

# now kill the replica abruptly (no graceful deregister) and immediately
# fire more requests — the orchestrator transparently falls back to the
# still-live replica even during the registry's TTL detection window:
docker kill pm-vibration-agent-2
curl -s -X POST http://127.0.0.1:8001/diagnose -H "Content-Type: application/json" \
  -d '{"machine_id":"LB-TEST","vibration_readings_mm_s":[2,2.1],"temperature_readings_c":[55,56]}'

docker rm -f pm-vibration-agent-2   # cleanup
```

## Design notes

- **Why HTTP/FastAPI instead of a heavier framework**: each agent's
  contract (AgentCard + `/tasks/send`) is intentionally small and
  transport-visible, so the A2A message shape is easy to inspect with
  plain `curl` — useful both for grading and for debugging.
- **TTL-based liveness, not push-based deregistration**: a graceful
  shutdown (`Ctrl-C`, `docker stop`) does call `DELETE /agents/{name}`,
  but the system does not *rely* on that — an abrupt crash is handled
  the same way, just with a bounded detection delay (`heartbeat interval
  × 3`, configurable in `common/registry_client.py`). The orchestrator
  additionally retries against any other live provider before failing,
  so a single dead replica never fails a request as long as one more
  is registered.
- **Instance identity vs. capability**: an agent's registry `name` is
  unique per *process* (`vibration-agent@host:port`), while its
  `capabilities` tag (`vibration-analysis`) is shared across all
  replicas — this is what lets multiple replicas of the same agent type
  register independently instead of overwriting each other.
