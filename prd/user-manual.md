# User manual

Case file can run on a laptop or in a company's own cloud. The console is the same. The model and the tools change with the environment.

## What you need

- Docker Desktop, for the console, API, worker, and Postgres.
- For a local model: [Ollama](https://ollama.com/) on the same machine, with a model that can call tools. `llama3.1` is the default.
- For production: an AWS account with Bedrock model access, and credentials the worker can use. No Ollama requirement in that mode.
- Python 3.10 or newer, only if you run the CLI or the tests outside Docker.

## Run locally

From the repository root:

```powershell
docker compose up --build
```

Open http://localhost:8080. Sign in before the case list loads.

Local compose is not the company identity provider. It accepts two development accounts:

| Username | Password | May open |
| --- | --- | --- |
| `oncall` | `oncall-local` | `checkout-api`, `payments-api` |
| `platform` | `platform-local` | every service |

A person signed in as `oncall` cannot open or read a case for another service. Investigate searches only `LOG_DIR/<service>`.

The API listens on http://localhost:8000. The compose file sets `MODEL_PROVIDER=ollama` itself, so a Bedrock setting in your shell does not leak into this stack. Ollama must be running on the host. The worker reaches it at `http://host.docker.internal:11434`.

Pull the default model once:

```powershell
ollama pull llama3.1
```

Use another pulled model by starting compose with `OLLAMA_MODEL` set to that tag.

### Walk through the sample

The image includes `examples/logs/checkout-api/api.log`. That file is the only system a checkout case can search. A person must sign in first. Local compose accepts username `oncall` with password `oncall-local`.

1. Sign in as `oncall`. On the console, choose **Use the checkout sample**. That only fills the form.
2. Choose **Open case**. The case is stored in Postgres.
3. Choose **Investigate**. The page polls until the run is completed or failed.
4. Read the incident note. A useful run quotes something that is in `api.log` and was not in the form, such as `card vault timeout`.
5. Choose **Mark mitigated** when the immediate harm has stopped, then **Mark resolved** when the case is done. Investigate stays disabled after resolved.

**Add a note** writes a fact you already know. It does not call the model. Kind chooses where it appears: timeline, hypotheses, or log lines.

### If Investigate fails

| What you see | What to do |
| --- | --- |
| Unable to locate credentials | The worker is on Bedrock. Local compose should log `provider=ollama`. Recreate the api and worker after confirming `MODEL_PROVIDER` is `ollama` in `docker-compose.yml`. |
| Connection errors to port 11434 | Start Ollama on the host. From the host, `http://localhost:11434` should answer. |
| The note describes `record_evidence` but the timeline is empty | The model searched, then wrote about the tool instead of calling it. The search still happened. A stronger local model, or a later prompt fix, is what makes the timeline fill. |
| Investigation running and it never finishes | The worker may have restarted mid-run. The run row can sit in `running`. A new investigation on that case is refused until that row is failed or completed. |

Worker logs:

```powershell
docker compose logs worker --tail 50
```

A healthy local worker contains `worker ready provider=ollama`.

## Command line, without the console

This path does not write to Postgres. It writes `.case/case.json`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

Set `MODEL_PROVIDER=ollama` in `.env`, then:

```powershell
investigate --brief examples/sample-incident.md
```

## Tests

```powershell
pytest
```

The tests cover settings, the case file, log search, the API, and the worker's save path. They do not call Ollama.

## Deploy for a company

Use the same API image and web image. Do not publish the compose password or the compose Postgres.

Set at least:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/investigations
MODEL_PROVIDER=bedrock
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
AWS_REGION=us-west-2
LOG_DIR=/var/case-file/logs
AUTH_MODE=oidc
OIDC_ISSUER=https://login.example.com
OIDC_AUDIENCE=case-file
OIDC_CLIENT_ID=case-file
```

`AUTH_MODE=dev` and `DEV_AUTH_SECRET` are for the laptop compose file only. Production leaves them unset. The identity provider must issue a signed JWT access token whose `aud` is `OIDC_AUDIENCE`. A `services` claim lists the service names that person may open. A `roles` claim of `incident-admin` may open every service. Put each service's logs in its own directory under `LOG_DIR`.

Give the worker AWS credentials with permission to invoke that Bedrock model. Enable the model in the Bedrock console. The API container runs `alembic upgrade head` before it serves traffic. Run one worker process. Put the web container behind HTTPS. Proxy `/api` to the API the way `deploy/nginx.conf` does.

To keep a local model in production, leave `MODEL_PROVIDER=ollama` and point `OLLAMA_HOST` at an Ollama server the worker can reach. That is a valid company choice. Bedrock is the supported cloud model, not a requirement of the case record.

When tool plugins land, the company will set `CONNECTORS` to the systems it uses, for example `local_logs,github` or `cloudwatch,github`. Until those plugins exist, the only search tool is the log directory in `LOG_DIR`.

## What each control does

| Control | Calls the model? | Effect |
| --- | --- | --- |
| Sign in | No | Stores a bearer token for later requests |
| Use the checkout sample | No | Fills the form in the browser |
| Open case | No | Creates the case and stores the engineer's name |
| Add a note | No | Stores a fact on the case |
| Investigate | Yes, on the worker | Queues a run. The worker calls the model and tools |
| Mark mitigated | No | Records who stopped the immediate harm |
| Mark resolved | No | Records who closed the case and blocks another investigation |

Above the case list, **All**, **Open**, **Investigating**, **Mitigated**, and **Resolved** filter that list. The choice stays in the page address.

## Stop the local stack

```powershell
docker compose down
```

`docker compose down -v` also deletes the local database volume.
