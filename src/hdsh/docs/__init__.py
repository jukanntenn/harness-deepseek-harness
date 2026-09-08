"""Documentation corpus gates.

Three verify-only gates over a repository's Markdown corpus, each wired as a
prek hook and configured by the consuming repository through
``.hdsh/docs.manifest.json`` (see :mod:`hdsh.docs.config`):

- :mod:`hdsh.docs.wrap` — one physical line per prose paragraph.
- :mod:`hdsh.docs.links` — relative cross-links and ``#fragment`` anchors resolve.
- :mod:`hdsh.docs.budgets` — ``wc -w`` ceilings for standing docs.
"""
