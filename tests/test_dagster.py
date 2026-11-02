import importlib.util
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
        self.assertIn("published contents changed", str(failure.exception))
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
                patch.object(app, "_state", return_value=({}, "fingerprint")), \
                patch.object(app, "_run", side_effect=[None, RuntimeError("build failed")]) as run, \
                patch.object(app, "_record_success") as success, \
                patch.object(app, "_enqueue_publish_notification") as notify:
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                app.publish(self.context)
            self.assertEqual(run.call_args.args[2], 3600)
            success.assert_not_called()
            notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
