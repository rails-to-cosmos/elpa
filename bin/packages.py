#!/usr/bin/env python3
"""Build and install component packages from their declared release metadata."""

import argparse
import glob
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def emacs_binary(value):
    candidates = [value] if value != "emacs" else [
        value, str(Path.home() / "Applications/Emacs.app/Contents/MacOS/Emacs"),
        "/Applications/Emacs.app/Contents/MacOS/Emacs"]
    for candidate in candidates:
        if found := shutil.which(candidate):
            return found
    raise ValueError(f"Emacs executable not found: {value}")


def lisp(action, request, emacs):
    expression = (f'(condition-case err (rce-command "{action}") '
                  '(error (message "%s" (error-message-string err)) (kill-emacs 1)))')
    result = subprocess.run([emacs_binary(emacs), "--batch", "-Q", "-l", str(ROOT / "package-tools.el"),
                             "--eval", expression], check=True, stdout=subprocess.PIPE, text=True,
                            env={**os.environ, "RCE_REQUEST": json.dumps(request)})
    return json.loads(result.stdout)


def definitions(sources, emacs):
    packages = []
    for source in sources:
        source = Path(source).expanduser().resolve()
        for spec in json.loads((source / "packages.json").read_text()):
            packages.append({**spec, "source": str(source)})
    metadata = lisp("metadata", packages, emacs)
    names = [package["name"] for package in metadata]
    if len(names) != len(set(names)):
        raise ValueError("duplicate package names")
    by_name = {package["name"]: package for package in metadata}
    ordered = dependency_order({name: set(package["dependencies"]) for name, package in by_name.items()})
    return [by_name[name] for name in ordered]


def contents(package):
    source = Path(package["source"])
    result = {}
    for pattern, destination in package["files"].items():
        matches = sorted(glob.glob(str(source / pattern)))
        if not matches:
            raise ValueError(f"{package['name']}: no files match {pattern}")
        for match in matches:
            path = Path(match)
            if not path.is_file() or not path.resolve().is_relative_to(source):
                raise ValueError(f"unsafe package input: {path}")
            target = Path(destination) / path.name
            if target.is_absolute() or ".." in target.parts or str(target) in result:
                raise ValueError(f"unsafe or duplicate package destination: {target}")
            result[str(target)] = path.read_bytes()
    result[f"{package['name']}-pkg.el"] = package["descriptor"].encode()
    return result


def artifact(package):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(contents(package).items()):
            entry = tarfile.TarInfo(f"{package['name']}-{package['version']}/{name}")
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
            archive.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


def clean_sources(packages):
    for source in sorted({package["source"] for package in packages}):
        status = subprocess.check_output(["git", "-C", source, "status", "--porcelain"], text=True)
        if status.strip():
            raise ValueError(f"{source}: commit changes first, or use DEV=1 for a development install")


def build(packages, output, dev=False, publish=False):
    if publish and dev:
        raise ValueError("development builds cannot be published")
    if not dev:
        clean_sources(packages)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ledger_path = output / "release-digests.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    built = []
    for package in packages:
        data = artifact(package)
        digest = hashlib.sha256(data).hexdigest()
        target = output / f"{package['name']}-{package['version']}.tar"
        if publish and target.name in ledger and ledger[target.name] != digest:
            raise ValueError(f"{target.name}: published contents changed; bump the package version")
        if target.exists() and target.read_bytes() != data and not dev:
            raise ValueError(f"{target.name}: contents changed; bump the package version")
        if not target.exists() or target.read_bytes() != data:
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
        if publish:
            target.with_suffix(".entry").write_text(package["archive-entry"] + "\n")
            ledger[target.name] = digest
        built.append({**package, "artifact": str(target.resolve()), "digest": digest})
    if publish:
        temporary = ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        temporary.replace(ledger_path)
    return built


def source_order(packages):
    owners = {package["name"]: package["source"] for package in packages}
    pending = {source: set() for source in owners.values()}
    for package in packages:
        pending[package["source"]].update(
            owners[name] for name in package["dependencies"]
            if name in owners and owners[name] != package["source"])
    return dependency_order(pending)


def dependency_order(pending):
    pending = dict(pending)
    ordered = []
    while pending:
        ready = sorted(source for source, deps in pending.items() if not deps.intersection(pending))
        if not ready:
            raise ValueError("cyclic package/component dependencies")
        for source in ready:
            ordered.append(source)
            del pending[source]
    return ordered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "install", "check", "order"])
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--emacs", default=os.environ.get("EMACS", "emacs"))
    parser.add_argument("--config", default=os.environ.get("EMACS_CONFIG", "~/.emacs.d"))
    parser.add_argument("--output", default="dist/packages")
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--package", help="build one package from a component")
    parser.add_argument("--publish", action="store_true", help="enforce immutable releases and write archive entries")
    args = parser.parse_args()
    packages = definitions(args.source, args.emacs)
    if args.package:
        packages = [package for package in packages if package["name"] == args.package]
        if not packages:
            raise ValueError(f"unknown component package: {args.package}")
    if args.action == "order":
        print(json.dumps(source_order(packages)))
    elif args.action == "build":
        build(packages, args.output, args.dev, args.publish)
    elif args.action == "check":
        expected = [{**package, "digest": hashlib.sha256(artifact(package)).hexdigest()}
                    for package in packages]
        lisp("check", {"config": str(Path(args.config).expanduser().resolve()), "packages": expected}, args.emacs)
    else:
        with tempfile.TemporaryDirectory(prefix="elpa-build-") as directory:
            built = build(packages, directory, args.dev)
            lisp("install", {"config": str(Path(args.config).expanduser().resolve()),
                             "packages": built, "dev": args.dev}, args.emacs)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
