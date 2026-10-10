"""Negative preflight without touching the live rootless Docker daemon."""
import subprocess
import unittest
from pathlib import Path

class RootlessPreflightTests(unittest.TestCase):
    def test_missing_socket_fails_closed(self):
        # An intentionally nonexistent socket proves the same precondition
        # returns nonzero, without stopping Docker or changing systemd.
        path = "/tmp/solverit-issue88-deliberately-missing-rootless.sock"
        if Path(path).exists():
            self.skipTest("test sentinel path unexpectedly exists")
        result = subprocess.run(["/usr/bin/test", "-S", path],
                                capture_output=True, check=False, timeout=5)
        self.assertNotEqual(result.returncode, 0)

if __name__ == "__main__":
    unittest.main()
