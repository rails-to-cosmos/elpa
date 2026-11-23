# rails-to-cosmos ELPA

Personal Emacs package archive. [Browse published versions](https://rails-to-cosmos.github.io/elpa/).

## Install

```elisp
(require 'package)
(add-to-list 'package-archives
             '("rails-to-cosmos" . "https://rails-to-cosmos.github.io/elpa/") t)
(package-refresh-contents)
(package-install 'table-view)
```

With `use-package`, after adding the archive above:

```elisp
(use-package table-view
  :ensure t
  :pin "rails-to-cosmos")
```

Replace legacy timestamp packages once when switching to release versions.
Emacs sorts the old timestamps above the new versions.

## Packages

| Package | Source | Description |
| --- | --- | --- |
| `agnostic-llm` | [rails-to-cosmos/agnostic-llm](https://github.com/rails-to-cosmos/agnostic-llm) | AI coding agent CLI integration |
| `agnostic-translate` | [rails-to-cosmos/agnostic-translate](https://github.com/rails-to-cosmos/agnostic-translate) | Multilingual translation |
| `cond-let` | [tarsius/cond-let](https://github.com/tarsius/cond-let) | Conditional binding macros |
| `danneskjold-theme` | [rails-to-cosmos/danneskjold-theme](https://github.com/rails-to-cosmos/danneskjold-theme) | High-contrast Emacs theme |
| `darr` | [rails-to-cosmos/darr](https://github.com/rails-to-cosmos/darr) | Visual display layout editor |
| `makeel` | [rails-to-cosmos/makeel](https://github.com/rails-to-cosmos/makeel) | Makefile target picker and runner |
| `org-glance` | [rails-to-cosmos/org-glance](https://github.com/rails-to-cosmos/org-glance) | Org mode projections |
| `org-glance-llm` | [rails-to-cosmos/org-glance-llm](https://github.com/rails-to-cosmos/org-glance-llm) | LLM sessions for Org Glance headlines |
| `session-buffer-cycle` | [rails-to-cosmos/session-buffer-cycle](https://github.com/rails-to-cosmos/session-buffer-cycle) | Cycle through project session buffers |
| `table-view` | [rails-to-cosmos/table-view](https://github.com/rails-to-cosmos/table-view) | Declarative table views |
| `table-view-native` | [rails-to-cosmos/table-view](https://github.com/rails-to-cosmos/table-view) | Optional Rust accelerator for `table-view` |

## Build locally

Run these from the `elpa` checkout with Eask and Emacs installed.

```sh
make build    # Build the archive into docs/
make update   # Fetch fresh sources and rebuild
make serve    # Build and serve at http://localhost:8080 (requires Python 3)
```

## Add a package and publish

Create `recipes/my-package` using the [MELPA recipe format](https://github.com/melpa/melpa#recipe-format).

```elisp
(my-package :fetcher github :repo "rails-to-cosmos/my-package")
```

Run `make publish` to fetch fresh sources, rebuild, commit `docs/`, and push.
GitHub Pages serves `docs/` from `main`.

Recipes with `:make-targets ("package")` use [`bin/packages.py`](bin/packages.py)
to build the same tarball for local installation and publication. Bump the
version when packaged content changes. The archive checks release hashes
against [`docs/release-digests.json`](docs/release-digests.json).

## Install from a component checkout

From `elpa`, with a sibling `org-glance` checkout, Python 3.9+, and Emacs 29.1+:

```sh
make -C ../org-glance package        # Build tarballs into dist/packages/
make -C ../org-glance install-emacs  # Install into ~/.emacs.d by default
make -C ../org-glance check-emacs    # Check installed packages against build receipts
make -C ../org-glance install-emacs DEV=1 EMACS_CONFIG=/path/to/test-profile
```

Set `ELPA_TOOLS` for an ELPA checkout elsewhere and `EMACS` to select the
executable. The profile can supply `scripts/package-setup.el` to set archives
and `package-user-dir`.

Release installs require a clean checkout. Use `DEV=1` for local same-version
changes or downgrades. The installer migrates legacy timestamp packages, saves
replaced directories under `EMACS_CONFIG/package-backups/install-*`, and
restores them if installation fails. Restart Emacs after installing.

## Dagster

[`bin/dagster-app.py`](bin/dagster-app.py) scans recipe heads and resumes
pending publications until the push is verified. The host supplies
`ELPA_DIR`, `DAGSTER_HOME`, the build toolchain, and a write-capable deploy key.
Run `./bin/dagster-app.py` to scan without publishing.

Builds time out after 1,800 seconds by default (`ELPA_PUBLISH_TIMEOUT_SECONDS`).
Logs are under `DAGSTER_HOME/elpa-publish-logs/<run-id>/`. Set
`GLANCE_NOTIFICATION_OUTBOX` to queue notifications after verified pushes.

## Test

```sh
python3 -m unittest discover -s tests -v
```

Set `PACKAGE_BUILD_DIR` to a `package-build` checkout and, if needed, `COMPAT_DIR`
to its `compat` dependency to include the archive build test.
