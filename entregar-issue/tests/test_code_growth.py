from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_code_growth.py"
POLICY = ".github/code-growth-policy.json"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def lines(count: int) -> str:
    return "".join(f"x{index} = {index}\n" for index in range(count))


class Candidate:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.repo = tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")

    def commit(self, files: dict[str, str | None]) -> str:
        for path, text in files.items():
            target = self.repo / path
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "c")
        return git(self.repo, "rev-parse", "HEAD")

    def check(self, base: str, head: str, justifications: dict[str, str] | None = None):
        out = self.tmp / "code-growth.json"
        cmd = [sys.executable, str(SCRIPT), "--repo", str(self.repo), "--base-sha", base, "--head-sha", head, "--out", str(out)]
        if justifications is not None:
            path = self.tmp / "justifications.json"
            path.write_text(json.dumps(justifications), encoding="utf-8")
            cmd += ["--justifications", str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() and proc.returncode in (0, 2) and "invalid" not in proc.stdout else None
        return proc, report


@pytest.fixture()
def candidate(tmp_path: Path) -> Candidate:
    return Candidate(tmp_path)


@pytest.mark.parametrize("size, justified, blocked", [
    (300, False, False),
    (301, False, True),
    (301, True, False),
    (500, True, False),
    (501, True, True),
])
def test_new_file_limits(candidate, size, justified, blocked):
    base = candidate.commit({"README.md": "base\n"})
    head = candidate.commit({"src/service.py": lines(size)})
    proc, report = candidate.check(base, head, {"src/service.py": "tabela de dominio indivisivel"} if justified else None)
    assert proc.returncode == (2 if blocked else 0), proc.stdout
    assert report["control_id"] == "CODE-GROWTH-001"
    assert report["status"] == ("blocked" if blocked else "passed")
    assert report["subject_sha"] == head
    assert bool(report["blocking_files"]) is blocked
    assert report["policy"]["source"] == "default"


@pytest.mark.parametrize("before, after, blocked", [
    (480, 500, False),
    (480, 501, True),
    (800, 820, False),
    (800, 821, True),
    (800, 600, False),
])
def test_existing_file_growth(candidate, before, after, blocked):
    base = candidate.commit({"src/service.py": lines(before)})
    head = candidate.commit({"src/service.py": lines(after)})
    proc, report = candidate.check(base, head)
    assert proc.returncode == (2 if blocked else 0), proc.stdout
    assert report["files"] == [{"path": "src/service.py", "lines_before": before, "lines_after": after}]


def test_tests_generated_vendor_and_non_code_are_exempt(candidate):
    base = candidate.commit({"README.md": "base\n"})
    head = candidate.commit({
        "tests/test_service.py": lines(900),
        "src/generated/client.py": lines(900),
        "vendor/lib/big.py": lines(900),
        "docs/guide.md": lines(900),
        "src/small.py": lines(10),
    })
    proc, report = candidate.check(base, head)
    assert proc.returncode == 0, proc.stdout
    assert [item["path"] for item in report["files"]] == ["src/small.py"]


def test_policy_is_read_from_base_and_candidate_cannot_loosen_it(candidate):
    strict = json.dumps({"new_file_soft_limit": 50, "new_file_hard_limit": 100})
    loose = json.dumps({"new_file_soft_limit": 5000, "new_file_hard_limit": 5000})
    base = candidate.commit({POLICY: strict})
    head = candidate.commit({POLICY: loose, "src/service.py": lines(150)})
    proc, report = candidate.check(base, head)
    assert proc.returncode == 2
    assert report["policy"]["new_file_hard_limit"] == 100
    assert report["policy"]["source"] == f"{base}:{POLICY}"

    relaxed_base = candidate.commit({POLICY: loose, "src/service.py": None})
    relaxed_head = candidate.commit({"src/service.py": lines(150)})
    proc, report = candidate.check(relaxed_base, relaxed_head)
    assert proc.returncode == 0, proc.stdout


@pytest.mark.parametrize("policy", [
    '{"new_file_soft_limit": 600, "new_file_hard_limit": 500}',
    '{"new_file_hard_limit": "500"}',
    '{"unknown_key": 1}',
    'not json',
])
def test_invalid_base_policy_blocks_instead_of_falling_back(candidate, policy):
    base = candidate.commit({POLICY: policy})
    head = candidate.commit({"src/service.py": lines(10)})
    proc, _ = candidate.check(base, head)
    assert proc.returncode == 2
    assert "invalid code-growth policy" in proc.stdout


def test_missing_commit_is_unknown_not_approval(candidate):
    base = candidate.commit({"README.md": "base\n"})
    proc, _ = candidate.check(base, "0" * 40)
    assert proc.returncode == 3
    assert proc.stdout.startswith("UNKNOWN")


def test_report_is_accepted_by_auditor_preflight_check(candidate):
    base = candidate.commit({"README.md": "base\n"})
    head = candidate.commit({"src/service.py": lines(10)})
    candidate.check(base, head)
    auditor = ROOT.parent / "auditar-issue" / "scripts" / "check_code_growth_evidence.py"
    proc = subprocess.run([sys.executable, str(auditor), "--report", str(candidate.tmp / "code-growth.json"), "--head-sha", head], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_gate_is_registered_and_documented():
    registry = json.loads((ROOT / "contracts" / "gate-registry.json").read_text(encoding="utf-8"))
    gate = next(item for item in registry["gates"] if item["id"] == "code-growth")
    assert gate["controls"] == ["CODE-GROWTH-001"]
    assert gate["activate_when"] == {"kind": "classification", "field": "code_touched", "equals": True}
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "references/code-growth-gate.md" in skill and "scripts/check_code_growth.py" in skill
    reference = (ROOT / "references" / "code-growth-gate.md").read_text(encoding="utf-8")
    assert "somente do `work_item_start_sha`" in reference
