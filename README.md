# incident-investigation-agent

A Python incident investigation agent built with the [Strands Agents SDK](https://strandsagents.com/). The same agent runs on Amazon Bedrock in production and on any local Ollama model while you develop.

## Plan

The agent takes an incident brief, searches the logs you point it at, and writes a case file as it works. Model choice is configuration. Tools and the investigation prompt do not change between environments.

```
brief or symptom
        |
        v
  Strands Agent  ---- tools: record_evidence, list_evidence, search_logs
        |
        +-- production: Amazon Bedrock (IAM or standard AWS credentials)
        +-- local:      Ollama at localhost, any pulled model
        |
        v
  incident note + .case/case.json
```

Investigation order baked into the system prompt:

1. Restate symptom, start time, and blast radius.
2. Record a timeline of deploys, config changes, and error spikes.
3. Search logs before naming a cause.
4. Give one leading hypothesis and one alternative, each tied to recorded evidence.
5. Recommend the next checks and the safest immediate mitigation.
6. Close with impact, leading cause, confidence, and open questions.

What is scaffolded now:

- Provider switch (`MODEL_PROVIDER=bedrock` or `ollama`)
- Bedrock model id and region from the environment
- Ollama host and model id from the environment, so any model you have pulled can be used
- A case file under `.case/`
- Log search over a local directory (`examples/logs` by default)
- A sample checkout incident and a matching log

What comes next, as separate adapters behind the same tools:

- CloudWatch Logs, metrics, and traces
- Deploy and change history
- Ticket or paging intake

## Layout

```
src/incident_investigation_agent/
  config.py     environment settings
  models.py     BedrockModel or OllamaModel
  agent.py      Strands Agent
  tools.py      case notes and log search tools
  logs.py       local log search
  prompts.py    investigation instructions
  case.py       .case/case.json
  __main__.py   CLI
examples/       sample brief and logs
tests/          settings and case file
```

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
