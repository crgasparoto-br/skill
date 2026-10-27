#!/usr/bin/env python3
"""Bounded data IO and fresh literal paths; this layout is not a security sandbox."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

from audit_artifact_io import ARTIFACT_FORMAT, artifact_metadata, load_json_artifact

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_INVENTORY_BYTES = 128 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("invalid replay artifact path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != value:
        raise ValueError("noncanonical replay artifact path")
    return value


def identity(path: Path) -> tuple[int, int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino, info.st_mode


def open_directory(path: Path) -> int:
    path = path.absolute()
    if ".." in path.parts:
        raise ValueError("replay input contains traversal")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        return parent
    except BaseException:
        os.close(parent)
        raise


def safe_read(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    """Open every component without following links and detect replacement during read."""
    parent = open_directory(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError("replay input is not a bounded regular file")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(raw) > limit or any(getattr(before, key) != getattr(row, key) for key in fields for row in (after, current)):
            raise ValueError("replay input changed during read")
        return raw
    finally:
        os.close(parent)


def read_object(path: Path) -> tuple[dict, bytes]:
    raw = safe_read(path)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("replay input must be a JSON object")
    return value, raw


def read_artifact(path: Path) -> tuple[dict, bytes, dict]:
    """Authenticate bounded physical inputs before decoding their existing transport."""
    value, raw = read_object(path)
    files, total = {path.name: raw}, len(raw)
    if value.get("artifact_format") == ARTIFACT_FORMAT:
        parts = value.get("parts")
        if not isinstance(parts, list) or not 1 <= len(parts) <= 512:
            raise ValueError("replay artifact part inventory exceeds its bound")
        for item in parts:
            if not isinstance(item, dict):
                raise ValueError("invalid replay artifact part")
            name = relative_path(item.get("path"))
            if name in files:
                raise ValueError("duplicate replay artifact part")
            files[name] = safe_read(path.parent / name)
            total += len(files[name])
            if total > MAX_INVENTORY_BYTES:
                raise ValueError("replay artifact transport exceeds its bound")
    with tempfile.TemporaryDirectory(prefix="authenticated-replay-artifact-") as folder:
        for name, content in files.items():
            target = Path(folder) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        target = Path(folder) / path.name
        metadata = artifact_metadata(target)
        logical = load_json_artifact(target, require_object=True)
    if any(safe_read(path.parent / name) != content for name, content in files.items()):
        raise ValueError("replay artifact changed during authentication")
    return logical, raw, metadata


def clean_environment() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "TZ": "UTC",
            "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def run_gate(argv: list[str]) -> tuple[int, bytes]:
    deadline, output = time.monotonic() + 30, bytearray()
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          env=clean_environment(), cwd="/", start_new_session=True) as child:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("literal replay exceeded its time bound")
                    if not selector.select(remaining):
                        continue
                    chunk = os.read(child.stdout.fileno(), min(65536, MAX_LOG_BYTES + 1 - len(output)))
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > MAX_LOG_BYTES:
                        raise ValueError("replay log exceeds its bound")
            return child.wait(timeout=max(0.01, deadline - time.monotonic())), bytes(output)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise


class FreshLayout:
    """Create absent targets, tracking exact inodes; remove only entries we created."""

    def __init__(self, files: dict[Path, bytes], evidence: Path, interpreter: Path, hosted: bool):
        self.files, self.evidence, self.interpreter = files, evidence, interpreter
        self.runtime = Path(sys.executable).resolve(strict=True)
        self.data_root = Path(os.path.commonpath([str(path.parent) for path in files]))
        self.hosted = hosted
        self.known: dict[Path, tuple[int, int, int]] = {}
        self.created: list[tuple[Path, tuple[int, int, int], bool]] = []
        self.privileged: set[Path] = set()

    def _runtime_targets(self) -> list[Path]:
        if self.interpreter.exists() or self.interpreter.is_symlink():
            if (self.interpreter not in {Path(sys.executable).absolute(), self.runtime}
                    or self.interpreter.resolve(strict=True) != self.runtime):
                raise ValueError("literal interpreter is not the trusted running Python")
            return []
        if (not self.interpreter.is_relative_to(self.data_root)
                and not self.interpreter.is_relative_to(Path("/opt/codex/runtimes"))):
            raise ValueError("missing literal interpreter is outside the dedicated runtime prefix")
        if self.interpreter.parent.name != "bin" or not re.fullmatch(r"python(?:3(?:\.\d+)?)?", self.interpreter.name):
            raise ValueError("missing literal interpreter must name Python in a bin directory")
        prefix = self.interpreter.parent.parent
        if prefix.exists() or prefix.is_symlink() or any(path.is_relative_to(prefix) for path in self.files):
            raise ValueError("literal interpreter requires an entirely new dedicated Python prefix")
        return [self.interpreter]

    def plan(self) -> None:
        allowed = (Path("/workspace"), Path("/tmp"), Path("/var/tmp"))
        if not any(self.data_root != root and self.data_root.is_relative_to(root) for root in allowed):
            raise ValueError("literal replay data requires a dedicated workspace or temporary prefix")
        if self.data_root.exists() or self.data_root.is_symlink():
            raise ValueError("literal replay data prefix already exists")
        targets = [*self.files, self.evidence, *self._runtime_targets()]
        if self.hosted and (os.environ.get("GITHUB_ACTIONS") != "true"
                            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"):
            raise ValueError("privileged prefix creation requires an explicit hosted runner")
        for path in targets:
            if not path.is_absolute() or path.as_posix() != str(path) or ".." in path.parts:
                raise ValueError("literal replay requires canonical absolute paths")
            if path.exists() or path.is_symlink():
                raise ValueError(f"literal replay destination already exists: {path}")
            for parent in reversed(path.parents):
                if parent.exists() or parent.is_symlink():
                    observed = identity(parent)
                    if not stat.S_ISDIR(observed[2]):
                        raise ValueError("literal replay ancestor is a symlink or non-directory")
                    self.known[parent] = observed

    def _sudo(self, program: str, *args: str) -> None:
        if not self.hosted:
            raise ValueError("literal replay layout is unavailable without privileged prefix creation")
        subprocess.run(["/usr/bin/sudo", "-n", "--", "/usr/bin/" + program, *args],
                       check=True, capture_output=True, env=clean_environment(), timeout=15)

    def _remember(self, path: Path, directory: bool) -> None:
        observed = identity(path)
        self.created.append((path, observed, directory))
        if directory:
            self.known[path] = observed

    def _parents(self, path: Path) -> None:
        for parent in reversed(path.parents):
            if parent in self.known:
                if identity(parent) != self.known[parent]:
                    raise ValueError("literal replay ancestor changed after preflight")
                continue
            try:
                parent.mkdir(mode=0o700)
            except PermissionError:
                self._sudo("mkdir", "-m", "0700", "--", str(parent))
                self.privileged.add(parent)
                self._remember(parent, True)
                self._sudo("chown", "--no-dereference", f"{os.getuid()}:{os.getgid()}", "--", str(parent))
            else:
                self._remember(parent, True)

    def create(self) -> None:
        for path, raw in self.files.items():
            self._parents(path)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
            self._remember(path, False)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
            if safe_read(path) != raw:
                raise ValueError("literal replay materialization changed bytes")
        if not self.interpreter.exists():
            self._parents(self.interpreter)
            self.interpreter.symlink_to(self.runtime)
            self._remember(self.interpreter, False)

    def cleanup(self) -> None:
        errors = []
        for path, expected, directory in reversed(self.created):
            try:
                if any(identity(parent) != self.known[parent] for parent in path.parents if parent in self.known):
                    raise ValueError("owned replay ancestor changed before cleanup")
                if identity(path) != expected:
                    raise ValueError("owned replay path changed before cleanup")
                if directory:
                    try:
                        path.rmdir()
                    except PermissionError:
                        if path not in self.privileged:
                            raise
                        self._sudo("rmdir", "--", str(path))
                else:
                    path.unlink()
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                errors.append(f"{path}: {exc}")
        if errors:
            raise ValueError("replay cleanup blocked: " + "; ".join(errors))


@contextlib.contextmanager
def fresh_layout(files: dict[Path, bytes], evidence: Path, interpreter: Path, hosted: bool = False):
    layout = FreshLayout(files, evidence, interpreter, hosted)
    layout.plan()  # Check every destination before the first write.
    try:
        layout.create()
        yield layout
    finally:
        layout.cleanup()
