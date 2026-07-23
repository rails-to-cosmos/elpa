The `llm' PLUGIN for org-glance: install this package and enable it with
(setq org-glance-plugins '(llm)) -- or `I' in the transient.  Core
org-glance does not depend on it, so a plain install never pulls in
vterm.

The `l' action: pick a headline and open the `agnostic-llm' menu pinned to
the headline's content-addressable data directory, so the CLI's per-directory
context accumulates there.  The `*llm:…*' session buffer is named for the
headline's title (see `org-glance-llm--label'); the data dir's hash is the
fallback.

A headline's session is identified by that data DIR -- a full-hash path
unique to the headline, kept as the session buffer's `default-directory'.
Reopening the headline switches to the live buffer, so one headline keeps
one session; the title label is cosmetic, so two same-titled headlines
still get separate sessions.
