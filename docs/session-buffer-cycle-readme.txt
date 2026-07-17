
Flip the current window through a set of per-project "session" buffers.
Each project (detected via `project.el', falling back to
`default-directory') gets one buffer per configured kind, named
`*KIND:LABEL*' where LABEL is the project's final path component.

`session-buffer-cycle' switches the current window to the next kind's
buffer, wrapping around and creating it on demand.  From any buffer that
is not a session buffer it enters the cycle at the first kind.

The kinds live in `session-buffer-cycle-kinds', an alist mapping a KIND
string to an OPENER function called with (NAME LABEL ROOT).  The opener
creates a buffer named NAME in the current window; `default-directory' is
already bound to ROOT.  The default cycles an eshell and a Dired buffer,
both built in.  Add anything you like -- a vterm, a shell attached to a
CLI agent, a browser, a REPL:

  ;; A plain vterm and a Claude CLI vterm:
  (require 'vterm)
  (setq session-buffer-cycle-kinds
        '(("vterm" . (lambda (name _label _root) (vterm name)))
          ("llm"   . (lambda (name _label _root)
                       (let ((vterm-shell "claude")) (vterm name))))))

Binds no keys itself.  Bind `session-buffer-cycle' from your config, e.g.

  (global-set-key (kbd "C-x C-x") #'session-buffer-cycle)
