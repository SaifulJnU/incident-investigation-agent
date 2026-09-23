"""List recent commits for the case service. Does not create or change anything on GitHub."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from strands import tool

from incident_investigation_agent.core.config import Settings
from incident_investigation_agent.infrastructure.connectors.http import ConnectorError, request_json
from incident_investigation_agent.infrastructure.connectors.mapping import mapped_target, require_service

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_API = re.compile(r"^https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/api/v3)?$")


def tools_for(settings: Settings, service: str | None):
    @tool
    def list_recent_commits(limit: int = 10) -> str:
        """List recent commits for this case's service repository. Read-only.

        Args:
            limit: Maximum commits to return
        """
        return list_commits(settings, service, limit)

    return [list_recent_commits]


def list_commits(settings: Settings, service: str | None, limit: int = 10) -> str:
    scoped = require_service(service)
    if scoped is None:
        return "No service is set on this case, so GitHub was not queried."
    if not settings.github_token:
        return "GitHub is not configured. Set GITHUB_TOKEN."
    if not _API.fullmatch(settings.github_api_url):
        return "GITHUB_API_URL must be an https API host, such as https://api.github.com."
    repo = _repo(settings, scoped)
    if repo is None:
        return "GitHub has no repository for this service. Set GITHUB_ORG or GITHUB_REPOS."
    capped = _limit(limit)
    since = (datetime.now(timezone.utc) - timedelta(hours=settings.github_lookback_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    query = urlencode({"since": since, "per_page": capped})
    url = f"{settings.github_api_url}/repos/{repo}/commits?{query}"
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        body = request_json(url, headers=headers)
    except ConnectorError as exc:
        return f"GitHub commit list failed for {repo}: {exc}"
    if not isinstance(body, list) or not body:
        return (
            f"No commits on {repo} in the last {settings.github_lookback_hours} hours."
        )
    lines = []
    for commit in body[:capped]:
        if not isinstance(commit, dict):
            continue
        sha = str(commit.get("sha") or "")[:7]
        detail = commit.get("commit") if isinstance(commit.get("commit"), dict) else {}
        message = str(detail.get("message") or "").splitlines()[0][:200]
        when = ""
        author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
        if isinstance(author, dict):
            when = str(author.get("date") or "")
        if sha or message:
            lines.append(f"{repo} {sha} {when} {message}".strip())
    if not lines:
        return f"GitHub returned no commit text for {repo}."
    return "\n".join(lines)


def _repo(settings: Settings, service: str) -> str | None:
    repo = mapped_target(settings.github_repos, service)
    if not repo and settings.github_org:
        repo = f"{settings.github_org}/{service}"
    if not repo or not _REPO.fullmatch(repo):
        return None
    return repo


def _limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, 20)
