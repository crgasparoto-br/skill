"""Single-process controller gate for the local offline Issue 88 pilot.

Acquire an exclusive nonblocking flock on a dedicated persistent lock file.
Keep its file descriptor open throughout startup reconciliation and dispatch.
Never replace or remove the lock file: unlinking breaks flock exclusivity.
This does not replace distributed leases in a future multi-host controller.
"""
from __future__ import annotations
import fcntl
import os
from contextlib import contextmanager

@contextmanager
def controller_lock(lock_path: str):
    parent = os.path.dirname(os.path.abspath(lock_path))
    if not os.path.isdir(parent):
        raise FileNotFoundError("controller lock directory does not exist")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(fd)
        if not os.path.isfile(lock_path) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
            raise PermissionError("unsafe lock file ownership or permissions")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another controller holds the lock") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
