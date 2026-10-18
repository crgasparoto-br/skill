"""Durable, actor-bound verification evidence; no credentials or raw command output.

Only a trusted controller may record observations after actual rootless checks.
This module does not authorize execution or publication on its own.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from jobs import JobStore

_SHA = re.compile(r"^[0-9a-f]{40}$")
_CHECKS = frozenset({"integrity-v1", "posix-shell-syntax-v1", "bash-syntax-v1"})
_IMAGES = {
    "bash-syntax-v1": "bash@sha256:a54fb4422b18f05dd3107c36f39d67b26334fda7ec89f4126052b45e228e2f15",
    "integrity-v1": "alpine:3.20",
    "posix-shell-syntax-v1": "alpine:3.20",
}


@dataclass(frozen=True)
class CheckEvidence:
    check: str
    base_sha: str
    image: str
    passed: bool
    timed_out: bool
    recorded_at: int


class CheckEvidenceStore:
    def __init__(self, database_path: str):
        self.jobs = JobStore(database_path)
        self.path = database_path
        with self.jobs._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS check_evidence (
                job_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                check_name TEXT NOT NULL,
                base_sha TEXT NOT NULL,
                image TEXT NOT NULL,
                passed INTEGER NOT NULL,
                timed_out INTEGER NOT NULL,
                recorded_at INTEGER NOT NULL,
                PRIMARY KEY(job_id, check_name),
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            )""")

    def record(self, *, job_id: str, actor: str, check: str, base_sha: str,
               image: str, passed: bool, timed_out: bool = False) -> CheckEvidence:
        job = self.jobs.read(job_id, actor)
        if job.status != "prepared":
            raise PermissionError("job is not prepared for checks")
        if (check not in _CHECKS or image != _IMAGES[check]
                or not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha)
                or base_sha != job.base_sha or type(passed) is not bool
                or type(timed_out) is not bool or (passed and timed_out)):
            raise ValueError("invalid verification evidence")
        with self.jobs._connect() as db:
            if db.execute("SELECT 1 FROM check_evidence WHERE job_id=? AND check_name=?",
                          (job_id, check)).fetchone():
                raise PermissionError("check evidence is immutable")
            now = int(time.time())
            db.execute("""INSERT INTO check_evidence
                (job_id, actor, check_name, base_sha, image, passed, timed_out, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, actor, check, base_sha, image, int(passed), int(timed_out), now))
        return CheckEvidence(check, base_sha, image, passed, timed_out, now)

    def list_for_owner(self, job_id: str, actor: str) -> tuple[CheckEvidence, ...]:
        self.jobs.read(job_id, actor)
        with self.jobs._connect() as db:
            rows = db.execute("""SELECT check_name, base_sha, image, passed,
                timed_out, recorded_at FROM check_evidence
                WHERE job_id=? AND actor=? ORDER BY check_name""",
                (job_id, actor)).fetchall()
        return tuple(CheckEvidence(r["check_name"], r["base_sha"], r["image"],
                                   bool(r["passed"]), bool(r["timed_out"]),
                                   r["recorded_at"]) for r in rows)

    def require_checks(self, job_id: str, actor: str) -> None:
        job = self.jobs.read(job_id, actor)
        results = {x.check: x for x in self.list_for_owner(job_id, actor)}
        if any(check not in results or not results[check].passed
               or results[check].timed_out or results[check].base_sha != job.base_sha
               for check in _CHECKS):
            raise PermissionError("required check evidence missing or failed")
