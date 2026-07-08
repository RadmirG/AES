#!/usr/bin/env python3
"""Pull Ollama models listed in AES model manifests.

The model manifests are intentionally lightweight YAML files. This script reads
`pull_groups.<group>.models` and calls Ollama's HTTP `/api/pull` endpoint for
those model tags. It has a small built-in parser for the manifest shape used in
this repository, so it does not require PyYAML.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11435"
DEFAULT_GROUP_BY_PROFILE = {
    "dev": "recommended",
    "prod": "baseline",
}


@dataclass(frozen=True)
class ModelManifest:
    default_model: str | None
    pull_groups: dict[str, list[str]]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _value_after_colon(line: str) -> str:
    return _unquote(line.split(":", 1)[1].strip())


def parse_manifest_text(text: str) -> ModelManifest:
    """Parse the AES Ollama manifest shape without external dependencies."""

    default_model: str | None = None
    pull_groups: dict[str, list[str]] = {}
    top_level: str | None = None
    current_group: str | None = None
    in_group_models = False

    for raw_line in text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue

        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        stripped = line_without_comment.strip()

        if indent == 0:
            top_level = stripped[:-1] if stripped.endswith(":") else None
            current_group = None
            in_group_models = False
            continue

        if top_level == "defaults" and indent == 2 and stripped.startswith("aes_ollama_model:"):
            default_model = _value_after_colon(stripped)
            continue

        if top_level == "models" and indent == 2 and stripped.startswith("default:"):
            default_model = default_model or _value_after_colon(stripped)
            continue

        if top_level != "pull_groups":
            continue

        if indent == 2 and stripped.endswith(":"):
            current_group = stripped[:-1].strip()
            pull_groups.setdefault(current_group, [])
            in_group_models = False
            continue

        if indent == 4:
            in_group_models = stripped == "models:"
            continue

        if indent == 6 and in_group_models and current_group and stripped.startswith("- "):
            pull_groups[current_group].append(_unquote(stripped[2:]))

    return ModelManifest(default_model=default_model, pull_groups=pull_groups)


def load_manifest(path: Path) -> ModelManifest:
    return parse_manifest_text(path.read_text(encoding="utf-8"))


def dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def select_models(
    manifest: ModelManifest,
    groups: list[str],
    include_default: bool,
    explicit_models: list[str],
) -> list[str]:
    selected: list[str] = []

    if include_default and manifest.default_model:
        selected.append(manifest.default_model)

    for group in groups:
        if group not in manifest.pull_groups:
            available = ", ".join(sorted(manifest.pull_groups)) or "<none>"
            raise ValueError(f"unknown pull group '{group}'. Available groups: {available}")
        selected.extend(manifest.pull_groups[group])

    selected.extend(explicit_models)
    return dedupe(selected)


def normalize_url(url: str) -> str:
    return url.rstrip("/")


def wait_for_ollama(base_url: str, attempts: int, delay_seconds: float) -> None:
    tags_url = f"{normalize_url(base_url)}/api/tags"
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(tags_url, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc

        print(f"Waiting for Ollama at {base_url} ({attempt}/{attempts})...")
        time.sleep(delay_seconds)

    raise RuntimeError(f"Ollama is not reachable at {base_url}: {last_error}")


def pull_model(base_url: str, model: str) -> None:
    pull_url = f"{normalize_url(base_url)}/api/pull"
    payload = json.dumps({"model": model, "stream": True}).encode("utf-8")
    request = Request(
        pull_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"Pulling {model}...")
    with urlopen(request, timeout=None) as response:
        for raw_line in response:
            line = raw_line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"  {line.decode('utf-8', errors='replace')}")
                continue

            if "error" in event:
                raise RuntimeError(f"Ollama failed to pull {model}: {event['error']}")

            status = event.get("status")
            completed = event.get("completed")
            total = event.get("total")

            if status and completed and total:
                percent = completed / total * 100
                print(f"  {status}: {percent:.1f}%")
            elif status:
                print(f"  {status}")

    print(f"Finished {model}")


def default_manifest_path(profile: str) -> Path:
    return Path(__file__).resolve().parent / f"models.{profile}.yaml"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Ollama models from an AES model manifest.")
    parser.add_argument("--profile", choices=("dev", "prod"), default="dev")
    parser.add_argument("--file", type=Path, help="Manifest file. Defaults to ollama/models.<profile>.yaml.")
    parser.add_argument(
        "--group",
        action="append",
        help="Pull group to install. Can be provided multiple times. Defaults to profile-specific group.",
    )
    parser.add_argument("--model", action="append", default=[], help="Additional model tag to pull.")
    parser.add_argument("--include-default", action="store_true", help="Also pull defaults.aes_ollama_model.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected models without pulling.")
    parser.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL),
        help=f"Ollama base URL. Defaults to OLLAMA_URL or {DEFAULT_OLLAMA_URL}.",
    )
    parser.add_argument("--wait-attempts", type=int, default=30)
    parser.add_argument("--wait-delay", type=float, default=2.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest_path = args.file or default_manifest_path(args.profile)
    groups = args.group or [DEFAULT_GROUP_BY_PROFILE[args.profile]]

    try:
        manifest = load_manifest(manifest_path)
        selected_models = select_models(
            manifest=manifest,
            groups=groups,
            include_default=args.include_default,
            explicit_models=args.model,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Manifest: {manifest_path}")
    print(f"Groups: {', '.join(groups)}")
    print("Models:")
    for model in selected_models:
        print(f"  - {model}")

    if args.dry_run:
        return 0

    try:
        wait_for_ollama(args.ollama_url, args.wait_attempts, args.wait_delay)
        for model in selected_models:
            pull_model(args.ollama_url, model)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
