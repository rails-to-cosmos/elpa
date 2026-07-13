;;; build.el --- Build the rails-to-cosmos ELPA archive -*- lexical-binding: t; -*-

;; Builds every recipe in recipes/ into docs/ (archive-contents + the package
;; .el/.tar files), then writes a .nojekyll marker and a small index.html so the
;; result is a GitHub-Pages-servable ELPA.  Run via `make build' (Eask puts
;; package-build on the load-path); commit docs/ and push, with Pages set to
;; deploy from the main branch's /docs folder.

;;; Code:

(require 'package-build)

(defconst rce/root
  (file-name-directory (or load-file-name buffer-file-name default-directory)))

(setq package-build-recipes-dir (expand-file-name "recipes/" rce/root)
      package-build-archive-dir (expand-file-name "docs/" rce/root)
      package-build-working-dir (expand-file-name ".working/" rce/root)
      ;; Snapshot builds from the latest commit; flip to t to build stable
      ;; versions from git tags instead.
      package-build-stable nil)

;; Pin the classic bare-date snapshot scheme: "YYYYMMDD.HHMM".
;; package-build's default changed to `package-build-release+date+count-version'
;; ("<header>.<date>.<count>"), which sorts BELOW a bare date and silently
;; breaks upgrades for packages previously published with bare-date versions.
(setq package-build-snapshot-version-functions
      (list #'package-build-timestamp-version))

(make-directory package-build-archive-dir t)

(package-build-all)

;; --- GitHub Pages niceties -------------------------------------------------

;; Serve files verbatim (no Jekyll processing of the archive files).
(with-temp-file (expand-file-name ".nojekyll" package-build-archive-dir))

(defun rce/index-html ()
  "Return a minimal index.html listing the built packages."
  (let* ((ac (with-temp-buffer
               (insert-file-contents (expand-file-name "archive-contents" package-build-archive-dir))
               (goto-char (point-min))
               (read (current-buffer))))
         (pkgs (cdr ac))
         (rows (mapconcat
                (lambda (entry)
                  (let* ((name (car entry))
                         (v (aref (cdr entry) 0))
                         (desc (aref (cdr entry) 2)))
                    (format "<tr><td><code>%s</code></td><td>%s</td><td>%s</td></tr>"
                            name (mapconcat #'number-to-string v ".") desc)))
                (sort (copy-sequence pkgs)
                      (lambda (a b) (string< (symbol-name (car a)) (symbol-name (car b)))))
                "\n")))
    (concat
     "<!doctype html><meta charset=utf-8>"
     "<title>rails-to-cosmos ELPA</title>"
     "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:44rem;margin:3rem auto;padding:0 1rem}"
     "code,pre{background:#f4f4f4;border-radius:4px}pre{padding:1rem;overflow:auto}"
     "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:.4rem .6rem;text-align:left}</style>"
     "<h1>rails-to-cosmos ELPA</h1>"
     "<p>A personal Emacs package archive.  Add it, then install:</p>"
     "<pre>(add-to-list 'package-archives\n"
     "             '(\"rails-to-cosmos\" . \"https://rails-to-cosmos.github.io/elpa/\") t)\n"
     "(package-refresh-contents)</pre>"
     "<h2>Packages</h2><table><tr><th>Package</th><th>Version</th><th>Description</th></tr>\n"
     rows
     "\n</table>")))

(with-temp-file (expand-file-name "index.html" package-build-archive-dir)
  (insert (rce/index-html)))

(message "ELPA built into %s" package-build-archive-dir)

;;; build.el ends here
