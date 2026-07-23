A tiny, backend-agnostic core that renders a declarative table
description -- columns, actions, default sort -- and dispatches keys to
consumer-registered command handlers.

Responsibilities:
  * render a spec as an aligned, org-table-styled read-only view
  * colour `badge' cells from the column's declared palette
  * build a keymap from the declared actions, dispatch by command name
  * own a row store keyed by id: set-rows / upsert-row / delete-row
  * client-side sort on sortable columns
  * interactive substring filter (/)
  * mark rows (m) and run `bulk' actions on the marked set
  * optional server-side pagination via a `page-fn': one page in memory,
    sort and filter pushed down, marks and bulk that span pages

A consumer provides: a parsed spec, a handler alist (command-name -> FN of
ID ROW), and either a `fill-fn' (BUFFER -> populates all rows via the
mutators below) or, for server-side pagination, a `page-fn' (REQUEST ->
fetches one page and delivers it with `table-view-set-page').

See examples/ for runnable demos:
  minimal.el       — inline rows from a JSON spec
  fill-function.el — populate via a fill function (Emacs subprocesses)
  upsert.el        — streaming row updates via a timer
  multi-sort.el    — column navigation + multi-column (C-u ^) sorting
  sort-methods.el  — per-column sort methods (values / compare) + default sort
  delete.el        — row deletion gated on a custom pre-delete step
  bulk.el          — marking (m), narrowing (/), and bulk actions (bulk: t)
  paginate.el      — server-side pagination over a fake backend (page-fn)
  org-links.el     — Org links in cells, followed by C-c C-o or mouse

Keybindings in table-view-mode:
  g   — clear filter/narrow & refresh, preserving the sort order
  ^   — sort by the column at point, repeat toggles asc/desc;
        off a column, cycle through every column and direction
  C-u ^ — add the column at point as a secondary (tie-breaker) sort key;
          a following run of `^' then toggles that key's direction
  ?   — toggle the multiline action legend (below the subtitle)
  m   — toggle mark on the current row;  u — unmark it
  M   — mark all visible rows;  U — unmark all
  /   — narrow to the marked rows, or filter by substring when none marked
  n/p — next/previous data row (stops on the last / first row)
  f/b — forward/backward: by column on a table line (header or row),
        by char elsewhere
  C-c C-o — follow the Org link at point (cells may hold [[TARGET][DESC]]);
            links are also mouse-clickable
  M-left/M-right — move the column at point left/right (org-table style)
  > / . — next page, < / , — previous page (paged buffers)
  M-> / M-< — last / first page;  M-g — go to page (offset paging)
  q   — quit
