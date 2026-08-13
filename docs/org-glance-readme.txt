Projections over org-mode headlines.  The org files are the source of
truth -- durable and addressable; everything else is a projection.

Every captured headline gets an `:ORG_GLANCE_ID:' and its own org file
under `org-glance-directory'.  Tags are collections, each free to carry
its own todo cycle and capture template.  Tables, overviews, the property
index and the write-ahead log are derived: delete one and the org files
rebuild it.

Edits go back into those files as ordinary org.  Another program may edit
them too: the `glance' browser front end writes the same bytes and names
each write in `meta/EXTERNAL.jsonl', which the next read folds back in.
