"""Read authenticated Git object bytes or prove exact-path absence at a pinned commit."""
from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def git_run(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repository), *arguments],
        check=True, capture_output=True,
    ).stdout


def material_parent_blob(repository: Path, material: str, relative: str) -> bytes | None:
    """Read only regular blobs; absent tree entries are different from Git failure."""
    if not re.fullmatch(r"[0-9a-f]{40}", material):
        raise ValueError("Git tree verification requires exact 40-character SHA")
    if (not relative or relative.startswith("/") or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise ValueError("unsafe Git tree path")
    git_run(repository, "cat-file", "-e", material + "^{commit}")
    parts = relative.split("/")
    entry = []
    for index in range(1, len(parts) + 1):
        name = "/".join(parts[:index])
        result = git_run(repository, "ls-tree", "-z", material, "--", name)
        if not result:
            return None
        metadata, observed = result.removesuffix(b"\0").split(b"\t", 1)
        entry = metadata.decode("ascii").split()
        if observed.decode("utf-8") != name or len(entry) != 3:
            raise ValueError("Git tree returned an unexpected entry")
        expected = {"040000"} if index < len(parts) else {"100644", "100755"}
        kind = "tree" if index < len(parts) else "blob"
        if entry[0] not in expected or entry[1] != kind:
            raise ValueError(f"unsafe Git type or symlink: {name}")
    return git_run(repository, "cat-file", "blob", entry[2])
