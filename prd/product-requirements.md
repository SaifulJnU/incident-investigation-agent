# Product requirements

Product: Case file  
Repository: incident-investigation-agent  
Status: working local slice, with a pluggable target  
Audience: the team building it, and a company that wants to run it

## 1. Problem

When production breaks, an on-call engineer reconstructs what happened from logs, deploys, metrics, and chat. That work is the same shape in every company. The tools are not. One team uses CloudWatch, another Datadog, another a folder of log files and GitHub.

Case file is an investigation record plus an agent. The record is the same for every company. The agent reaches the company's own systems through tools the company plugs in. The model that reasons over those tools is also a plug: a local Ollama model while developing, Amazon Bedrock when the company runs it in production.

## 2. Product intent

Any company can run one Case file deployment for its own incidents.

- The case (timeline, evidence, hypotheses, note, status) does not change between companies.
- Tools are plugins. A company enables the systems it actually has.
- The model is a plugin. Local and production can differ.
- The agent is read-only toward the company's systems. A person marks mitigation and resolution. Writes and remediation stay behind a later approval gate.
- A company does not have to send incidents to a vendor. The stack runs on their machine or in their cloud.

## 3. Users

| Person | What they do in the product |
| --- | --- |
| On-call engineer | Opens a case, adds what they already know, clicks Investigate, reads the note, marks mitigated or resolved |
| Incident lead | Reads the same case during the bridge and corrects the record |
| Platform owner | Installs the stack, chooses the model, and enables tool plugins for that company |
| Auditor | Reads each status change: who moved the case, from which status, and when. The case also stores the latest opener, mitigator, and resolver |

## 4. What exists today

This is the slice that runs.

- Web console at port 8080: sign in, open a case, list cases, add a note, investigate, mark mitigated, mark resolved.
- Sign-in. Production checks an OIDC access token. Local compose uses two development accounts.
- A person may open and read cases only for services on their token. `incident-admin` may open every service.
- API and a worker. Investigate returns immediately. The worker searches, then one model call writes the note.
- Postgres stores cases, evidence, and investigation runs, including who opened the case and who requested the run.
- The worker searches the connectors selected by `APP_ENV` and `CONNECTORS`. It stores each matching line itself. The model does not call tools.
- `APP_ENV=local` searches `LOG_DIR/<service>`. In Docker the checkout sample is `examples/logs/checkout-api`.
- `APP_ENV=prod` searches CloudWatch, Datadog, Loki, and GitHub. `CONNECTORS` can name a shorter list.
- Model plug with two options: Ollama (local compose) and Amazon Bedrock (when `MODEL_PROVIDER=bedrock` and AWS credentials exist).
- CLI that investigates a prompt and writes `.case/case.json`, separate from the console database.

## 5. What a company will plug in

Built for logs and GitHub commits. Slack and PagerDuty intake are still later. The contract below is what each plugin does.

A tool plugin:

- Has a name a company can enable or disable (`local_logs`, `cloudwatch`, `datadog`, `github`, `grafana`).
- Exposes a search function the worker calls. A Strands tool wrapper may sit on that same function. Investigate does not ask the model to call it.
- Is read-only in the first version of that plugin.
- Returns text the note can quote. It does not write back to the external system.
- Declares the settings it needs (region, API key, log group) and fails with a clear message when those settings are missing.
- Can be omitted. A company with only GitHub and local files does not configure Datadog.

A model plugin:

- Is selected with `MODEL_PROVIDER`.
- Today: `ollama`, `bedrock`.
- Later, the same agent code can take any other provider Strands already supports, behind the same setting.
- The rest of the product does not mention the provider.

Intake plugins, later: a person can open a case by hand today. Slack and PagerDuty would open the same kind of case from an alert. They are not required to use the product.

## 6. Functional requirements

### 6.1 Case

- A person must present a bearer token. Without one, case routes return 401.
- A person can open a case with a title, service, severity (`sev1` to `sev4`), start time, and a description of what happened, when that service is in their grant.
- Opening a case for another service returns 403. Reading another service's case returns 404.
- A case has a status: open, investigating, mitigated, resolved.
- Only a person moves a case to mitigated or resolved.
- Investigate is refused when a run is already queued or running, and when the case is resolved.
- Investigate is refused with 429 when the number of queued runs is already `MAX_QUEUED_RUNS` (32 unless the environment says otherwise). A running or finished run does not count.

