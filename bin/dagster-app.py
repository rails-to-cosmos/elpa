#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#    "dagster",
# ]
# ///
"""Dagster definitions for publishing this ELPA archive."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from dagster import (
    DefaultSensorStatus,
    Definitions,
    OpExecutionContext,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    job,
    op,
    sensor,
)


ROOT = Path(__file__).resolve().parent.parent
ELPA_DIR = Path(os.environ.get("ELPA_DIR", ROOT)).expanduser()
RECIPES = ELPA_DIR / "recipes"
LS_REMOTE_TIMEOUT = 20
PULL_TIMEOUT = 120
PUBLISH_TIMEOUT = 1800

_REPO = re.compile(r':repo\s+"([^"]+)"')
_BRANCH = re.compile(r':branch\s+"([^"]+)"')
_FETCHER = re.compile(r':fetcher\s+([A-Za-z]+)')


def _success_file() -> Path:
    dagster_home = Path(os.environ.get("DAGSTER_HOME", "~/.local/share/dagster")).expanduser()
    return dagster_home / "elpa-publish-state.json"


def _recipes() -> list[tuple[str, str, str]]:
    """Return (name, GitHub repository, branch) for every GitHub recipe."""
    recipes = []
    if not RECIPES.is_dir():
        return recipes
    for path in sorted(RECIPES.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fetcher = _FETCHER.search(text)
        repo = _REPO.search(text)
        if not repo or (fetcher and fetcher.group(1) != "github"):
            continue
        branch = _BRANCH.search(text)
        recipes.append((path.name, repo.group(1), branch.group(1) if branch else ""))
    return recipes


def _head_sha(repo: str, branch: str) -> str:
    url = f"https://github.com/{repo}.git"
    ref = f"refs/heads/{branch}" if branch else "HEAD"
    result = subprocess.run(
        ["git", "ls-remote", url, ref],
        capture_output=True,
        text=True,
        timeout=LS_REMOTE_TIMEOUT,
    )
    if result.returncode:
        raise RuntimeError(f"git ls-remote {repo} {ref}: {result.stderr.strip()[:200]}")
    lines = result.stdout.strip().splitlines()
    return lines[0].split()[0] if lines else ""


def _state() -> tuple[dict[str, str], str]:
    heads = {name: _head_sha(repo, branch) for name, repo, branch in _recipes()}
    blob = "\n".join(f"{name}={heads[name]}" for name in sorted(heads))
    return heads, hashlib.sha256(blob.encode()).hexdigest()[:16]


def _last_success() -> dict:
    try:
        return json.loads(_success_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _deployment_problem() -> str | None:
    key = os.environ.get("ELPA_DEPLOY_KEY_FILE")
    if key and not Path(key).is_file():
        return f"ELPA deploy key is not a file: {key}"
    return None


def _record_success(heads: dict[str, str], fingerprint: str) -> None:
    path = _success_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "heads": heads,
                "published_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _notification_id(run_id: str) -> str:
    """Return a Glance-compatible UUID for a Dagster run identifier."""
    try:
        return str(UUID(run_id))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"elpa-publish:{run_id}"))


def _enqueue_publish_notification(
    context: OpExecutionContext,
    heads: dict[str, str],
    fingerprint: str,
) -> None:
    """Durably enqueue a successful publication for the Glance notification feed."""
    configured = os.environ.get("GLANCE_NOTIFICATION_OUTBOX")
    if not configured:
        context.log.info("GLANCE_NOTIFICATION_OUTBOX is unset; publication notification skipped")
        return

    outbox = Path(configured).expanduser()
    event_id = _notification_id(context.run_id)
    captured_at = datetime.now(UTC).isoformat()
    event = {
        "version": 1,
        "eventId": event_id,
        "capturedAt": captured_at,
        "notification": {
            "app": "elpa",
            "summary": "ELPA published successfully",
            "body": f"Published {len(heads)} recipe heads; archive fingerprint {fingerprint}.",
            "urgency": "NORMAL",
            "category": "deployment",
            "desktopEntry": "",
            "dunstId": "",
            "stackTag": "elpa-publish",
            "progress": "",
            "urls": "https://rails-to-cosmos.github.io/elpa/",
        },
    }
    temporary = outbox / f".{event_id}.{os.getpid()}.tmp"
    destination = outbox / f"{time.time_ns()}-{event_id}.json"
    try:
        outbox.mkdir(parents=True, exist_ok=True)
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(event, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
        directory = os.open(outbox, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        context.log.info("queued Glance notification %s", event_id)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        context.log.warning("publication succeeded but notification enqueue failed: %s", error)


def _run(context: OpExecutionContext, command: list[str], timeout: int) -> None:
    result = subprocess.run(
        command,
        cwd=ELPA_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    context.log.info("%s rc=%s\n%s", " ".join(command), result.returncode, (result.stdout + result.stderr)[-6000:])
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)} failed in {ELPA_DIR} (rc={result.returncode})")


@op
def publish(context: OpExecutionContext) -> None:
    """Refresh, build, commit, and push the archive."""
    if not ELPA_DIR.is_dir():
        raise RuntimeError(f"ELPA_DIR {ELPA_DIR} not found")
    missing = [tool for tool in ("make", "emacs", "eask", "git", "ssh") if not shutil.which(tool)]
    if missing:
        raise RuntimeError(f"ELPA publication needs these tools on PATH: {', '.join(missing)}")
    if problem := _deployment_problem():
        raise RuntimeError(problem)

    heads, fingerprint = _state()
    _run(context, ["git", "pull", "--ff-only", "--autostash"], PULL_TIMEOUT)
    _run(context, ["make", "publish"], PUBLISH_TIMEOUT)
    _record_success(heads, fingerprint)
    _enqueue_publish_notification(context, heads, fingerprint)


@job
def elpa_publish_job():
    publish()


@sensor(job=elpa_publish_job, minimum_interval_seconds=900, default_status=DefaultSensorStatus.RUNNING)
def elpa_sensor(context: SensorEvaluationContext):
    """Publish until the most recently successful upstream snapshot is current."""
    if problem := _deployment_problem():
        yield SkipReason(problem)
        return
    recipes = _recipes()
    if not recipes:
        yield SkipReason(f"no GitHub recipes under {RECIPES}")
        return
    try:
        heads, fingerprint = _state()
    except (RuntimeError, subprocess.SubprocessError) as error:
        yield SkipReason(f"upstream scan incomplete, retrying: {error}")
        return

    previous = _last_success()
    if previous.get("fingerprint") == fingerprint:
        yield SkipReason(f"published snapshot is current ({fingerprint})")
        return
    previous_heads = previous.get("heads", {})
    changed = sorted(name for name, sha in heads.items() if previous_heads.get(name) != sha)
    context.log.info("ELPA publication required for: %s", ", ".join(changed))
    yield RunRequest(tags={"elpa/fingerprint": fingerprint})


defs = Definitions(jobs=[elpa_publish_job], sensors=[elpa_sensor])


if __name__ == "__main__":
    heads, fingerprint = _state()
    previous = _last_success()
    print(f"ELPA_DIR={ELPA_DIR} recipes={len(heads)} fingerprint={fingerprint}")
    print(f"last_success={previous.get('fingerprint', 'none')}")
    for name, sha in heads.items():
        marker = "current" if previous.get("heads", {}).get(name) == sha else "changed"
        print(f"  {name:<26} {sha[:12]} {marker}")
