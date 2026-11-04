#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#    "dagster",
# ]
# ///
"""Dagster definitions for publishing this ELPA archive."""

import hashlib
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from dagster import (
    DefaultSensorStatus,
    Definitions,
    Failure,
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
TERMINATE_GRACE = 5
GIT_RETRY_DELAYS = (5, 15, 45)

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
    if not lines:
        raise RuntimeError(f"upstream branch not found: {repo} {ref}")
    return lines[0].split()[0]


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


def _publish_timeout() -> int:
    value = os.environ.get("ELPA_PUBLISH_TIMEOUT_SECONDS", str(PUBLISH_TIMEOUT))
    try:
        seconds = int(value)
    except ValueError:
        seconds = 0
    if seconds <= 0:
        raise ValueError("ELPA_PUBLISH_TIMEOUT_SECONDS must be a positive integer")
    return seconds


def _stop_process_group(process: subprocess.Popen) -> None:
    def send(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    send(signal.SIGTERM)
    try:
        process.wait(timeout=TERMINATE_GRACE)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # Children may outlive a make process that exits on SIGTERM.
        send(signal.SIGKILL)
        process.wait()


def _command_problem(output: str) -> tuple[str, str, bool]:
    text = output.lower()
    if "published contents changed" in text or "contents changed; bump" in text:
        return ("A published package version has different contents.",
                "Bump that package's version before publishing again.", False)
    if "permission denied (publickey)" in text:
        return ("Git SSH authentication was rejected.",
                "If retries keep failing, check the configured deploy key and GitHub service status.", True)
    if "commit_refs" in text:
        return ("GitHub could not update the remote branch (commit_refs).",
                "The archive commit is retained locally for another push attempt.", True)
    if any(term in text for term in ("non-fast-forward", "fetch first", "not possible to fast-forward")):
        return ("The local and remote branches have diverged.",
                "Reconcile the branches before retrying; publication will not force-push.", False)
    if any(term in text for term in ("could not resolve", "connection timed out", "connection reset",
                                    "connection refused", "remote end hung up", "early eof",
                                    "connection closed", "unable to access", "internal server error",
                                    "error: 500", "error: 502", "error: 503", "error: 504")):
        return ("The Git remote could not complete the request.",
                "Retry after the connection or remote service recovers.", True)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return ("\n".join(lines[-5:])[-1000:] or "The command returned no diagnostic output.",
            "Inspect the full command log for details.", False)


class CommandError(RuntimeError):
    def __init__(self, command, path, output, returncode, expired=None):
        self.command, self.path = command, path
        self.phase, self.attempts = "publication", 1
        if expired:
            self.reason = f"Command timed out after {expired.timeout}s."
            self.hint = "Its process group was stopped. Check the log before increasing the timeout."
            self.retryable = True
        else:
            self.reason, self.hint, self.retryable = _command_problem(output)
        super().__init__(f"{self.reason}\n{self.hint}\nCommand: {' '.join(command)} "
                         f"(rc={returncode})\nFull output: {path}")


def _run(context: OpExecutionContext, command: list[str], timeout: int) -> None:
    log_dir = _success_file().parent / "elpa-publish-logs" / _notification_id(context.run_id)
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    expired = None
    with tempfile.NamedTemporaryFile(dir=log_dir, prefix="command-", suffix=".log", delete=False) as log:
        path = Path(log.name)
        context.log.info("Running %s (timeout %ss); full output: %s", " ".join(command), timeout, path)
        process = subprocess.Popen(
            command, cwd=ELPA_DIR, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            expired = error
            _stop_process_group(process)
        except BaseException:
            _stop_process_group(process)
            raise
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 6000))
        tail = stream.read().decode("utf-8", errors="replace")
    elapsed = time.monotonic() - started
    summary = (f"{' '.join(command)} in {ELPA_DIR}: "
               + (f"timed out after {timeout}s" if expired else f"rc={process.returncode}")
               + f" (elapsed {elapsed:.1f}s). Full output: {path}\n{tail}")
    context.log.info("%s", summary)
    if expired or process.returncode:
        raise CommandError(command, path, tail, process.returncode, expired) from expired


def _git_retry(context, args: list[str], phase: str) -> None:
    for attempt in range(len(GIT_RETRY_DELAYS) + 1):
        try:
            _run(context, ["git", *args], PULL_TIMEOUT)
            return
        except CommandError as error:
            error.phase, error.attempts = phase, attempt + 1
            if not error.retryable or attempt == len(GIT_RETRY_DELAYS):
                raise
            delay = GIT_RETRY_DELAYS[attempt]
            context.log.warning("%s: %s Retrying in %ss (attempt %s/%s). Full output: %s",
                                phase, error.reason, delay, attempt + 2,
                                len(GIT_RETRY_DELAYS) + 1, error.path)
            time.sleep(delay)


def _git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ELPA_DIR, capture_output=True,
                            text=True, timeout=PULL_TIMEOUT)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    result = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant],
                            cwd=ELPA_DIR, capture_output=True, text=True, timeout=PULL_TIMEOUT)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Cannot verify archive commit ancestry: {result.stderr.strip()}")
    return result.returncode == 0


