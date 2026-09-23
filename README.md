# incident-investigation-agent

A Python incident investigation agent built with the [Strands Agents SDK](https://strandsagents.com/). The same agent runs on Amazon Bedrock in production and on any local Ollama model while you develop.

## Plan

An investigation is a case file, not a chat transcript. That is how Resolve, Cleric, Traversal, and incident.io present the work: a timeline, the evidence behind it, hypotheses, and a note a person can act on. The agent is read-only. It searches and records. A person marks the mitigation.

```
browser (case file)
        |
        v
  API  ---- Postgres: cases, evidence, investigation runs
        |
        v
  worker ---- Strands agent ---- local logs today
        |                         CloudWatch, Grafana, Datadog, GitHub later
        +-- production: Amazon Bedrock
        +-- local:      any Ollama model
```

The console is the case. The CLI still writes a local `.case/case.json` when you want a single run without Docker.

Investigation order baked into the system prompt:

1. Restate symptom, start time, and blast radius.
2. Record a timeline of deploys, config changes, and error spikes.
3. Search logs before naming a cause.
4. Give one leading hypothesis and one alternative, each tied to recorded evidence.
5. Recommend the next checks and the safest immediate mitigation.
6. Close with impact, leading cause, confidence, and open questions.

Running now:

- Docker Compose: Postgres, API, worker, and the web console
- Cases, evidence, and investigation runs in Postgres
- A worker that runs the Strands agent without holding the HTTP request
- Bedrock in production, any pulled Ollama model locally
- Local log search (`examples/logs` in the image)
- The case-file console: open a case, timeline, hypotheses, incident note

Still to build:

- Read-only connectors for CloudWatch, Grafana or Prometheus, Datadog, and GitHub deploys
- Hypothesis confidence and a ruled-out state
- A full audit log of every status change
- Slack and PagerDuty intake
- Postmortem export
- An approval gate before any remediation write
- Request metrics and a time limit on a run
- CI that publishes the images

## Layout

The Python package is split the way a German production service usually is: the case rules do not import FastAPI or SQLAlchemy, HTTP only calls the repository, and the model and log files sit behind adapters.

```
src/incident_investigation_agent/
  domain/            evidence and the store port
  services/          agent, investigation run, incident note
  repositories/      Postgres reads and writes
  db/                engine, sessions, table definitions
  infrastructure/    Bedrock or Ollama, local logs, on-disk case file
  api/               FastAPI routes, request bodies, session dependency
  core/              settings and process logging
  cli.py             investigate command
  worker.py          process that claims queued runs
web/                 case-file console
deploy/              API image, web image, nginx
examples/            sample brief and logs
```

## Console

Docker Desktop is enough. The API image runs migrations on startup. Ollama on the host is reached at `host.docker.internal:11434`. Set `MODEL_PROVIDER=bedrock` in the shell before `docker compose up` when you want Bedrock instead. The database password in `docker-compose.yml` is for this local stack only.

```bash
docker compose up --build
```

Open http://localhost:8080. The API is on port 8000. Local compose signs you in with a username and password, not the company identity provider. Use username `oncall` and password `oncall-local` for checkout and payments, or `platform` and `platform-local` for every service. Then use "Use the checkout sample", open the case, and Investigate. The sample log for that service is `examples/logs/checkout-api/api.log`. An investigation only searches the directory for the case's service.

Production sets `AUTH_MODE=oidc` with `OIDC_ISSUER`, `OIDC_AUDIENCE`, and `OIDC_CLIENT_ID`. The access token must be a signed JWT. A `services` claim lists the services that person may open. The role `incident-admin` may open every service. Do not set `DEV_AUTH_SECRET` in production.

## Setup

## Setup

Python 3.10 or newer.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

macOS or Linux:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### Local Ollama

Install [Ollama](https://ollama.com/), start it, and pull any model that can call tools. `llama3.1` is the default. Set `OLLAMA_MODEL` to a different tag if you want another one.

```bash
ollama pull llama3.1
```

`.env`:

```
MODEL_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

### Production Amazon Bedrock

Leave `MODEL_PROVIDER` unset, or set it to `bedrock`. The SDK uses the normal AWS credential chain: environment variables, shared config, or an IAM role on EC2, ECS, or Lambda. Enable the model in the Bedrock console.

```
MODEL_PROVIDER=bedrock
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
AWS_REGION=us-west-2
```

## Run

```bash
investigate "Checkout 500s started at 14:02 UTC after the payments-api deploy"
investigate --brief examples/sample-incident.md
```

Or:

```bash
python -m incident_investigation_agent --brief examples/sample-incident.md
```

The agent prints which provider it is using, then the investigation. Evidence it records lands in `.case/case.json`. That directory is gitignored.

## Test

```bash
pytest
```
