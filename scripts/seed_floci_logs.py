"""Load a production-style checkout error log into Floci CloudWatch."""

import time

from incident_investigation_agent.infrastructure.connectors.cloudwatch import logs_client

ENDPOINT = "http://floci:4566"
GROUPS = {
    "/aws/ecs/checkout-api": [
        "checkout-api INFO request POST /checkout status=200 latency_ms=140",
        'checkout-api ERROR upstream payments-api status=500 body="card vault timeout"',
        "checkout-api ERROR request POST /checkout status=500 latency_ms=3010",
    ],
    "/aws/ecs/payments-api": [
        "payments-api INFO deploy version=1.42.0",
        "payments-api ERROR vault connection timed out host=vault.internal:8443",
    ],
}


def main() -> None:
    client = logs_client("us-east-1", ENDPOINT)
    now = int(time.time() * 1000)
    for group, messages in GROUPS.items():
        _ensure_group(client, group)
        token = _stream_token(client, group)
        events = [
            {"timestamp": now + index, "message": message}
            for index, message in enumerate(messages)
        ]
        kwargs = {"logGroupName": group, "logStreamName": "api", "logEvents": events}
        if token:
            kwargs["sequenceToken"] = token
        client.put_log_events(**kwargs)
        print(f"wrote {len(messages)} lines to {group}")


def _ensure_group(client, group: str) -> None:
    try:
        client.create_log_group(logGroupName=group)
    except Exception as exc:
        if exc.__class__.__name__ != "ResourceAlreadyExistsException":
            raise
    try:
        client.create_log_stream(logGroupName=group, logStreamName="api")
    except Exception as exc:
        if exc.__class__.__name__ != "ResourceAlreadyExistsException":
            raise


def _stream_token(client, group: str) -> str:
    page = client.describe_log_streams(logGroupName=group, logStreamNamePrefix="api")
    streams = page.get("logStreams") or []
    if not streams:
        return ""
    return str(streams[0].get("uploadSequenceToken") or "")


if __name__ == "__main__":
    main()
