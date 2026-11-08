# Production review

Date: 31 October 2026  
Scope: the code on `main`, the design notes in `prd/`, and a local run of the suite (83 passed).

This is a working record for the next changes. It is not a launch checklist.

## Where it stands

Case file is a solid single-company pilot. One on-call team can run it, sign in, keep a case, and get a note from logs the company already has.

It is not yet a service a company should page on. The record, the queue, and the access checks are ahead of the investigation itself. The investigation is a fixed word search plus one model call. The design notes now describe that same path.

| Area | Grade | Why |
| --- | --- | --- |
| Case record | Strong | Status history, actors, evidence kept apart from the note, one active run per case |
| Access | Strong for one company | 401 without a token, 403 for a service outside the grant, 404 for another service's case, dev login refused when `APP_ENV=prod` |
| Queue | Right shape, small ceiling | `FOR UPDATE SKIP LOCKED`, a cap of 32 waiting runs per service, a 15-second connector timeout, a 20-minute run timeout |
| Investigation | The weak part | The console does not let the model search. A word list does |
| Operate it | Thin | Live, ready, and a worker heartbeat exist. The case list returns one page. A push runs pytest. There are no metrics |
| Scale | One company, a quiet hour | A second worker can run. A busy hour of investigations will queue, then return 429 |

## What already holds

These are worth keeping. Later work should sit on them.

- The API returns before the model runs. The worker claims the run.
- A connector that does not finish is dropped for that source. The other sources are kept.
- A failed run stores the error with tokens and configured secrets replaced.
- A stopping worker releases only the runs it holds, and clears only its own heartbeat.
- Postgres is the queue. There is no second bus to operate.
- The agent cannot commit, push, restart, or roll back. A person marks mitigated or resolved.
- Each company is meant to run its own database. That choice is the right one.

## Mistakes and drift

### The console and the CLI now investigate the same way

Both call `investigate_text`. That function runs `gather`, stores every matching line, then asks `build_note_agent` for one reply with no tools. The requirements, the system design, and the command line describe that path. The tool-calling prompt is gone.

The investigation is still a fixed word list plus one model call. Closing the split did not make the search able to ask a second question. That remains the weak part, and it is item 7 below.

### A timeout and a deploy write different errors

`release_stale_runs` stores "This run passed the time limit before it finished." `release_held_runs` stores "The worker stopped before this run finished." The log line still names the reason (`timeout` or `worker-stopped`). A case that sat for 20 minutes no longer reads like a case interrupted by a deploy.

### Each worker process has its own heartbeat

`worker_beats.name` is `<hostname>-<pid>`. A second process does not overwrite the first. A process that is stopping deletes only its row. Health stays up while any row is newer than 20 seconds, and goes down when the last fresh row is gone. A crash still leaves its row until that timestamp is stale.

### The case list is one page, and a finding is a short quote

`list_incidents` returns at most 50 cases, ordered by start time and then by id. The response names the last case when another page exists. The counts above the list are still the whole grant. A matching line stored as evidence is at most 2000 characters. A longer line keeps its start and ends with `...`. One investigation can still run about ten queries on each log system, twenty lines a query, across every enabled connector. Those lines are copied onto the case, each one cut at that limit.

### The queue cap is per service

`MAX_QUEUED_RUNS` counts waiting runs for the case's service. Checkout can fill its own 32. Payments can still queue. A running or finished run does not count. A script clicking Investigate on one service cannot block the rest of the company.

### The local compose file is easy to mistake for a deploy

The file header calls it a local production shape. It publishes Postgres on port 5432 with the password `investigator`, and it mounts the Docker socket into Floci. That is acceptable on a laptop. It is a serious mistake if the file is copied to a host that other people can reach.

### Migrations and the design note disagree

`deploy/api.Dockerfile` starts uvicorn and runs `alembic upgrade head` beside it. `/api/ready` stays 503 until `incidents` can be read, which is the right probe. `prd/schema-design.md` says the image migrates before it serves. An operator who trusts the note will misread a 503 during startup.

### The suite runs on a push

`.github/workflows/tests.yml` runs `pytest` on every push and pull request, on Python 3.12. `web/package-lock.json` pins the console install. Python dependencies are still version ranges.

### The search cannot ask a second question

`gather` always searches `timeout`, `timed out`, and `500`, then at most two versions, two status codes, and three extra words from the brief. A case about saturation, a bad flag, or a certificate will not be searched for those words unless they survive that filter. The model writes the note from whatever came back. It cannot search again.

## How far it scales

Scale here means more incidents for one company, in that company's own Postgres. It does not mean many companies in one database. The design already refuses that, and it should stay refused.

| Load | What happens |
| --- | --- |
| A few investigations an hour | Fine. The queue, the skip lock, and one worker are enough |
| Several at once | One worker claims four runs. Each run fans out searches on up to eight threads. The model call is the slow part |
| A bad hour | Each service's waiting list holds 32 runs, then Investigate returns 429 for that service. Another service can still queue. Running runs do not count |
| A second worker process | Safe. Each process has its own heartbeat row and deletes only that row on stop. The claim lock was already safe |
| Large log volume | Postgres will not be the first limit. CloudWatch, Datadog, Loki, and GitHub will, because one case fires a handful of queries at each of them |
| Many companies | A separate deployment each. Do not add a tenant column to this schema |

The worker loop sleeps one second when the queue is empty. That is cheap. The expensive part is the fan-out plus one model call per run, with a 15-second cap on each connector call and a 20-minute cap on the run.

## Plugging into systems the company already runs

The idea of an MCP connector, or any existing tool server, is the right direction. It is the wrong first change.

MCP is a way to call tools that already exist: GitHub, Datadog, AWS, an internal runbook. Case file already has that idea, in a private form. `infrastructure/connectors/registry.py` maps a name to `tools_for`. `CONNECTORS` turns names on. A company adds a system by writing a Python function and a line in that map, then a second line in `gather._jobs`, because the worker does not call the Strands tools.

An MCP server attached only to the note model would not run during a search. Gather calls Python functions. An MCP connector has to be one of those functions.

Use MCP later, as one more connector, with these limits:

- Read-only tools only. The worker still must not commit, push, restart, or roll back.
- An allowlist of tool names in configuration. A company MCP server often also exposes write tools and shell tools.
- The same service grant as the other connectors. A checkout case must not call a tool that reads payments.
- The same 15-second timeout, and the same redaction before a failure is stored.
- Results come back as text the note can quote. They are not written back to the other system.

Until the console path can call a tool by name, a new system is still a short Python connector. That is smaller than an MCP client, and it matches the code that actually runs.

## Changes worth making, in order

Each one is small enough to review, and each one is visible to a person using the product or operating it.

1. Done. The console, the command line, and the design notes all say Investigate gathers with the fixed query list and then writes one note.
2. Done. A run that passed the time limit and a run released because the worker stopped store different errors on the case.
3. Done. Each worker process writes its own heartbeat row and deletes only that row on stop.
4. Done. The case list returns 50 cases at a time, and a stored finding keeps at most 2000 characters.
5. Done. The queue cap is counted per service, so one service cannot fill the waiting list for the company.
6. Done. A workflow runs `pytest` on a push, and `web/package-lock.json` pins the console install.
7. Let a run search once more. Take the first findings and one word or code they contain, run that query, and then write the note. That is the change that makes the investigation look like an investigation.
8. After step 7, add an MCP connector behind the allowlist above. Not before.

Leave Slack and PagerDuty intake until a case opened by hand is something an on-call engineer trusts. Intake onto a weak search just creates more cases.
