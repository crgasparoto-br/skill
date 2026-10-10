"""Offline policy invariants: profiles cannot silently weaken confinement."""
import unittest
from dataclasses import replace

from sandbox_profile import OFFLINE_CHECK_V1


class SandboxProfileTests(unittest.TestCase):
    def test_reviewed_defaults(self):
        OFFLINE_CHECK_V1.validate()

    def test_downgrades_rejected(self):
        changes = [
            {"network": "bridge"}, {"network": "host"},
            {"user": "0:0"}, {"memory_bytes": 0}, {"cpu_quota": 0},
            {"pids_limit": 0}, {"tmpfs_bytes": 1024 * 1024 * 1024},
            {"read_only": False}, {"drop_all_capabilities": False},
            {"no_new_privileges": False}, {"socket_mounts_allowed": True},
            {"arbitrary_bind_mounts_allowed": True},
            {"privileged_allowed": True}, {"allow_host_network": True},
        ]
        for kwargs in changes:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(OFFLINE_CHECK_V1, **kwargs).validate()


if __name__ == "__main__":
    unittest.main()
