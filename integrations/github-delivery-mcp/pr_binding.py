"""Durable job-to-PR correlation; not publication or audit evidence.

Only a trusted publication broker may call bind_published_pr after comparing
the GitHub response with the authorized job. This store alone grants no success.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from jobs import JobConflictError, JobStore

_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class PRBinding:
    job_id: str
    pr_number: int
    head_sha: str
    recorded_at: int


class PRBindingStore:
    def __init__(self, database_path: str):
        self.jobs = JobStore(database_path)
        with self.jobs._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS job_pr_bindings (
                job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                pr_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL,
                recorded_at INTEGER NOT NULL
            )""")

    def bind_published_pr(self, *, job_id: str, actor: str, pr_number: int,
                          head_sha: str) -> PRBinding:
        job = self.jobs.read(job_id, actor)
        if job.status != "prepared":
            raise JobConflictError("only prepared jobs can bind a PR")
        if (type(pr_number) is not int or pr_number <= 0
                or not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha)
                or head_sha != job.expected_head or head_sha == job.base_sha
                or job.branch in ("develop", "main")):
            raise ValueError("invalid PR binding identity")
        with self.jobs._connect() as db:
            row = db.execute("SELECT pr_number, head_sha, recorded_at FROM job_pr_bindings WHERE job_id=?",
                             (job_id,)).fetchone()
            if row is not None:
                if row["pr_number"] != pr_number or row["head_sha"] != head_sha:
                    raise JobConflictError("immutable PR binding mismatch")
                return PRBinding(job_id, pr_number, head_sha, row["recorded_at"])
            recorded_at = int(time.time())
            db.execute("INSERT INTO job_pr_bindings VALUES (?,?,?,?)",
                       (job_id, pr_number, head_sha, recorded_at))
            return PRBinding(job_id, pr_number, head_sha, recorded_at)

    def read(self, *, job_id: str, actor: str) -> PRBinding:
        self.jobs.read(job_id, actor)
        with self.jobs._connect() as db:
            row = db.execute("SELECT * FROM job_pr_bindings WHERE job_id=?",
                             (job_id,)).fetchone()
        if row is None:
            raise KeyError("PR binding not found")
        return PRBinding(row["job_id"], row["pr_number"], row["head_sha"], row["recorded_at"])
