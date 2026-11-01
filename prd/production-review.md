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
| Queue | Right shape, small ceiling | `FOR UPDATE SKIP LOCKED`, a cap of 32 waiting runs, a 15-second connector timeout, a 20-minute run timeout |
| Investigation | The weak part | The console does not let the model search. A word list does |
| Operate it | Thin | Live, ready, and a worker heartbeat exist. There is no CI workflow, no metrics, and no page size on the case list |
| Scale | One company, a quiet hour | A second worker is not safe. A busy hour of investigations will queue, then return 429 |

## What already holds

These are worth keeping. Later work should sit on them.

- The API returns before the model runs. The worker claims the run.
- A connector that does not finish is dropped for that source. The other sources are kept.
- A failed run stores the error with tokens and configured secrets replaced.
- A stopping worker releases only the runs it holds, and clears its heartbeat.
- Postgres is the queue. There is no second bus to operate.
- The agent cannot commit, push, restart, or roll back. A person marks mitigated or resolved.
- Each company is meant to run its own database. That choice is the right one.

## Mistakes and drift

### The console and the CLI now investigate the same way

Both call `investigate_text`. That function runs `gather`, stores every matching line, then asks `build_note_agent` for one reply with no tools. The requirements, the system design, and the command line describe that path. The tool-calling prompt is gone.

The investigation is still a fixed word list plus one model call. Closing the split did not make the search able to ask a second question. That remains the weak part, and it is item 7 below.

### A timeout and a deploy write the same error

`release_stale_runs` and `release_held_runs` both store "The worker stopped before this run finished." The reason (`timeout` or `worker-stopped`) is only a log line. A case that sat for 20 minutes looks the same as a case interrupted by a deploy.

### The heartbeat is one shared row

`worker_beats` is keyed by the name `worker`. A second process overwrites that row. A process that is stopping deletes it. Health can report the worker down while another worker is alive, or up while the only worker has exited. The stop path is careful about which runs it releases. The beat is not careful about which process it represents.

### The case list and the evidence rows have no bound

`list_incidents` returns every case for the grant, ordered by start time. A year of cases is one response. Each search hit is stored as evidence with no length cap. One investigation can run about ten queries on each log system, twenty lines a query, across every enabled connector. Those lines are copied onto the case.

### The queue cap is global

`MAX_QUEUED_RUNS` counts every waiting run in the deployment. One service, or a script clicking Investigate, can fill the cap. Every other service then gets 429 until a worker starts one of those runs.

### The local compose file is easy to mistake for a deploy

The file header calls it a local production shape. It publishes Postgres on port 5432 with the password `investigator`, and it mounts the Docker socket into Floci. That is acceptable on a laptop. It is a serious mistake if the file is copied to a host that other people can reach.

### Migrations and the design note disagree

`deploy/api.Dockerfile` starts uvicorn and runs `alembic upgrade head` beside it. `/api/ready` stays 503 until `incidents` can be read, which is the right probe. `prd/schema-design.md` says the image migrates before it serves. An operator who trusts the note will misread a 503 during startup.

### Nothing runs the suite on a push

`pytest` from the project virtualenv passed, 83 tests, on 31 October 2026. The repository has no GitHub Actions workflow, so `main` does not run that suite. Python dependencies are version ranges. `web/package-lock.json` is still untracked, so the console install is not pinned.

### The search cannot ask a second question

`gather` always searches `timeout`, `timed out`, and `500`, then at most two versions, two status codes, and three extra words from the brief. A case about saturation, a bad flag, or a certificate will not be searched for those words unless they survive that filter. The model writes the note from whatever came back. It cannot search again.

## How far it scales

Scale here means more incidents for one company, in that company's own Postgres. It does not mean many companies in one database. The design already refuses that, and it should stay refused.

| Load | What happens |
| --- | --- |
| A few investigations an hour | Fine. The queue, the skip lock, and one worker are enough |
| Several at once | One worker claims four runs. Each run fans out searches on up to eight threads. The model call is the slow part |
| A bad hour | The waiting list holds 32 runs, then Investigate returns 429. Running runs do not count, so four running plus 32 waiting is the pile-up |
| A second worker process | Unsafe until the heartbeat row is per process. The claim lock itself is safe |
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
2. Store the real reason when a run is abandoned. A timeout and a stopped worker should read differently on the case.
3. Give each worker process its own heartbeat name, and delete only that row on stop. Then a second worker is a real scale step.
4. Cap the case list with a page size, and cap how much text one finding can store.
5. Count the queue cap per service, or reserve part of the 32 for other services, so one service cannot block the company.
6. Add a workflow that runs `pytest` on a push. Commit `web/package-lock.json` so the console install is pinned.
7. Let a run search once more. Take the first findings and one word or code they contain, run that query, and then write the note. That is the change that makes the investigation look like an investigation.
8. After step 7, add an MCP connector behind the allowlist above. Not before.

Leave Slack and PagerDuty intake until a case opened by hand is something an on-call engineer trusts. Intake onto a weak search just creates more cases.
