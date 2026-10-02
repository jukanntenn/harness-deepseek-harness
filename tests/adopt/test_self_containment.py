"""The transplant self-containment gate.

Rewriting must be the identity over the movable corpus modulo the invocation
mapping — no outbound prose links, no dead upstream URLs — and the source
corpus keeps one invocation form per side. This executed invariant is what
keeps the adopted corpus self-contained: a new citation outside the closure
fails here, at authoring time, instead of leaking into a consumer repository.
"""

from __future__ import annotations

import re
from pathlib import Path

from hdsh.adopt import corpus

_MIRRORS_ROOT = Path(corpus.__file__).parent / "templates" / "mirrors"
_INSTALLED = corpus.installed_destinations("2026-01-01")
_BARE_INVOCATION = re.compile(r"`hdsh [a-z]")
_NON_HDSH_UV_COMMAND = re.compile(r"`uv run (?!hdsh)[a-z]")


def _mirror_documents() -> list[tuple[str, str]]:
    """Every mirrored Markdown document as a (destination, text) pair."""
    return [
        (
            path.relative_to(_MIRRORS_ROOT).as_posix(),
            path.read_text(encoding="utf-8"),
        )
        for path in sorted(_MIRRORS_ROOT.rglob("*.md"))
    ]


class TestSelfContainment:
    def test_rewriting_is_the_identity_modulo_invocation_mapping(self) -> None:
        for dest, text in _mirror_documents():
            transplanted = corpus.transplant_markdown(
                text, dest=dest, installed=_INSTALLED, hdsh_ref="v0.1.0"
            )
            assert transplanted == corpus.map_invocations(text), dest

    def test_no_upstream_blob_urls_in_the_source_corpus(self) -> None:
        for dest, text in _mirror_documents():
            assert corpus.UPSTREAM_BLOB_ROOT not in text, dest

    def test_source_corpus_uses_only_the_uv_invocation_form(self) -> None:
        for dest, text in _mirror_documents():
            assert _BARE_INVOCATION.search(text) is None, dest

    def test_source_corpus_carries_no_development_commands(self) -> None:
        for dest, text in _mirror_documents():
            assert _NON_HDSH_UV_COMMAND.search(text) is None, dest

    def test_every_cited_decision_record_moves_with_the_corpus(self) -> None:
        for anchor in corpus.RFC_CLOSURE:
            assert anchor in corpus.MIRRORED_PAIRS, anchor
            assert (_MIRRORS_ROOT / anchor).is_file(), anchor
            assert (_MIRRORS_ROOT / f"{anchor[: -len('.md')]}.zh.md").is_file(), anchor

    def test_invocation_mapping_covers_fenced_examples(self) -> None:
        text = "Prose says `uv run hdsh scope`.\n\n```sh\nuv run hdsh pairing verify\n```\n"
        assert corpus.map_invocations(text) == (
            "Prose says `hdsh scope`.\n\n```sh\nhdsh pairing verify\n```\n"
        )
