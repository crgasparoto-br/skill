"""Local controller pilot: exclusive lock -> reconcile -> optional offline check.

Not network-facing. Does not handle GitHub credentials, patching or PRs.
All invocations must use same persistent lock file. Production integration
must enforce this invariant in every dispatch and recovery path.
"""
from __future__ import annotations

import argparse
import json
import os

from controller_lock import controller_lock
from local_job_runner import submit_offline_smoke
from local_recovery import recover_local_jobs
from locked_check_dispatch import dispatch_locked_checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--smoke-key", help="Optional unique local smoke idempotency key")
    parser.add_argument("--check-job", help="Existing prepared job ID for local checks")
    parser.add_argument("--check-actor", help="Trusted local job owner")
    parser.add_argument("--check-snapshot", help="Existing trusted snapshot directory")
    args = parser.parse_args()
    checks = (args.check_job, args.check_actor, args.check_snapshot)
    if any(checks) and not all(checks):
        parser.error("all three --check-* arguments are required")
    if all(checks) and args.smoke_key:
        parser.error("--smoke-key cannot be combined with job checks")
    if os.geteuid() != 1004:
        raise PermissionError("solverit-worker is required")
    with controller_lock(args.lock):
        recovered = recover_local_jobs(args.database)
        print(json.dumps({"recovered_jobs": recovered}))
        if args.smoke_key:
            result = submit_offline_smoke(args.database, actor="local-smoke-operator",
                                          idempotency_key=args.smoke_key)
            print(json.dumps({"job_id": result.job_id, "status": result.status,
                              "exit_code": result.exit_code, "output": result.output}))
            if result.status != "succeeded":
                raise RuntimeError("smoke job did not succeed")
    # The dispatcher owns the SAME lock for the entire rootless check cycle.
    # Never acquire controller_lock here again (flock would deadlock/reject).
    # A second controller may intervene between recovery and dispatch, but
    # dispatch_locked_checks re-reads job status while holding that lock.
    if all(checks):
        evidence = dispatch_locked_checks(
            database_path=args.database, lock_path=args.lock,
            job_id=args.check_job, actor=args.check_actor,
            snapshot_dir=args.check_snapshot,
        )
        print(json.dumps({"job_id": args.check_job, "checks": [
            {"name": x.check, "passed": x.passed, "timed_out": x.timed_out}
            for x in evidence]}))

if __name__ == "__main__":
    main()
