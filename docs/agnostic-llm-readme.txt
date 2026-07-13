
Drive the `claude' CLI (https://docs.anthropic.com/en/docs/claude-cli)
from Emacs.  Each project gets a dedicated `*claude:PROJECT*' vterm; a
multi-line prompt buffer with @file completion feeds it, and a throwaway
"bubble" streams a `claude -p' reply inline without disturbing the main
session.  `agnostic-llm-show-last-response' renders the latest assistant
turn from the session JSONL into a read-only buffer.

A transient menu (`agnostic-llm-menu') gathers the commands and exposes
per-invocation switches for model, reasoning effort, and
`--dangerously-skip-permissions'.  A FIXME/TODO annotation system records
notes at point, persists them (per-project under `.agnostic-llm/' or
per-user under `~/.cache/agnostic-llm/'), lists them, and can hand them
back to Claude to resolve.

Requires the `claude' CLI on PATH.  Binds no global keys itself — bind the
entry points (`agnostic-llm', `agnostic-llm-menu', `agnostic-llm-prompt',
...) from your own configuration.