### 6.2 Investigation

- Investigate stores a run and returns without waiting for the model. The waiting list holds at most `MAX_QUEUED_RUNS` runs.
- The worker sends the model the title, service, severity, start time, description, and evidence already on the case.
- Before that call, the worker searches every enabled connector for `timeout`, `timed out`, and `500`, then at most two versions, two status codes, and three other words from the brief. GitHub is asked for recent commits once, not once per word.
- The worker stores each matching line as evidence. The model does not choose the searches and does not call tools.
- The worker stores the model's final text as the incident note.
- The console shows the latest run: provider, model name, status, note, and error if the run failed.

### 6.3 Evidence

- A person can add a note of kind symptom, log, timeline, change, or hypothesis.
- The worker adds the same kinds for each matching line it keeps. A log line is `log`. A GitHub commit is `change`.
- The console groups them: timeline (symptom, timeline, change), hypotheses, log lines.

### 6.4 Tools that must be pluggable

| Plugin | First capability | Status |
| --- | --- | --- |
| Local logs | Search text files in a configured directory | Built |
| Case file | Record and list evidence on the case | Built |
| CloudWatch Logs | Search a log group by time and filter | Built. `APP_ENV=prod` |
| Datadog | Search logs. A metric query is later | Built for logs. `APP_ENV=prod` |
| Grafana or Loki | Search logs for the service label | Built. `APP_ENV=prod` |
| GitHub | List commits for the service in the lookback window | Built. `APP_ENV=prod` |
| Slack | Post nothing in v1. Later, open a case from a channel | Planned |
| PagerDuty | Open a case from an incident | Planned |

### 6.5 Models

| Provider | When a company uses it | Status |
| --- | --- | --- |
| Ollama | Local install. Any pulled model. `llama3.1` is the default local model | Built |
| Amazon Bedrock | Production, with the company's AWS credentials and an enabled model | Built, not used by local compose |
| Other Strands providers | A company that standardizes on another API | Planned as another `MODEL_PROVIDER` value |

## 7. Non-functional requirements

- A company keeps case data in its own Postgres. There is no shared multi-tenant service in this repository.
- Secrets (Datadog keys, GitHub tokens, AWS keys) come from the environment or the platform's secret store. They are not written into the case.
- Local Docker must not inherit a host `MODEL_PROVIDER=bedrock` or `APP_ENV=prod` by accident. The compose file sets Ollama and `APP_ENV=local`.
- The compose database password is for the local stack only. Production replaces `DATABASE_URL`.
- An investigation that cannot authenticate to a plugin fails that run with the underlying error. It does not invent a cause.
- `/api/live` returns 200 when the API process is up. It does not check the database. `/api/ready` returns 503 until the case schema can be read. A process waiting on the database is not the same as a process that is down. `/api/health` still reports the database and the worker.
- The console works in a current desktop browser and on a narrow laptop width.

## 8. Success for the next test pass

A tester can:

1. Open the console and create the sample checkout case without a cloud account.
2. Click Investigate and see a completed run that used Ollama, not Bedrock.
3. See a note that quotes a line present in `examples/logs/checkout-api/api.log` and absent from the title.
4. See that same line stored as evidence by the worker, without the model calling a tool.
5. Mark the case mitigated, then resolved, and see Investigate disabled.
6. Point the same stack at Bedrock by changing the provider and supplying AWS credentials, without changing the console.

## 9. Out of scope for the current build

- Automatic remediation, rollbacks, and pull requests.
- Multi-tenant SaaS hosting for many companies in one database.
- Replacing a company's paging tool.
- Training a model on a company's incidents.

## 10. Open decisions

- How a company maps a service name is configuration: `CLOUDWATCH_LOG_GROUP_PREFIX`, `CLOUDWATCH_LOG_GROUPS`, `DATADOG_SERVICE_TAG`, `LOKI_LABEL`, `GITHUB_ORG`, and `GITHUB_REPOS`.
- How long a run may stay in `running` before the worker marks it failed.
