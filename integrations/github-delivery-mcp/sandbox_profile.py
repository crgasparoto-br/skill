"""Versioned, immutable sandbox contract for Issue 88.

No caller-controlled shell flags, mounts, networks, or container privileges.
An independent trusted controller must validate image provenance and digest,
workspace ownership, cgroup enforcement and outbound-network policy.
"""
from dataclasses import dataclass
@dataclass(frozen=True)
class SandboxProfile:
    name: str = "offline-check-v1"
    network: str = "none"
    user: str = "65532:65532"
    memory_bytes: int = 536870912
    cpu_quota: float = 1.0
    pids_limit: int = 64
    tmpfs_bytes: int = 16777216
    read_only: bool = True
    drop_all_capabilities: bool = True
    no_new_privileges: bool = True
    socket_mounts_allowed: bool = False
    arbitrary_bind_mounts_allowed: bool = False
    privileged_allowed: bool = False
    allow_host_network: bool = False

    def validate(self) -> None:
        if (self.network != "none" or self.user != "65532:65532"
            or self.memory_bytes != 536870912 or self.cpu_quota != 1.0
            or self.pids_limit != 64 or self.tmpfs_bytes != 16777216
            or not self.read_only or not self.drop_all_capabilities
            or not self.no_new_privileges or self.socket_mounts_allowed
            or self.arbitrary_bind_mounts_allowed or self.privileged_allowed
            or self.allow_host_network):
            raise ValueError("sandbox profile must match reviewed offline contract")


OFFLINE_CHECK_V1 = SandboxProfile()
OFFLINE_CHECK_V1.validate()
