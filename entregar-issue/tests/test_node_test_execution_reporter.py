"""Exercise the paired native reporters through the real Node test runner."""
import json
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from node_grounding_execution import require_node_pass, verify_node_reporters

REPORTER = Path(__file__).resolve().parents[1] / "scripts" / "node_test_execution_reporter.mjs"


class NodeTestExecutionReporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node 24 runtime is unavailable")
        version = subprocess.check_output([cls.node, "--version"], text=True, timeout=10)
        if not version.startswith("v24."):
            raise unittest.SkipTest("This reporter adapter targets Node 24")

    def test_paired_reporters_record_file_identity_and_skipped_state(self):
        with tempfile.TemporaryDirectory() as directory:
            self.check_paired_reporters(Path(directory).resolve())

    def check_paired_reporters(self, tmp_path):
        check_paired_reporters(tmp_path, self.node)


def check_paired_reporters(tmp_path, node):
    source = """
        import { describe, test } from 'node:test';
        describe('outer', () => describe('inner', () => test('same name', () => {})));
        test('ordinary test', () => {});
        test('intentionally skipped', { skip: true }, () => {});
    """
    paths = [tmp_path / "one.test.mjs", tmp_path / "two.test.mjs"]
    for test_file in paths:
        test_file.write_text(source, encoding="utf-8")
    junit, log = tmp_path / "node.xml", tmp_path / "node.jsonl"
    result = subprocess.run([
        node, "--test", "--test-reporter=junit", f"--test-reporter={REPORTER.as_uri()}",
        f"--test-reporter-destination={junit}", f"--test-reporter-destination={log}",
        *(str(path) for path in paths),
    ], cwd=tmp_path, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    cases = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(cases) == 6
    assert {item["file"] for item in cases} == {str(path) for path in paths}
    assert all(item["entry_file"] == item["file"] for item in cases)
    assert all(item["schema_version"] == 1 and item["runner"] == "node:test" for item in cases)

    actual = {(e["file"], e["classname"], e["name"], e["status"]) for e in cases}
    expected = {
        (e.attrib["file"], e.attrib["classname"], e.attrib["name"],
         "skipped" if e.find("skipped") is not None else "passed")
        for e in ET.parse(junit).iter("testcase")
    }
    assert actual == expected
    assert len(actual) == 6
    assert sum(case["status"] == "skipped" for case in cases) == 2
    paired = verify_node_reporters(str(tmp_path), junit.read_bytes(), log.read_bytes())
    assert paired[("one.test.mjs", "outer.inner", "same name")] == "passed"
    assert paired[("two.test.mjs", "outer.inner", "same name")] == "passed"
    assert paired[("two.test.mjs", "test", "intentionally skipped")] == "skipped"
    assert len(paired) == 6
    require_node_pass(paired, source_file="one.test.mjs", classname="outer.inner", name="same name")
    with pytest.raises(ValueError, match="do not prove a passing execution"):
        require_node_pass(paired, source_file="two.test.mjs", classname="test", name="intentionally skipped")

