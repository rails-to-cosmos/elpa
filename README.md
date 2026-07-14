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
| `org-glance`         | [rails-to-cosmos/org-glance](https://github.com/rails-to-cosmos/org-glance) (`metadata-migration`) |
| `agnostic-translate` | [rails-to-cosmos/agnostic-translate](https://github.com/rails-to-cosmos/agnostic-translate) |
| `darr`               | [rails-to-cosmos/darr](https://github.com/rails-to-cosmos/darr)                             |
| `danneskjold-theme`  | [rails-to-cosmos/danneskjold-theme](https://github.com/rails-to-cosmos/danneskjold-theme)   |

## How it works

An ELPA archive is just static files over HTTPS:

- `archive-contents` — one Lisp form listing every package, version, and deps.
- `PKG-VERSION.el` (single-file) or `PKG-VERSION.tar` (multi-file) + `PKG-readme.txt`.

[`build.el`](build.el) runs [`package-build`](https://github.com/melpa/package-build)
(the MELPA engine) over [`recipes/`](recipes), writing everything into `docs/`.
GitHub Pages serves the committed `docs/` folder from the `main` branch; rebuild
and publish with `make publish`.

Versions are **snapshots** (`YYYYMMDD.HHMM` from each source repo's latest
commit); set `package-build-stable` to `t` in `build.el` to build stable
versions from git tags instead.

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
