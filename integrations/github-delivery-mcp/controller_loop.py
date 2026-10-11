"""Bounded, recover-only controller loop; no network or GitHub write.

Each cycle acquires the same exclusive controller lock used by local checks,
then reconciles interrupted work. Signals stop only after the active cycle.
This is not a delivery scheduler; prepared jobs are never replayed.
"""
from __future__ import annotations

import os
import signal
import threading
import time

from controller_lock import controller_lock
from local_recovery import recover_local_jobs


def run_recovery_loop(*, database_path: str, lock_path: str,
                      interval_seconds: int = 60, stop_event=None,
                      on_cycle=None) -> None:
    if os.geteuid() != 1004:
        raise PermissionError("dedicated worker required")
    if not isinstance(interval_seconds, int) or not 10 <= interval_seconds <= 3600:
        raise ValueError("interval must be 10..3600 seconds")
    stop = stop_event if stop_event is not None else threading.Event()
    while not stop.is_set():
        with controller_lock(lock_path):
            count = recover_local_jobs(database_path)
        if on_cycle is not None:
            on_cycle(count)
        stop.wait(interval_seconds)


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    stop = threading.Event()

    def request_stop(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    run_recovery_loop(
        database_path=args.database, lock_path=args.lock,
        interval_seconds=args.interval, stop_event=stop,
        on_cycle=lambda n: print(json.dumps({"recovered_jobs": n}), flush=True),
    )


if __name__ == "__main__":
    main()
