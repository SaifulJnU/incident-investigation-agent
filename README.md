# Case file

On-call engineers lose the first minutes of an incident to the same hunt: CloudWatch, Datadog, Loki, and GitHub, then a note written by hand. Case file does that hunt and leaves a record a person can act on. The alert system still pages. This service writes the investigation.

## What you can measure

| Measure | What the product records |
| --- | --- |
| Time to a note | Each run moves from queued to running to completed or failed, with a start and a finish |
| Who acted | Name and login for open, investigate, mitigate, and resolve |
| Scope | One service per case. A checkout case cannot read payments logs |
| Outcome | Open, investigating, mitigated, or resolved, with counts on the case list |
| Evidence | Symptoms, log lines, timeline entries, changes, and hypotheses, kept apart from the prose note |

Severity is `sev1` through `sev4`. Paging stays in the existing alert tool.

## What the build shows

| | |
| --- | --- |
| Search | 4 production systems (CloudWatch, Datadog, Loki, GitHub), or a local log folder |
| Model | Amazon Bedrock in production, Ollama locally. The console does not change |
| Login | Company identity provider in production (OIDC, PKCE). A local username and password exist only for the demo |
| Access | No token is 401. A service the token does not grant is 403. Another service's case is 404 |
| Work split | The API returns immediately. A worker asks the model and writes the note |
| Safety | The worker searches and records. It cannot commit, push, restart, or roll back |
| Tests | 39 automated tests for access, connectors, the API, and the worker |
| Stack | Python, FastAPI, Postgres, Alembic, React |

## Run it

Docker Desktop is enough. The API applies database migrations on startup.

```bash
docker compose up --build
```

Open http://localhost:8080.

| Username | Password | Services |
| --- | --- | --- |
| `oncall` | `oncall-local` | checkout and payments |
| `platform` | `platform-local` | every service |

Choose "Use the checkout sample", open the case, and choose Investigate.

```bash
pytest
```

Production sets `APP_ENV=prod`, `MODEL_PROVIDER=bedrock`, and `AUTH_MODE=oidc`, and turns on only the systems this company uses with `CONNECTORS`.
