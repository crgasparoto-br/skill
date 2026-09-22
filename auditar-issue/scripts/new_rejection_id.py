#!/usr/bin/env python3
"""Create one stable identifier for an independent audit rejection event."""
from uuid import uuid4


def main() -> int:
    print(f"audit-rejection:{uuid4()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
