"""Git-blob operations owned by the bilingual pairing workflow."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess

_SNAPSHOT_REF_PREFIX = "refs/hdsh/pairing/snapshots"
_GITHEAD_ENVIRONMENT_KEY = re.compile(r"GITHEAD_([0-9a-f]{40})")
_INDEX_METADATA_FIELDS = 3


class GitError(RuntimeError):
    """A repository-owned Git subprocess could not produce usable output."""


def blob_hash(content: bytes) -> str:
    """Compute the full git blob hash of file content (``git hash-object``).

    Args:
        content: Exact file bytes.

    Returns:
        The 40-hex-digit SHA-1 blob hash.
    """
    digest = hashlib.sha1()  # noqa: S324 - SHA-1 is the git object-hash format
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def run_git(
    root: str, args: list[str], operation: str, *, input_bytes: bytes | None = None
) -> bytes:
    """Run one Git subprocess and return its exact stdout bytes.

    Args:
        root: Repository root used as Git's working directory.
        args: Arguments following the ``git`` executable.
        operation: Human-readable operation for failure diagnostics.
        input_bytes: Optional stdin bytes.

    Returns:
        Exact stdout bytes.

    Raises:
        GitError: When Git cannot start or exits unsuccessfully.
    """
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            input=input_bytes,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        msg = f"{operation} failed: {error}"
        raise GitError(msg) from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        msg = f"{operation} failed with status {result.returncode}: {detail}"
        raise GitError(msg)
    return result.stdout


def git_index_paths(root: str) -> set[str]:
    """Return every stage-zero path currently present in the Git index.

    Args:
        root: Repository root.

    Returns:
        The set of repository-relative paths.

    Raises:
        GitError: When a Git subprocess fails or returns a malformed entry.
    """
    listing = run_git(root, ["ls-files", "--stage", "-z"], "listing Git index paths")
    paths: set[str] = set()
    for entry in listing.decode("utf-8").split("\0"):
        if entry == "":
            continue
        meta, separator, _name = entry.partition("\t")
        if separator == "":
            msg = "git ls-files --stage returned a malformed entry"
            raise GitError(msg)
        fields = meta.split(" ")
        if len(fields) != _INDEX_METADATA_FIELDS:
            msg = "git ls-files --stage returned a malformed entry"
            raise GitError(msg)
        if fields[2] == "0":
            paths.add(_name)
    return paths


def git_merge_input_paths(root: str, environment: dict[str, str] | None = None) -> set[str]:
    """Paths visible to a custom merge driver from the index and merge heads.

    Git invokes custom drivers before it writes clean additions from the other
    heads into stage zero; every ``GITHEAD_<oid>`` environment entry names a
    merge head whose tree must be consulted too. The explicit post-conflict
    resolver has no ``GITHEAD`` entries and uses the index alone.

    Args:
        root: Repository root.
        environment: Environment carrying ``GITHEAD_`` entries; defaults to
            ``os.environ``.

    Returns:
        Every stage-zero and merge-head path.

    Raises:
        GitError: When a Git subprocess fails.
    """
    paths = git_index_paths(root)
    env = os.environ if environment is None else environment
    heads = sorted(
        match.group(1) for key in env if (match := _GITHEAD_ENVIRONMENT_KEY.fullmatch(key))
    )
    for head in heads:
        listing = run_git(
            root,
            ["ls-tree", "-r", "--name-only", "-z", head],
            f"listing merge-head {head} paths",
        )
        paths.update(entry for entry in listing.decode("utf-8").split("\0") if entry)
    return paths


def read_git_index_blob(root: str, path: str) -> tuple[str, bytes] | None:
    """Read one path from the Git index without consulting working-tree bytes.

    Args:
        root: Repository root.
        path: Repository-relative path.

    Returns:
        The stage-zero object ID and exact blob bytes, or ``None`` when the
        path is absent.

    Raises:
        GitError: When the path is unmerged or its index entry is invalid.
    """
    output = run_git(
        root, ["ls-files", "--stage", "-z", "--", path], f"git ls-files --stage for {path}"
    )
    entries = [entry for entry in output.decode("utf-8").split("\0") if entry]
    if not entries:
        return None
    if len(entries) != 1:
        msg = f"{path} does not have exactly one resolved index entry"
        raise GitError(msg)
    meta, separator, _name = entries[0].partition("\t")
    if separator == "":
        msg = f"{path} remains unmerged or has an invalid index entry"
        raise GitError(msg)
    fields = meta.split(" ")
    if len(fields) != _INDEX_METADATA_FIELDS or fields[2] != "0":
        msg = f"{path} remains unmerged or has an invalid index entry"
        raise GitError(msg)
    object_id = fields[1]
    content = run_git(root, ["cat-file", "blob", object_id], f"reading staged {path}")
    return object_id, content


def store_git_blob(root: str, content: bytes) -> str:
    """Persist exact working-tree bytes for later recovery by a pairing record.

    The bytes are written even when they never appear in the index or a commit,
    and the object is pinned under a content-addressed snapshot ref so garbage
    collection cannot invalidate a recorded recovery pointer.

    Args:
        root: Repository root.
        content: Exact file bytes.

    Returns:
        The stored blob's object ID.

    Raises:
        GitError: When Git stores unexpected bytes or the ref cannot be written.
    """
    expected = blob_hash(content)
    stored = (
        run_git(
            root,
            ["hash-object", "-w", "--stdin"],
            "git hash-object -w --stdin",
            input_bytes=content,
        )
        .decode("utf-8")
        .strip()
    )
    if stored != expected:
        msg = (
            "git hash-object -w --stdin returned unexpected object ID "
            f"{stored!r}; expected {expected}"
        )
        raise GitError(msg)
    run_git(
        root,
        ["update-ref", f"{_SNAPSHOT_REF_PREFIX}/{stored}", stored],
        "git update-ref for translation snapshot",
    )
    return stored
