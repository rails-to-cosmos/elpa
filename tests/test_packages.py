import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("packages", ROOT / "bin/packages.py")
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)


class PackagesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="component test ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.profile = self.root / "profile"
        self.output = self.root / "archive"
        self.write_package("1.0")
        (self.source / "packages.json").write_text(json.dumps([
            {"main": "sample.el", "files": {"sample.el": "."}}]))
        self.git("init", "-q")
        self.commit()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.source), *args], check=True, capture_output=True)

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")

    def write_package(self, version, value="original"):
        (self.source / "sample.el").write_text(
            f';;; sample.el --- Test package -*- lexical-binding: t; -*-\n'
            f';; Version: {version}\n;; Package-Requires: ((emacs "29.1"))\n'
            f';;; Commentary:\n;; Test fixture.\n;;; Code:\n'
            f'(defconst sample-value "{value}")\n(provide \'sample)\n;;; sample.el ends here\n')

    def definitions(self):
        return packages.definitions([self.source], "emacs")

    def build(self, **kwargs):
        return packages.build(self.definitions(), self.output, **kwargs)

    def install(self, built, dev=False):
        packages.lisp("install", {"config": str(self.profile), "packages": built, "dev": dev}, "emacs")

    def snapshot(self):
        return {str(path.relative_to(self.profile)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.profile.rglob("*") if path.is_file()}

    def test_reproducible_artifact_and_read_only_repeat_and_check(self):
        built = self.build(publish=True)
        original = Path(built[0]["artifact"]).read_bytes()
        other = packages.build(self.definitions(), self.root / "local")
        self.assertEqual(Path(other[0]["artifact"]).read_bytes(), original)
        self.install(built)
        before = self.snapshot()
        self.install(built)
        packages.lisp("check", {"config": str(self.profile), "packages": built}, "emacs")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.profile / "init.el").exists())

    def test_timestamp_migration_preserves_backup_and_activates_release(self):
        self.write_package("20261001.1234")
        self.commit()
        self.install(self.build())
        old = self.profile / "elpa/sample-20261001.1234/sample.el"
        original = old.read_bytes()
        self.write_package("1.0", "release")
        self.commit()
        self.install(self.build())
        self.assertFalse(old.exists())
        backups = list((self.profile / "package-backups").glob("*/sample-20261001.1234/sample.el"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        output = subprocess.check_output([
            packages.emacs_binary("emacs"), "--batch", "-Q", "-L", str(self.profile / "elpa/sample-1.0"),
            "-l", "sample", "--eval", "(princ sample-value)"], text=True)
        self.assertEqual(output, "release")

    def test_same_version_changes_require_dev_and_published_versions_are_immutable(self):
        self.install(self.build(publish=True))
        before = self.snapshot()
        self.write_package("1.0", "changed")
        with self.assertRaisesRegex(ValueError, "commit changes"):
            self.build()
        self.commit()
        with self.assertRaisesRegex(ValueError, "bump the package version"):
            self.build(publish=True)
        built = packages.build(self.definitions(), self.root / "changed")
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(built)
        self.assertEqual(self.snapshot(), before)
        self.install(built, dev=True)
        self.assertIn('"changed"', (self.profile / "elpa/sample-1.0/sample.el").read_text())

    def test_failure_after_unpack_restores_old_package(self):
        self.install(self.build())
        old = self.profile / "elpa/sample-1.0/sample.el"
        original = old.read_bytes()
        setup = self.profile / "scripts/package-setup.el"
        setup.parent.mkdir()
        setup.write_text("(advice-add 'package-install-file :after (lambda (&rest _) (error \"injected failure\")))\n")
        self.write_package("1.1", "broken")
        self.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(self.build())
        self.assertEqual(old.read_bytes(), original)
        self.assertFalse((self.profile / "elpa/sample-1.1").exists())

    def test_dependency_order_and_cycle(self):
        client = self.source / "sample-client.el"
        client.write_text(';;; sample-client.el --- Client\n;; Version: 1.0\n'
                          ';; Package-Requires: ((sample "1.0"))\n'
                          ';;; Commentary:\n;; Fixture.\n;;; Code:\n'
                          '(provide \'sample-client)\n;;; sample-client.el ends here\n')
        (self.source / "packages.json").write_text(json.dumps([
            {"main": "sample-client.el", "files": {"sample-client.el": "."}},
            {"main": "sample.el", "files": {"sample.el": "."}}]))
        self.assertEqual([package["name"] for package in self.definitions()], ["sample", "sample-client"])
        specs = [dict(name="plugin", source="plugin", dependencies=["core"]),
                 dict(name="core", source="core", dependencies=[])]
        self.assertEqual(packages.source_order(specs), ["core", "plugin"])
        specs[1]["dependencies"] = ["plugin"]
        with self.assertRaisesRegex(ValueError, "cyclic"):
            packages.source_order(specs)

    def test_release_downgrade_requires_dev_and_check_does_not_run_autoloads(self):
        self.write_package("2.0")
        self.commit()
        built = self.build()
        self.install(built)
        marker = self.profile / "autoload-ran"
        autoloads = self.profile / "elpa/sample-2.0/sample-autoloads.el"
        with autoloads.open("a") as stream:
            stream.write(f'\n(with-temp-file {json.dumps(str(marker))} (insert "side effect"))\n')
        packages.lisp("check", {"config": str(self.profile), "packages": built}, "emacs")
        self.assertFalse(marker.exists())
        self.write_package("1.0")
        self.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(self.build())
        self.assertTrue((self.profile / "elpa/sample-2.0/sample.el").exists())

    def test_packaged_native_sources_and_flattened_org_glance(self):
        if not all((ROOT.parent / name / "packages.json").exists() for name in ("table-view", "org-glance")):
            self.skipTest("component checkouts are required for file-layout integration")
        specs = packages.definitions([ROOT.parent / "table-view", ROOT.parent / "org-glance"], "emacs")
        built = packages.build(specs, self.output, dev=True)
        for package in built:
            with tarfile.open(package["artifact"]) as archive:
                members = archive.getnames()
            if package["name"] == "table-view-native":
                self.assertTrue(any(name.endswith("native/tvx/Cargo.toml") for name in members))
                self.assertTrue(any(name.endswith("native/tvx/src/main.rs") for name in members))
                self.assertFalse(any("/target/" in name for name in members))
            if package["name"] == "org-glance":
                self.assertTrue(any(name.endswith("/org-glance-graph.el") for name in members))
                self.assertFalse(any("/src/" in name for name in members))


if __name__ == "__main__":
    unittest.main()
