# incident-investigation-agent

On-call engineers lose the first minutes of an incident to the same hunt: CloudWatch, Datadog, Loki, and GitHub, then a note written by hand. This service does that hunt and leaves a case a person can act on.

The alert system still pages and assigns. This product does not replace it. It writes the investigation: what broke, the evidence, a leading cause, one alternative, and the safest next step.

## The business problem

A checkout failure at 14:02 is not a missing dashboard. The company already has logs, deploys, and an incident tool. The expensive part is a senior engineer reconstructing the timeline under pressure, then typing it again into the ticket.

Case file keeps one record:

- The case: service, severity, start time, and what the engineer already knows
- The evidence: a symptom, a log line, a timeline entry, a change, or a hypothesis
- The note: impact, leading cause, an alternative, confidence, the next checks, and the safest mitigation
- The name of the person who opened it, asked for the investigation, mitigated it, and resolved it

The agent is read-only. It searches and records. A person marks the case mitigated when the immediate harm has stopped, and resolved when the service is normal. A resolved case cannot be investigated again.

## What changes for the on-call engineer

Before: open four systems, search for `timeout` and `500`, find the last deploy, write the note, then decide.

After: open the case and choose Investigate. The API returns immediately. A worker asks the model, the model calls only the systems this company turned on, and the note lands on the case. The engineer checks that a quoted line is real, does the fix in the real platform, then marks mitigated or resolved.

Locally the search is a log folder and the model is any Ollama model that can call tools. In production the model is Amazon Bedrock and the search is CloudWatch, Datadog, Loki, and GitHub. The console stays the same. `CONNECTORS=cloudwatch,github` turns the unused systems off.

## Security

Production login is the company identity provider. The API accepts a signed JWT and checks issuer, audience, and expiry. It does not keep a second password list. `AUTH_MODE=dev` exists only for the local demo.

Authorization is the service on the case:

- No token: the API answers 401
- Opening a case for a service the token does not grant: 403
- Reading another service's case: 404, so a caller cannot learn that the case exists
- Lists and counts stay inside the granted services
- The role `incident-admin`, or a service grant of `*`, can open every service

A checkout case cannot read payments logs, another CloudWatch group, another Datadog service, or another GitHub repository. Connector queries reject path traversal and unexpected characters. API keys and tokens stay in the environment. They are not written into the case.

The worker cannot create a commit, push a log line, restart a service, or roll back a deploy. A missing connector setting is reported on that tool. The model is told to say a fact is unknown when it is not in the case or in a tool result.

## What a team can measure

Every investigation is a row. A team can report on the work without reading a chat scroll.

| Record | What it shows |
| --- | --- |
| Time to a note | The run moves from queued to running to completed or failed, with a start and a finish |
| Who acted | Name and login for open, investigate, mitigate, and resolve |
| Scope | The service on the case, and that the search stayed inside it |
| Evidence | The facts that were kept, separate from the prose note |
| Outcome | Open, investigating, mitigated, or resolved, with counts on the case list |

Severity is `sev1` through `sev4`. It is stored on the case and sent to the model. Paging stays in the existing alert tool.

## Run it

Docker Desktop is enough for the local case. The API applies database migrations on startup.

```bash
docker compose up --build
```

Open http://localhost:8080. Sign in with username `oncall` and password `oncall-local` (checkout and payments) or `platform` and `platform-local` (every service). Choose "Use the checkout sample", open the case, and choose Investigate.

Production replaces the local login and the sample log folder. Set these, and change only the values that are still placeholders:

```
APP_ENV=prod
MODEL_PROVIDER=bedrock
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
AWS_REGION=us-west-2
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/investigations
AUTH_MODE=oidc
OIDC_ISSUER=https://login.example.com
OIDC_AUDIENCE=case-file
OIDC_CLIENT_ID=case-file
CLOUDWATCH_LOG_GROUP_PREFIX=/aws/ecs/
DATADOG_SITE=datadoghq.com
DATADOG_API_KEY=replace-me
DATADOG_APP_KEY=replace-me
LOKI_URL=https://loki.example.com
LOKI_TOKEN=replace-me
GITHUB_API_URL=https://api.github.com
GITHUB_TOKEN=replace-me
GITHUB_ORG=replace-me
```

CloudWatch uses the worker's AWS role and needs `logs:FilterLogEvents`. A case for `checkout-api` reads that prefix plus the service name. Do not set `DEV_AUTH_SECRET` in production. Drop a system the company does not use and set `CONNECTORS` to the rest.

```bash
pytest
```
