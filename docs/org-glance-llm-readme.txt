The `llm' PLUGIN for org-glance: install this package and enable it with
(setq org-glance-plugins '(llm)) -- or `I' in the transient.  Core
org-glance does not depend on it, so a plain install never pulls in
vterm.

The `l' action: pick a headline and open the `agnostic-llm' menu pinned to
the headline's content-addressable data directory, so the CLI's per-directory
context accumulates there.  The menu selects the provider first; its model
choices then come from that provider's catalog.  The `*llm:…*' session
buffer is named for the headline's title (see `org-glance-llm--label'); the
data dir's hash is the fallback.

A session is identified by provider, data DIR, and canonical name.  Its data
dir remains the buffer's `default-directory'; named conversations coexist
under one headline.
