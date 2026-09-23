# Scope and use cases

Case file is for a company that already has incidents and already has some record of them: logs, deploys, metrics, tickets. The product does not collect that telemetry. It investigates through whatever plugins that company turns on, and it keeps the case.

## In scope

- One company, one deployment, their data in their database.
- A person opens a case and asks for an investigation.
- The agent searches only through enabled, read-only tools.
- The result is a note on the case, plus evidence the agent recorded.
- A person decides mitigation and resolution.
- Local run with Ollama and a log directory.
- Production run with Bedrock, or with Ollama if that is the company's choice.
- More tools later, each optional: CloudWatch, Datadog, Grafana or Loki, GitHub, then Slack and PagerDuty as ways to open a case.

## Out of scope

- A vendor-hosted multi-tenant service that holds many companies' incidents.
- The agent restarting services, reverting deploys, or opening pull requests on its own.
- Replacing Datadog, CloudWatch, PagerDuty, or Slack.
- Guaranteeing a root cause. The note has to say when the evidence is missing.

## Use cases

### 1. Errors after a deploy

Harbor and Co. runs a checkout API. At 14:02 UTC, payments-api 1.42.0 goes out. Checkout starts returning HTTP 500. The on-call engineer opens a case with the service, the time, and that summary. They click Investigate.

With the built-in log plugin, the agent searches `api.log` and can find:

```text
checkout-api ERROR upstream payments-api status=500 body="card vault timeout"
payments-api ERROR vault connection timed out host=vault.internal:8443
```

The note should say the leading explanation is a vault timeout after that deploy, name an alternative, and recommend the next check. The engineer marks mitigated if they roll back, and resolved when the error rate is back.

This is the case in the local sample. It works without Datadog or AWS.

### 2. A company that lives in CloudWatch

Same case shape. The platform owner enables a CloudWatch plugin and maps `checkout-api` to a log group. Investigate searches that group for the incident window instead of a folder. The console does not change. The company never enables the Datadog plugin.

### 3. A company that lives in Datadog

Same case shape. The Datadog plugin searches logs, and later a metric, with that account's API key. GitHub can be enabled beside it so the agent can see commits to the service between the start time and now. CloudWatch stays off.

### 4. Deploy correlation

The symptom is a latency jump, not an error. The useful plugin is GitHub or the company's deploy history: what shipped to this service in the last hour. The log plugin still answers whether the new version is in the error lines. Neither plugin is mandatory. A company with only logs still gets a case and a note. The note should say the deploy list is unknown if that plugin is off.

### 5. Someone already knows a fact

During the incident, a person adds a note: "database failover was not announced." Investigate includes that note in the next prompt. The agent must not contradict recorded evidence without saying so.

### 6. The same product in two companies

Company A enables `local_logs` and Ollama. Company B enables `cloudwatch` plus `github` and Bedrock. Both use the same images. Neither company sees the other's cases, because each runs its own Postgres.

## Actors in every use case

The on-call engineer opens and closes the case. The agent only reads and writes the case file. The platform owner chooses plugins and the model before the incident, not during the note.

## Acceptance for a use case

- The note names a cause only when a tool result or the case text supports it.
- A line quoted from logs can be found in the system that plugin searched.
- Turning a plugin off does not break open, investigate, or resolve. The agent has fewer tools and must say what it could not check.
