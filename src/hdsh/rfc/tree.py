"""Shared path vocabulary and structure walk for the ``.agents/rfcs/`` tree.

The lifecycle/class layout is the protocol defined by
``.agents/rfcs/README.md``; the format and archive gates derive their path
decisions from these closed sets instead of keeping private copies. The walk
enforces the closed structure: only the three lifecycle folders belong to
the active tree, files directly at the tree root sit outside it, an unknown
directory at the root violates the closed lifecycle set even when empty, and
an RFC lives at exactly ``{lifecycle}/{class}/yyyy-mm-dd-topic.md``.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

NOTES_ROOT = ".agents/rfcs"

#: The sealed tree only implemented records can enter.
ARCHIVED_LIFECYCLE = "archived"

#: Lifecycle folders of the active tree an RFC moves between.
LIFECYCLE_FOLDERS = ("proposed", "implemented", "rejected")

#: The closed class set; adding a class is a README-level protocol change.
CLASS_FOLDERS = ("feature", "bug-fix", "simplification", "architecture", "process", "testing")

#: English RFC filenames: first-proposed date, lowercase topic slug.
ENGLISH_NOTE_FILENAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")

#: Non-RFC Markdown allowed directly at a lifecycle root, never deeper.
ROOT_ALLOWLIST = frozenset({"AGENTS.md", "CLAUDE.md"})

#: Path segments between a lifecycle folder and an RFC file: the class, the file.
_NOTE_SEGMENTS = 2


def walk_notes(root: Path) -> tuple[list[Path], list[str]]:
    """Walk the active lifecycle trees and enforce the structure rules.

    Args:
        root: Repository root path.

    Returns:
        Every well-placed English RFC under the three lifecycle folders, plus
        one violation message per structure error (unknown lifecycle folder,
        bad depth, unknown class folder, or bad filename).
    """
    notes_root = root / NOTES_ROOT
    if not notes_root.is_dir():
        return [], []
    # The lifecycle set is closed at the root too: any other directory would
    # hold RFCs invisible to the per-lifecycle walk below.
    errors = [
        f"{NOTES_ROOT}/{entry.name}/: unknown lifecycle folder (allowed: "
        f"{', '.join(LIFECYCLE_FOLDERS)}, plus {ARCHIVED_LIFECYCLE}/)"
        for entry in sorted(notes_root.iterdir())
        if stat.S_ISDIR(entry.lstat().st_mode)
        and entry.name != ARCHIVED_LIFECYCLE
        and entry.name not in LIFECYCLE_FOLDERS
    ]
    notes: list[Path] = []
    for lifecycle in LIFECYCLE_FOLDERS:
        lifecycle_root = notes_root / lifecycle
        if not lifecycle_root.is_dir():
            continue
        for path in sorted(lifecycle_root.rglob("*.md")):
            parts = path.relative_to(lifecycle_root).parts
            relative = str(path.relative_to(root))
            if len(parts) == 1 and path.name in ROOT_ALLOWLIST:
                continue
            # A Chinese counterpart (foo.zh.md) is the same RFC indexed via its
            # English filename; the pairing gate owns its consistency.
            if path.name.endswith(".zh.md"):
                continue
            if len(parts) != _NOTE_SEGMENTS:
                errors.append(
                    f"{relative}: expected {{lifecycle}}/{{class}}/file.md "
                    f"(got depth {len(parts) + 1})"
                )
                continue
            note_class = parts[0]
            if note_class not in CLASS_FOLDERS:
                errors.append(
                    f"{relative}: unknown class folder {note_class!r} "
                    f"(allowed: {', '.join(CLASS_FOLDERS)})"
                )
                continue
            if ENGLISH_NOTE_FILENAME.match(path.name) is None:
                errors.append(f"{relative}: filename must be yyyy-mm-dd-topic.md")
                continue
            notes.append(path)
    return notes, errors
