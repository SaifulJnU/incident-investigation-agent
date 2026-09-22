"""Command line entry: investigate "symptom..." or --brief path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from incident_investigation_agent.agent import build_agent
from incident_investigation_agent.config import Settings


def _read_brief(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"Brief not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="investigate",
        description="Investigate an incident with a Strands agent.",
    )
    parser.add_argument(
        "symptom",
        nargs="*",
        help="What is failing, in your own words",
    )
    parser.add_argument(
        "--brief",
        type=Path,
        help="Markdown or text file with the incident brief",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    args = build_parser().parse_args(argv)
    parts: list[str] = []
    if args.brief is not None:
        parts.append(_read_brief(args.brief))
    if args.symptom:
        parts.append(" ".join(args.symptom))
    prompt = "\n\n".join(part for part in parts if part).strip()
    if not prompt:
        raise SystemExit("Pass a symptom or --brief. Example: investigate \"checkout 500s started at 14:02\"")

    settings = Settings.from_env()
    print(
        f"Provider: {settings.model_provider}"
        + (
            f" ({settings.ollama_model})"
            if settings.model_provider == "ollama"
            else f" ({settings.bedrock_model_id})"
        ),
        file=sys.stderr,
    )
    agent = build_agent(settings)
    agent(prompt)


if __name__ == "__main__":
    main()
