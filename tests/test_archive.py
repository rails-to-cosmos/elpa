import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("packages", ROOT / "bin/packages.py")
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)


@unittest.skipUnless(os.environ.get("PACKAGE_BUILD_DIR"), "set PACKAGE_BUILD_DIR for archive integration")
class ArchiveTest(unittest.TestCase):
    def test_publication_uses_local_artifact_and_refuses_changed_release(self):
        with tempfile.TemporaryDirectory(prefix="elpa-archive-") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            main = source / "sample.el"
            main.write_text(';;; sample.el --- Test package -*- lexical-binding: t; -*-\n'
                            ';; Version: 1.0\n;; Package-Requires: ((emacs "29.1"))\n'
                            ';;; Commentary:\n;; Fixture.\n;;; Code:\n'
                            '(defconst sample-value 1)\n(provide \'sample)\n;;; sample.el ends here\n')
            (source / "packages.json").write_text(json.dumps([
                {"main": "sample.el", "files": {"sample.el": "."}}]))
            git = shutil.which("git")

            def command(*args):
                subprocess.run([git, "-C", str(source), *args], check=True, capture_output=True)

            def commit():
                command("add", ".")
                command("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")

            command("init", "-q", "--initial-branch=main")
            commit()
            archive = root / "archive"
            archive.mkdir()
            for name in ("build.el", "package-tools.el"):
                shutil.copy(ROOT / name, archive / name)
            shutil.copytree(ROOT / "bin", archive / "bin")
            (archive / "recipes").mkdir()
            (archive / "recipes/sample").write_text(
                '(sample :fetcher github :repo "test/sample" :branch "main" :make-targets ("package"))\n')
            (root / "bin").mkdir()
            wrapper = root / "bin/git"
            wrapper.write_text('#!/usr/bin/env python3\nimport os, sys\n'
                               f'os.execv({git!r}, [{git!r}] + '
                               f'[{str(source)!r} if x == "https://github.com/test/sample.git" else x for x in sys.argv[1:]])\n')
            wrapper.chmod(0o755)
            env = {**os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"]}
            invocation = [packages.emacs_binary("emacs"), "--batch", "-Q", "-L", os.environ["PACKAGE_BUILD_DIR"]]
            if os.environ.get("COMPAT_DIR"):
                invocation += ["-L", os.environ["COMPAT_DIR"]]
            invocation += ["-l", str(archive / "build.el")]
            for _ in range(2):
                result = subprocess.run(invocation, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr[-6000:])
            local = packages.build(packages.definitions([source], "emacs"), root / "local")
            published = archive / "docs/sample-1.0.tar"
            self.assertEqual(published.read_bytes(), Path(local[0]["artifact"]).read_bytes())
            self.assertIn("sample", (archive / "docs/archive-contents").read_text())
            original = published.read_bytes()
            main.write_text(main.read_text().replace("sample-value 1", "sample-value 2"))
            commit()
            result = subprocess.run(invocation, env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(published.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
