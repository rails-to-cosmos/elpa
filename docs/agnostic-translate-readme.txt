
Translate text into multiple languages at once using an LLM backend.
Auto-detects the source language from the input and translates into
every other language in a configurable list (seeded from system locale
and keyboard layouts).

Everything lives in one `table-view' buffer, `*agnostic-translate*':
each translation is a row, with a column for the detected source
language, one column per target language, and an agent comment.  Rows
accumulate for the session.  Press `+' to compose input (an
Org-capture-style buffer), `a' / `d' to add / remove a language
column, `w' / RET to copy the cell at point, and `o' to open the whole
row pretty-printed.

Requires `claude' CLI (https://docs.anthropic.com/en/docs/claude-cli)
on PATH.
