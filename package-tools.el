;;; package-tools.el --- Component package metadata and installation -*- lexical-binding: t; -*-

(require 'cl-lib)
(require 'json)
(require 'package)

(defun rce-get (object key)
  (alist-get key object))

(defun rce-metadata (spec)
  (let* ((source (rce-get spec 'source))
         (main (expand-file-name (rce-get spec 'main) source))
         (desc (with-temp-buffer
                 (insert-file-contents main)
                 (package-buffer-info)))
         (name (symbol-name (package-desc-name desc)))
         (version (package-version-join (package-desc-version desc)))
         (requirements (package-desc-reqs desc)))
    (append spec
            `((name . ,name) (version . ,version)
              (dependencies . ,(vconcat (mapcar (lambda (req) (symbol-name (car req))) requirements)))
              (requirements . ,(mapcar (lambda (req)
                                         (cons (car req) (package-version-join (cadr req))))
                                       requirements))
              (descriptor . ,(concat
                              ";;; Generated from the package header. -*- no-byte-compile: t; -*-\n"
                              (prin1-to-string
                               `(define-package ,name ,version ,(package-desc-summary desc)
                                  ',(mapcar (lambda (req)
                                              (list (car req) (package-version-join (cadr req))))
                                            requirements))) "\n"))
              (archive-entry . ,(prin1-to-string
                                 (cons (package-desc-name desc)
                                       (vector (package-desc-version desc) requirements
                                               (package-desc-summary desc) 'tar))))))))

(defun rce-profile (request &optional no-activate)
  (setq user-emacs-directory (file-name-as-directory (rce-get request 'config))
        package-user-dir (expand-file-name "elpa" user-emacs-directory))
  (let ((setup (expand-file-name "scripts/package-setup.el" user-emacs-directory)))
    (when (file-exists-p setup) (load setup nil t)))
  (package-initialize no-activate))

(defun rce-timestamp-version-p (version)
  (and (= (length version) 2)
       (<= 20000101 (car version) 20991231)
       (<= 0 (cadr version) 2359)
       (< (% (cadr version) 100) 60)))

(defun rce-installed (name)
  (cl-remove-if-not
   (lambda (desc) (file-in-directory-p (package-desc-dir desc) package-user-dir))
   (cdr (assq (intern name) package-alist))))

(defun rce-receipt (desc)
  (let ((path (expand-file-name ".component-digest" (package-desc-dir desc))))
    (when (file-exists-p path)
      (with-temp-buffer (insert-file-contents path) (string-trim (buffer-string))))))

(defun rce-current-p (package)
  (let ((installed (rce-installed (rce-get package 'name))))
    (and (= (length installed) 1)
         (equal (package-desc-version (car installed))
                (version-to-list (rce-get package 'version)))
         (equal (rce-receipt (car installed)) (rce-get package 'digest)))))

(defun rce-install (request)
  (rce-profile request)
  (let* ((packages (rce-get request 'packages))
         (changed (cl-remove-if #'rce-current-p packages))
         refreshed
         (package-native-compile nil)
         (package-selected-packages
          (append (mapcar (lambda (p) (intern (rce-get p 'name))) packages)
                  package-selected-packages)))
    (dolist (package changed)
      (let ((version (version-to-list (rce-get package 'version))))
        (dolist (desc (rce-installed (rce-get package 'name)))
          (when (and (not (rce-get request 'dev))
                     (or (and (equal (package-desc-version desc) version)
                              (rce-receipt desc)
                              (not (equal (rce-receipt desc) (rce-get package 'digest))))
                         (and (version-list-< version (package-desc-version desc))
                              (not (rce-timestamp-version-p (package-desc-version desc))))))
            (error "%s: bump the version; use DEV=1 for an explicit development replacement"
                   (rce-get package 'name))))))
    (when changed
      (make-directory package-user-dir t)
      (let* ((backup-root (expand-file-name "package-backups" user-emacs-directory))
             (backup (progn (make-directory backup-root t)
                            (make-temp-file (expand-file-name "install-" backup-root) t)))
             moved created success)
        (unwind-protect
            (progn
              (dolist (package changed)
                (dolist (desc (rce-installed (rce-get package 'name)))
                  (let* ((old (directory-file-name (package-desc-dir desc)))
                         (saved (expand-file-name (file-name-nondirectory old) backup)))
                    (rename-file old saved)
                    (push (cons saved old) moved)))
                (setq package-alist (assq-delete-all (intern (rce-get package 'name)) package-alist)))
              (setq package-activated-list nil)
              (dolist (package changed)
                (let ((target (expand-file-name
                               (concat (rce-get package 'name) "-" (rce-get package 'version))
                               package-user-dir)))
                  (push target created)
                  (when (and (not refreshed)
                             (cl-some (lambda (req)
                                        (not (package-installed-p (car req) (version-to-list (cdr req)))))
                                      (rce-get package 'requirements)))
                    (package-refresh-contents)
                    (setq refreshed t))
                  (package-install-file (rce-get package 'artifact))
                  (with-temp-file (expand-file-name ".component-digest" target)
                    (insert (rce-get package 'digest) "\n"))))
              (setq success t)
              (message "Installed %d component package(s); backups: %s. Restart Emacs to load them."
                       (length changed) backup))
          (unless success
            (dolist (path created) (when (file-directory-p path) (delete-directory path t)))
            (dolist (pair moved) (rename-file (car pair) (cdr pair)))))))
    (unless changed (message "Component packages are current"))))

(defun rce-command (action)
  (let* ((request (json-parse-string
                   (getenv "RCE_REQUEST")
                   :object-type 'alist :array-type 'list :false-object nil :null-object nil))
         (result
          (pcase action
            ("metadata" (vconcat (mapcar #'rce-metadata request)))
            ("install" (rce-install request) t)
            ("check"
             (rce-profile request t)
             (dolist (package (rce-get request 'packages))
               (unless (rce-current-p package)
                 (error "%s needs install-emacs" (rce-get package 'name))))
             t))))
    (princ (json-encode result))))

(provide 'package-tools)
