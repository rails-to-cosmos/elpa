
Drive an agentic CLI from Emacs.  Each project gets a dedicated
`*llm:PROJECT*' vterm; a multi-line prompt buffer with @file completion
feeds it, and a throwaway "bubble" streams a one-shot reply inline
without disturbing the main session.  `agnostic-llm-show-last-response'
renders the latest assistant turn from the session JSONL into a read-only
buffer.

A transient menu (`agnostic-llm-menu') gathers the commands and exposes
per-invocation switches for model, reasoning effort, and skipping
permission prompts.  A FIXME/TODO annotation system records notes at
point, persists them (per-project under `.agnostic-llm/' or per-user
under `~/.cache/agnostic-llm/'), lists them, and can hand them back to
the LLM to resolve.

Everything provider-specific — the CLI executable, its command-line
flags, the session-store layout, and the model/effort catalog — lives in
`agnostic-llm-providers', keyed by `agnostic-llm-provider'.  `claude' is
the default provider; add entries to drive other agentic CLIs (see
docs/multi-backend-design.org).

Requires the active provider's CLI on PATH (the `claude' CLI by default).
Binds no global keys itself — bind the entry points (`agnostic-llm',
`agnostic-llm-menu', `agnostic-llm-prompt', ...) from your own
configuration.
