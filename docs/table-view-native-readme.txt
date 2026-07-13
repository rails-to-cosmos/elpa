Optional accelerator: a Rust subprocess (`tvx') owns the table data model
(sort, filter, window) so Emacs stays a thin view past ~20k rows.  It speaks
JSON-RPC over stdio via the built-in `jsonrpc.el' and plugs into the existing
`table-view' paged mode as a `page-fn' -- no core rewrite.

Distribution is compile-on-install: the Rust source ships under native/ and
is built with cargo via `M-x table-view-native-compile'.  When the binary is
absent or unbuildable, table-view runs the pure-elisp path and warns.

Phase 1: initialize / open / window / close (discrete paged windows).  The
live-update layer ($/delta, `table-view-apply-delta') lands later.
