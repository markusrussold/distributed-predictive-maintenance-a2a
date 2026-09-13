# Single shared image for every agent in the fleet. Which agent a
# container runs is decided purely by the `command:` it's started with
# (see docker-compose.yml) -- this keeps one build serving 5 services.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY agents ./agents

EXPOSE 8000 8001 8002 8003 8004

CMD ["uvicorn", "agents.registry.main:app", "--host", "0.0.0.0", "--port", "8000"]
