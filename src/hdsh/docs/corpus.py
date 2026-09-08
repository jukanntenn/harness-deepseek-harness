"""Repository-root discovery and corpus expansion shared by the documentation gates."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from hdsh.docs.config import CorpusScope


@dataclass(frozen=True)
class CorpusFile:
    """One corpus file: its repository-relative path and absolute path."""

    #: Repository-relative path with ``/`` separators, for diagnostics.
    path: str
    #: Absolute path, for reads.
    abs_path: Path


def find_repository_root(tool: str) -> Path:
    """Locate the Git repository root the gate was invoked in.

    Args:
        tool: The gate's CLI name for diagnostics.

    Returns:
        The absolute repository root.

    Raises:
        SystemExit: With code 2 when Git is unavailable or the working
            directory is inside no repository.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        print(f"{tool}: cannot locate repository root: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    if completed.returncode != 0:
        print(f"{tool}: working directory is inside no Git repository", file=sys.stderr)
        raise SystemExit(2)
    return Path(completed.stdout.strip())


def discover_corpus_files(root: Path, scope: CorpusScope) -> list[CorpusFile]:
    """Expand one corpus scope into stable, deduplicated files.

    Excludes are globbed with the same semantics as includes; matches are
    sorted per pattern and deduplicated by real path, so a symlinked
    instruction file is checked once and the result order is deterministic.

    Args:
        root: Absolute repository root.
        scope: Include/exclude glob pair.

    Returns:
        The selected files in stable first-seen order.
    """
    excluded: set[Path] = set()
    for pattern in scope.exclude:
        for match in sorted(root.glob(pattern)):
            if match.is_file():
                excluded.add(match.resolve())
    seen: set[Path] = set()
    files: list[CorpusFile] = []
    for pattern in scope.include:
        for match in sorted(root.glob(pattern)):
            if not match.is_file():
                continue
            real = match.resolve()
            if real in seen or real in excluded:
                continue
            seen.add(real)
            files.append(CorpusFile(match.relative_to(root).as_posix(), match))
    return files
