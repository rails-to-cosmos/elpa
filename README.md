# rails-to-cosmos ELPA

My personal [ELPA](https://www.gnu.org/software/emacs/manual/html_node/emacs/Packages.html) archive.

Archive: <https://rails-to-cosmos.github.io/elpa/>

## Use it

```elisp
(add-to-list 'package-archives '("rails-to-cosmos" . "https://rails-to-cosmos.github.io/elpa/") t)
(package-refresh-contents)
(package-install 'table-view)
```

With `use-package`:

```elisp
(use-package table-view
  :ensure t
  :pin "rails-to-cosmos")
```

## Packages

| Package             | Source                                                                      |
|---------------------|-----------------------------------------------------------------------------|
| `table-view`         | [rails-to-cosmos/table-view](https://github.com/rails-to-cosmos/table-view)                 |
| `table-view-native`  | same repo — optional Rust backend (compile-on-install)                                      |
| `org-glance`         | [rails-to-cosmos/org-glance](https://github.com/rails-to-cosmos/org-glance) (`master`) |
| `org-glance-llm`     | [rails-to-cosmos/org-glance-llm](https://github.com/rails-to-cosmos/org-glance-llm) |
| `agnostic-llm`       | [rails-to-cosmos/agnostic-llm](https://github.com/rails-to-cosmos/agnostic-llm) |
| `agnostic-translate` | [rails-to-cosmos/agnostic-translate](https://github.com/rails-to-cosmos/agnostic-translate) |
| `darr`               | [rails-to-cosmos/darr](https://github.com/rails-to-cosmos/darr)                             |
| `danneskjold-theme`  | [rails-to-cosmos/danneskjold-theme](https://github.com/rails-to-cosmos/danneskjold-theme)   |
| `session-buffer-cycle` | [rails-to-cosmos/session-buffer-cycle](https://github.com/rails-to-cosmos/session-buffer-cycle) |

## How it works

An ELPA archive is just static files over HTTPS:

- `archive-contents` — one Lisp form listing every package, version, and deps.
- `PKG-VERSION.el` (single-file) or `PKG-VERSION.tar` (multi-file) + `PKG-readme.txt`.

[`build.el`](build.el) runs [`package-build`](https://github.com/melpa/package-build)
(the MELPA engine) over [`recipes/`](recipes), writing everything into `docs/`.
GitHub Pages serves the committed `docs/` folder from the `main` branch; rebuild
and publish with `make publish`.

The project also owns its Dagster definition in
[`bin/dagster-app.py`](bin/dagster-app.py). Its sensor compares upstream recipe
heads with the last successfully published snapshot. Failed publications remain
pending and are retried on the next sensor tick. After a successful push it writes
an event to `GLANCE_NOTIFICATION_OUTBOX`, when configured, for durable delivery to
the Glance notification feed.

Recipes declaring `:make-targets ("package")` use `bin/packages.py`. The component's
main Lisp header owns the version and dependencies; `packages.json` maps source
globs to package directories. Local installation and archive publication produce
the same deterministic tar file. The six packages from `agnostic-llm`,
`agnostic-translate`, `org-glance`, `org-glance-llm`, and `table-view` use this path.
Other recipes retain their existing snapshot policy.

Publication records immutable version hashes in `docs/release-digests.json`.
Changing packaged contents requires a version bump. Build failures stop
publication; the sensor retries after the source is corrected. Changes outside
packaged files leave the artifact unchanged.

## Component installation and migration

With the ELPA checkout beside the component checkout:

```sh
make -C ../org-glance package
make -C ../org-glance install-emacs
make -C ../org-glance check-emacs
make -C ../org-glance install-emacs DEV=1 EMACS_CONFIG=/path/to/test-profile
```

`ELPA_TOOLS` overrides the tooling checkout. `EMACS` selects the executable;
the default also discovers the usual macOS app locations. Python 3.9+ and
Emacs 29.1+ are supported. `EMACS_CONFIG` defaults to `~/.emacs.d`.
The installer loads the profile's optional `scripts/package-setup.el` for package
archives and a custom `package-user-dir`, without loading the full init.

Normal installation requires a clean Git checkout. Repeating an installed build
is a no-op. Changed same-version builds and release downgrades require `DEV=1`.
Development artifacts cannot be published. `check-emacs` reads build receipts
without installing packages or refreshing archives.

Existing timestamp packages sort above release versions. The installer explicitly
migrates them, moving replaced directories into
`EMACS_CONFIG/package-backups/install-*`. If installation fails it restores the
previous directories. Missing dependencies may be downloaded from the profile's
configured archives. Restart Emacs after installation. Retained backups can be
restored with Emacs stopped.

Deploy the component definitions and shared tools, publish the first release
archive, then run Lab bootstrap or component installation on each profile.
Archive-only users must explicitly replace timestamp installations once; ordinary
version comparison cannot perform that downgrade. The old dependency requirement
`agnostic-llm >= 20260916.2109` maps to release `0.8.0.0.20260916.0`;
the named-session requirement `20261025` maps to `0.12.0.0.20261025.0`.

Run migration, rollback, repeatability, and publication checks with
`python3 -m unittest discover -s tests -v`.
Set `PACKAGE_BUILD_DIR` to a package-build checkout and, when required,
`COMPAT_DIR` to its compat dependency to include the complete archive-driver test.

## Add a package

1. Drop a [MELPA-style recipe](https://github.com/melpa/melpa#recipe-format)
   in [`recipes/`](recipes), named after the package:

   ```elisp
   (my-package :fetcher github :repo "rails-to-cosmos/my-package")
   ```

2. Run `make publish` — rebuilds `docs/`, commits, and pushes.

## Build locally

```sh
make build     # build the archive -> docs/
make update    # re-fetch latest commits, then rebuild
make serve     # build + serve at http://localhost:8080
make publish   # rebuild, commit docs/, and push to Pages
```

The Dagster host supplies `ELPA_DIR`, `DAGSTER_HOME`, the build toolchain, and a
write-capable deploy key. The sensor stays idle with an actionable reason when
that key is unavailable. Validate the upstream scan without publishing with:

```sh
./bin/dagster-app.py
```
