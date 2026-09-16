"""The mirror equality gate: packaged templates equal the live repository files.

Every mirrored corpus file ships as package data byte-equal to the live file
it mirrors; this executed gate is what keeps the two copies from drifting.
"""

from __future__ import annotations

from pathlib import Path

from hdsh.adopt.corpus import MIRRORED_FILES, MIRRORED_PAIRS, TEMPLATE_FILES

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_MIRRORS_ROOT = Path(__file__).resolve().parents[2] / "src" / "hdsh" / "adopt" / "templates"
_MIRROR_TREE = _MIRRORS_ROOT / "mirrors"
_TEMPLATE_TREE = _MIRRORS_ROOT / "templates"


class TestMirrorEquality:
    def test_every_mirror_is_byte_equal_to_the_live_file(self) -> None:
        for live, _ in MIRRORED_FILES:
            assert (_MIRROR_TREE / live).read_bytes() == (_REPOSITORY_ROOT / live).read_bytes(), (
                f"mirror drifted from the live file: {live}"
            )

    def test_every_pair_mirror_is_byte_equal_to_the_live_file(self) -> None:
        paths = [*(MIRRORED_PAIRS), *(f"{anchor[:-3]}.zh.md" for anchor in MIRRORED_PAIRS)]
        for live in paths:
            assert (_MIRROR_TREE / live).read_bytes() == (_REPOSITORY_ROOT / live).read_bytes(), (
                f"pair mirror drifted from the live file: {live}"
            )

    def test_every_declared_template_exists(self) -> None:
        for template, _ in TEMPLATE_FILES:
            assert (_TEMPLATE_TREE / template).is_file(), f"missing template: {template}"
        for template in ("agents/adopt-rfc.md", "agents/adopt-rfc.zh.md"):
            assert (_TEMPLATE_TREE / template).is_file(), f"missing template: {template}"
