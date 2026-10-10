"""Durable job metadata for a separate delivery control plane.

This module neither executes repository code nor holds GitHub credentials.
Caller must enforce OAuth authorization on *every* read and write before use.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
TRANSITIONS = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "cancelled", "timed_out"}),
    "failed": frozenset({"queued"}),
    "timed_out": frozenset({"queued"}),
    "cancelled": frozenset(),
    "succeeded": frozenset(),
}
SAFE_FIELDS = frozenset({"job_id", "repo", "issue_number", "branch",
                         "base_sha", "expected_head", "correlation_id", "status",
                         "created_at", "updated_at"})


class JobConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class Job:
    job_id: str
    repo: str
    issue_number: int
    branch: str
    base_sha: str
    expected_head: str
    correlation_id: str
    status: str
    created_at: int
    updated_at: int


class JobStore:
    def __init__(self, database_path: str):
        self.path = database_path
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
              job_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
              idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
              repo TEXT NOT NULL, issue_number INTEGER NOT NULL,
              branch TEXT NOT NULL, base_sha TEXT NOT NULL,
              expected_head TEXT NOT NULL, correlation_id TEXT NOT NULL,
              status TEXT NOT NULL, created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              UNIQUE(actor, idempotency_key)
            )""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _public(row):
        return Job(**{field: row[field] for field in SAFE_FIELDS})

    def create(self, *, actor: str, key: str, payload_hash: str, repo: str,
               issue_number: int, branch: str, base_sha: str,
               expected_head: str) -> Job:
        if not actor or not key or len(key) > 128 or len(payload_hash) != 64:
            raise ValueError("invalid identity or idempotency contract")
        if issue_number <= 0:
            raise ValueError("invalid issue number")
        now = int(time.time())
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM jobs WHERE actor=? AND idempotency_key=?",
                (actor, key),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise JobConflict("idempotency key reused with different payload")
                return self._public(existing)
            job_id = str(uuid.uuid4())
            correlation_id = str(uuid.uuid4())
            db.execute("""INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (job_id, actor, key, payload_hash, repo, issue_number,
                        branch, base_sha, expected_head, correlation_id,
                        "queued", now, now))
            return self._public(db.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,),
            ).fetchone())

    def read(self, job_id: str, actor: str) -> Job:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE job_id=? AND actor=?", (job_id, actor)
            ).fetchone()
            if row is None:
                raise KeyError("job not found")
            return self._public(row)

    def transition(self, job_id: str, actor: str, expected: str, target: str) -> Job:
        if target not in TRANSITIONS.get(expected, ()):
            raise JobConflict("invalid job transition")
        with self._connect() as db:
            updated = db.execute(
                """UPDATE jobs SET status=?, updated_at=?
                WHERE job_id=? AND actor=? AND status=?""",
                (target, int(time.time()), job_id, actor, expected),
            )
            if updated.rowcount != 1:
                raise JobConflict("job transition conflict")
            return self._public(db.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone())

    def recover_interrupted(self) -> int:
        """Mark interrupted running jobs timed_out; never silently replay writes."""
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status='timed_out', updated_at=? WHERE status='running'",
                (int(time.time()),),
            )
            return cursor.rowcount
