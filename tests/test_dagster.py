import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch


def decorator(function=None, **kwargs):
    return function if function is not None else lambda function: function


dagster = types.ModuleType("dagster")
dagster.DefaultSensorStatus = types.SimpleNamespace(RUNNING="RUNNING")
for name in ("Definitions", "OpExecutionContext", "RunRequest", "SensorEvaluationContext", "SkipReason"):
    setattr(dagster, name, Mock())
dagster.op = dagster.job = dagster.sensor = decorator


class Failure(Exception):
    def __init__(self, description, metadata=None, allow_retries=True):
        super().__init__(description)
        self.metadata = metadata


dagster.Failure = Failure
spec = importlib.util.spec_from_file_location("elpa_dagster", Path(__file__).resolve().parents[1] / "bin/dagster-app.py")
app = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"dagster": dagster}):
    spec.loader.exec_module(app)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="elpa-command-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = patch.dict(os.environ, {"DAGSTER_HOME": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cwd = patch.object(app, "ELPA_DIR", self.root)
        self.cwd.start()
        self.addCleanup(self.cwd.stop)
        self.context = types.SimpleNamespace(run_id="test-run", log=Mock())

    def command(self, program):
        return [sys.executable, "-c", program]

    def logs(self):
        return list(self.root.glob("elpa-publish-logs/*/*.log"))

    def test_failure_keeps_full_ordered_output_and_exposes_cause(self):
        script = self.root / "fail.py"
        script.write_text(
            "import sys; print('first output', flush=True); "
            "print('x' * 8000, flush=True); "
            "print('published contents changed; bump the package version', file=sys.stderr); sys.exit(2)"
        )
        with self.assertRaisesRegex(RuntimeError, "rc=2") as failure:
            app._run(self.context, [sys.executable, str(script)], 5)
        self.assertIn("published package version has different contents", str(failure.exception))
        self.assertIn(str(self.logs()[0]), str(failure.exception))
        output = self.logs()[0].read_text()
        self.assertTrue(output.startswith("first output\n"))
        self.assertGreater(len(output), 8000)
        self.assertTrue(output.endswith("published contents changed; bump the package version\n"))

    def test_success_keeps_output_and_reaps_process(self):
        app._run(self.context, self.command("print('published successfully')"), 5)
        self.assertEqual(self.logs()[0].read_text(), "published successfully\n")

    @unittest.skipUnless(sys.platform == "linux", "process state inspection uses procfs")
    def test_timeout_kills_signal_resistant_child_even_after_parent_exits(self):
        child = ("import os, signal, time; from pathlib import Path; "
                 "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 "Path('child.pid').write_text(str(os.getpid())); time.sleep(60)")
        parent = ("import subprocess, sys, time; from pathlib import Path; "
                  f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                  "time.sleep(60)")
        try:
            with patch.object(app, "TERMINATE_GRACE", 0.1):
                with self.assertRaisesRegex(RuntimeError, "timed out after") as failure:
                    app._run(self.context, self.command(parent), 0.5)
            self.assertIsInstance(failure.exception.__cause__, subprocess.TimeoutExpired)
            pid = int((self.root / "child.pid").read_text())
            stat = Path(f"/proc/{pid}/stat")
            for _ in range(50):
                if not stat.exists() or stat.read_text().split(") ", 1)[1].startswith("Z"):
                    break
                time.sleep(0.01)
            else:
                self.fail("timed-out child process is still running")
        finally:
            pid_file = self.root / "child.pid"
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_interruption_stops_command_group_and_propagates(self):
        process = Mock()
        process.wait.side_effect = KeyboardInterrupt
        with patch.object(app.subprocess, "Popen", return_value=process), \
                patch.object(app, "_stop_process_group") as stop:
            with self.assertRaises(KeyboardInterrupt):
                app._run(self.context, ["make", "publish"], 1)
            stop.assert_called_once_with(process)

    def test_timeout_configuration(self):
        for value in ("0", "-1", "invalid", "1.5"):
            with patch.dict(os.environ, ELPA_PUBLISH_TIMEOUT_SECONDS=value):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    app._publish_timeout()
        with patch.dict(os.environ, ELPA_PUBLISH_TIMEOUT_SECONDS="3600"):
            self.assertEqual(app._publish_timeout(), 3600)

    def test_failed_publication_never_records_success_or_notifies(self):
        with patch.object(app.shutil, "which", return_value="tool"), \
                patch.object(app, "_deployment_problem", return_value=None), \
                patch.object(app, "_publish_timeout", return_value=3600), \
                patch.object(app, "_publish_archive", side_effect=RuntimeError("build failed")) as run, \
                patch.object(app, "_record_success") as success, \
                patch.object(app, "_enqueue_publish_notification") as notify:
            with self.assertRaisesRegex(Failure, "build failed"):
                app.publish(self.context)
            self.assertEqual(run.call_args.args[1], 3600)
            success.assert_not_called()
            notify.assert_not_called()

    def test_transient_git_failures_retry_with_backoff(self):
        error = app.CommandError(["git", "push"], self.root / "push.log",
                                 "remote: fatal error in commit_refs", 1)
        with patch.object(app, "_run", side_effect=[error, error, None]) as run, \
                patch.object(app.time, "sleep") as sleep:
            app._git_retry(self.context, ["push"], "Push archive")
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 15])

    def test_permanent_failures_are_not_retried(self):
        error = app.CommandError(["git", "push"], self.root / "push.log", "non-fast-forward", 1)
        with patch.object(app, "_run", side_effect=error) as run, \
                patch.object(app.time, "sleep") as sleep:
            with self.assertRaisesRegex(app.CommandError, "diverged"):
                app._git_retry(self.context, ["push"], "Push archive")
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_auth_failure_has_concise_dagster_description_and_log_metadata(self):
        error = app.CommandError(["git", "pull"], self.root / "pull.log",
                                 "git@github.com: Permission denied (publickey).\n" + "noise\n" * 100, 128)
        with patch.object(app.shutil, "which", return_value="tool"), \
                patch.object(app, "_deployment_problem", return_value=None), \
                patch.object(app, "_publish_archive", side_effect=error):
            with self.assertRaises(Failure) as caught:
                app.publish(self.context)
        self.assertIn("authentication was rejected", str(caught.exception))
        self.assertNotIn("noise", str(caught.exception))
        self.assertEqual(caught.exception.metadata["full_log"], str(self.root / "pull.log"))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        CommandTests.setUp(self)
        self.repo = self.root / "checkout"
        self.remote = self.root / "remote.git"
        self.repo.mkdir()
        self.cwd.stop()
        self.cwd = patch.object(app, "ELPA_DIR", self.repo)
        self.cwd.start()
        self.addCleanup(self.cwd.stop)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Publication test")
        self.git("config", "user.email", "publish@example.test")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/archive").write_text("old")
        self.git("add", "docs")
        self.git("commit", "-m", "initial")
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        self.builds = 0
        self.original_run = app._run

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, stderr=subprocess.DEVNULL,
                                       text=True).strip()

    def build_or_run(self, context, command, timeout):
        if command == ["make", "prepare-publish"]:
            self.builds += 1
            (self.repo / "docs/archive").write_text("new")
            self.git("add", "docs")
            self.git("commit", "-m", "Update ELPA archive")
        else:
            self.original_run(context, command, timeout)

    def test_failed_push_resumes_exact_commit_without_rebuilding(self):
        def fail_push(context, command, timeout):
            if command[:2] == ["git", "push"]:
                raise app.CommandError(command, self.root / "push.log",
                                       "remote: fatal error in commit_refs", 1)
            self.build_or_run(context, command, timeout)

        with patch.object(app, "_state", return_value=({"package": "abc"}, "snapshot")), \
                patch.object(app, "_run", side_effect=fail_push), \
                patch.object(app, "GIT_RETRY_DELAYS", ()):
            with self.assertRaises(app.CommandError):
                app._publish_archive(self.context, 30)
        pending_path = app._pending_file()
        pending = json.loads(pending_path.read_text())
        self.assertEqual(self.git("rev-parse", "HEAD"), pending["commit"])
        self.assertFalse(app._success_file().exists())
        with patch.object(app, "_run", side_effect=self.build_or_run), \
                patch.object(app, "_state", side_effect=AssertionError("pending recovery rescanned sources")):
            app._publish_archive(self.context, 30)
        self.assertEqual(self.builds, 1)
        self.assertFalse(pending_path.exists())
        self.assertEqual(app._last_success()["fingerprint"], "snapshot")
        self.assertEqual(self.git("ls-remote", "origin", "main").split()[0], pending["commit"])

    def test_accepted_push_with_lost_response_is_verified_on_retry(self):
        def lose_reply(context, command, timeout):
            self.build_or_run(context, command, timeout)
            if command[:2] == ["git", "push"]:
                raise app.CommandError(command, self.root / "push.log", "connection reset", 128)

        with patch.object(app, "_state", return_value=({}, "snapshot")), \
                patch.object(app, "_run", side_effect=lose_reply), \
                patch.object(app, "GIT_RETRY_DELAYS", ()):
            with self.assertRaises(app.CommandError):
                app._publish_archive(self.context, 30)
        with patch.object(app, "_run", wraps=self.original_run) as run:
            app._publish_archive(self.context, 30)
        self.assertFalse(any(call.args[1][:2] == ["git", "push"] for call in run.call_args_list))
        self.assertEqual(self.builds, 1)
        self.assertEqual(app._last_success()["fingerprint"], "snapshot")

    def test_staged_changes_are_preserved(self):
        (self.repo / "notes").write_text("user work")
        self.git("add", "notes")
        with self.assertRaisesRegex(RuntimeError, "staged changes"), \
                patch.object(app, "_run") as run:
            app._publish_archive(self.context, 30)
        run.assert_not_called()
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes")

    def test_checkout_lock_prevents_overlapping_publishers(self):
        with (self.repo / ".git/elpa-publish.lock").open("a") as lock:
            app.fcntl.flock(lock, app.fcntl.LOCK_EX | app.fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "Another ELPA publisher"), \
                    patch.object(app, "_run") as run:
                app._publish_archive(self.context, 30)
            run.assert_not_called()

    def test_prepare_publish_commits_only_archive_files(self):
        (self.repo / "notes").write_text("user work")
        self.git("add", "notes")
        (self.repo / "docs/archive").write_text("new")
        override = self.root / "build.mk"
        override.write_text("upgrade:\n\t@true\n")
        subprocess.run(["make", "-f", str(app.ROOT / "Makefile"), "-f", str(override), "prepare-publish"],
                       cwd=self.repo, check=True, capture_output=True)
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), "docs/archive")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes")

    def test_divergence_keeps_pending_commit_and_never_pushes(self):
        base = self.git("rev-parse", "HEAD")
        self.build_or_run(self.context, ["make", "prepare-publish"], 30)
        pending = {"commit": self.git("rev-parse", "HEAD"), "heads": {}, "fingerprint": "snapshot",
                   "remote": "origin", "branch": "main"}
        path = app._pending_file()
        app._write_pending(path, pending)
        peer = self.root / "peer"
        subprocess.run(["git", "clone", "--branch", "main", str(self.remote), str(peer)],
                       check=True, capture_output=True)
        for args in (("config", "user.name", "Peer"), ("config", "user.email", "peer@example.test"),
                     ("commit", "--allow-empty", "-m", "remote change"), ("push", "origin", "main")):
            subprocess.run(["git", *args], cwd=peer, check=True, capture_output=True)
        with patch.object(app, "_run", wraps=self.original_run) as run:
            with self.assertRaisesRegex(RuntimeError, "diverged"):
                app._publish_archive(self.context, 30)
        self.assertFalse(any(call.args[1][:2] == ["git", "push"] for call in run.call_args_list))
        self.assertTrue(path.exists())
        self.assertFalse(app._success_file().exists())
        self.assertNotEqual(self.git("ls-remote", "origin", "main").split()[0], base)

    def test_sensor_recovers_pending_push_without_scanning_upstream(self):
        app._write_pending(app._pending_file(), {"commit": self.git("rev-parse", "HEAD")})
        with patch.object(app, "_deployment_problem", return_value=None), \
                patch.object(app, "_state", side_effect=AssertionError("unnecessary scan")), \
                patch.object(app, "RunRequest") as request:
            list(app.elpa_sensor(self.context))
        request.assert_called_once_with(tags={"elpa/recovery": "pending-push"})

    def test_build_failure_does_not_create_pending_or_success(self):
        with patch.object(app, "_state", return_value=({}, "snapshot")), \
                patch.object(app, "_git_retry"), \
                patch.object(app, "_run", side_effect=app.CommandError(
                    ["make", "prepare-publish"], self.root / "build.log",
                    "published contents changed; bump the package version", 2)):
            with self.assertRaises(app.CommandError):
                app._publish_archive(self.context, 30)
        self.assertFalse(app._pending_file().exists())
        self.assertFalse(app._success_file().exists())


if __name__ == "__main__":
    unittest.main()