def _write_pending(path: Path, pending: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        stream.write(json.dumps(pending, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _pending_file() -> Path:
    return Path(_git_output("rev-parse", "--absolute-git-dir")) / "elpa-publish-pending.json"


def _finish_pending(context, path: Path, pending: dict) -> None:
    remote, branch, commit = pending["remote"], pending["branch"], pending["commit"]
    _git_retry(context, ["fetch", remote, branch], "Check remote archive")
    if not _is_ancestor(commit, "FETCH_HEAD"):
        if not _is_ancestor("FETCH_HEAD", commit):
            raise RuntimeError("Archive publication is pending, but the remote branch has diverged. "
                               "Reconcile it with the saved commit " + commit + "; no force-push was attempted.")
        _git_retry(context, ["push", remote, f"{commit}:refs/heads/{branch}"], "Push archive")
        _git_retry(context, ["fetch", remote, branch], "Verify published archive")
        if not _is_ancestor(commit, "FETCH_HEAD"):
            raise RuntimeError("The remote has not confirmed the archive commit. Publication remains pending.")
    _record_success(pending["heads"], pending["fingerprint"])
    path.unlink()
    _enqueue_publish_notification(context, pending["heads"], pending["fingerprint"])


def _publish_archive(context, timeout: int) -> None:
    pending_path = _pending_file()
    git_dir = pending_path.parent
    with (git_dir / "elpa-publish.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another ELPA publisher is active; retry after it finishes.") from None
        if pending_path.exists():
            try:
                pending = json.loads(pending_path.read_text())
                if (not isinstance(pending, dict)
                        or not all(key in pending for key in ("remote", "branch", "commit", "heads", "fingerprint"))
                        or not isinstance(pending["heads"], dict)
                        or not all(isinstance(pending[key], str) and pending[key]
                                   for key in ("remote", "branch", "commit", "fingerprint"))
                        or not re.fullmatch(r"[0-9a-f]{40,64}", pending["commit"])):
                    raise ValueError("missing fields")
            except (ValueError, TypeError) as error:
                raise RuntimeError(f"Cannot read pending publication at {pending_path}; preserve it for recovery.") from error
            context.log.info("Resuming pending archive commit %s without rebuilding", pending["commit"])
            _finish_pending(context, pending_path, pending)
            return
        if _git_output("diff", "--cached", "--name-only"):
            raise RuntimeError("The ELPA checkout has staged changes. Commit or unstage them before publication.")
        _git_retry(context, ["pull", "--ff-only", "--autostash"], "Refresh archive checkout")
        heads, fingerprint = _state()
        tracking = _git_output("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        remote, separator, branch = tracking.partition("/")
        if not separator:
            raise RuntimeError("ELPA publication requires an upstream branch.")
        try:
            _run(context, ["make", "prepare-publish"], timeout)
        except CommandError as error:
            error.phase = "Build archive"
            raise
        pending = {"heads": heads, "fingerprint": fingerprint, "remote": remote,
                   "branch": branch, "commit": _git_output("rev-parse", "HEAD")}
        _write_pending(pending_path, pending)
        _finish_pending(context, pending_path, pending)


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

    timeout = _publish_timeout()
    try:
        _publish_archive(context, timeout)
    except CommandError as error:
        raise Failure(
            description=f"{error.phase} failed after {error.attempts} attempt(s).\n\n{error.reason}\n{error.hint}",
            metadata={"phase": error.phase, "attempts": error.attempts,
                      "command": " ".join(error.command), "full_log": str(error.path),
                      "retryable": error.retryable},
            allow_retries=False,
        ) from None
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise Failure(description=str(error), allow_retries=False) from None


@job
def elpa_publish_job():
    publish()


@sensor(job=elpa_publish_job, minimum_interval_seconds=900, default_status=DefaultSensorStatus.RUNNING)
def elpa_sensor(context: SensorEvaluationContext):
    """Publish until the most recently successful upstream snapshot is current."""
    if problem := _deployment_problem():
        yield SkipReason(problem)
        return
    if ELPA_DIR.is_dir() and _pending_file().exists():
        yield RunRequest(tags={"elpa/recovery": "pending-push"})
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
