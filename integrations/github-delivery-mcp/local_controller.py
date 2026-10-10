"""Local controller pilot: exclusive lock -> reconcile -> optional offline check.

Not network-facing. Does not handle GitHub credentials, patching or PRs.
All invocations must use same persistent lock file. Production integration
must enforce this invariant in every dispatch and recovery path.
"""
from __future__ import annotations

import json
import os

import argparse
from controller_lock import controller_lock
from local_job_runner import submit_offline_smoke
from local_recovery import recover_local_jobs
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--smoke-key", help="Optional unique local smoke idempotency key")
    args = parser.parse_args()
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

if __name__ == "__main__":
    main()
