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
| Auditor, later | Reads who changed a case. Not built yet |

## 4. What exists today

This is the slice that runs.

- Web console at port 8080: open a case, list cases, add a note, investigate, mark mitigated, mark resolved.
- API and a worker. Investigate returns immediately and the worker runs the agent.
- Postgres stores cases, evidence, and investigation runs.
- Strands agent with exactly three tools: `search_logs`, `record_evidence`, `list_evidence`.
- `search_logs` reads text files in a directory. In Docker that directory is `examples/logs`.
- Model plug with two options: Ollama (local compose) and Amazon Bedrock (when `MODEL_PROVIDER=bedrock` and AWS credentials exist).
- CLI that investigates a prompt and writes `.case/case.json`, separate from the console database.

## 5. What a company will plug in

Not built yet. The requirements below are the contract so the current three tools can grow into a set.

A tool plugin:

- Has a name a company can enable or disable (`local_logs`, `cloudwatch`, `datadog`, `github`, `grafana`).
- Exposes one or more Strands tools.
- Is read-only in the first version of that plugin.
- Returns text the model can quote. It does not write back to the external system.
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

- A person can open a case with a title, service, severity (`sev1` to `sev4`), start time, and a description of what happened.
- A case has a status: open, investigating, mitigated, resolved.
- Only a person moves a case to mitigated or resolved.
- Investigate is refused when a run is already queued or running, and when the case is resolved.

### 6.2 Investigation

- Investigate stores a run and returns without waiting for the model.
- The worker sends the model the title, service, severity, start time, description, and evidence already on the case.
- The model may call enabled tools. Tool results go back to the model.
- The worker stores the model's final text as the incident note.
- The console shows the latest run: provider, model name, status, note, and error if the run failed.

### 6.3 Evidence

- A person can add a note of kind symptom, log, timeline, change, or hypothesis.
- The agent can add the same kinds through `record_evidence`.
- The console groups them: timeline (symptom, timeline, change), hypotheses, log lines.

### 6.4 Tools that must be pluggable

| Plugin | First capability | Status |
| --- | --- | --- |
| Local logs | Search text files in a configured directory | Built |
| Case file | Record and list evidence on the case | Built |
| CloudWatch Logs | Search a log group by time and filter | Planned |
| Datadog | Search logs, and later a metric query | Planned |
| Grafana or Loki | Search logs with that company's query language | Planned |
| GitHub | List commits and deploys for the service in the incident window | Planned |
| Slack | Post nothing in v1. Later, open a case from a channel | Planned |
| PagerDuty | Open a case from an incident | Planned |

### 6.5 Models

| Provider | When a company uses it | Status |
| --- | --- | --- |
| Ollama | Local install. Any pulled model. `llama3.1` is the default because it can call tools | Built |
| Amazon Bedrock | Production, with the company's AWS credentials and an enabled model | Built, not used by local compose |
| Other Strands providers | A company that standardizes on another API | Planned as another `MODEL_PROVIDER` value |

## 7. Non-functional requirements

- A company keeps case data in its own Postgres. There is no shared multi-tenant service in this repository.
- Secrets (Datadog keys, GitHub tokens, AWS keys) come from the environment or the platform's secret store. They are not written into the case.
- Local Docker must not inherit a host `MODEL_PROVIDER=bedrock` by accident. The compose file sets Ollama.
- The compose database password is for the local stack only. Production replaces `DATABASE_URL`.
- An investigation that cannot authenticate to a plugin fails that run with the underlying error. It does not invent a cause.
- The console works in a current desktop browser and on a narrow laptop width.

## 8. Success for the next test pass

A tester can:

1. Open the console and create the sample checkout case without a cloud account.
2. Click Investigate and see a completed run that used Ollama, not Bedrock.
3. See a note that quotes a line present in `examples/logs/api.log` and absent from the title.
4. See that line also stored as evidence when the model calls `record_evidence`.
5. Mark the case mitigated, then resolved, and see Investigate disabled.
6. Point the same stack at Bedrock by changing the provider and supplying AWS credentials, without changing the console.

Item 4 is not reliable on `llama3.1` today. The model sometimes describes the tool call instead of making it. That is a test failure to fix, not the intended product behavior.

## 9. Out of scope for the current build

- Automatic remediation, rollbacks, and pull requests.
- Multi-tenant SaaS hosting for many companies in one database.
- Replacing a company's paging tool.
- Training a model on a company's incidents.

## 10. Open decisions

- Whether CloudWatch or Datadog is the first external plugin. Pick the system the first pilot company already pays for.
- How a company maps a service name on the case to a log group, a Datadog service tag, or a GitHub repository. That mapping is configuration, not a hard-coded name.
- How long a run may stay in `running` before the worker marks it failed.
