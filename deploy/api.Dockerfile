FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN useradd --create-home --uid 10001 app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY examples ./examples

RUN pip install --no-cache-dir .

USER app

EXPOSE 8000

# The server listens before migrations finish, so a database that is still
# starting does not look like a dead process. /api/live stays 200. /api/ready
# stays 503 until the case schema can be read.
CMD ["sh", "-c", "while ! alembic upgrade head; do sleep 2; done & uvicorn incident_investigation_agent.api.app:app --host 0.0.0.0 --port 8000"]
