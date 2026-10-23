"""JUnit candidate indexing must remain factual and fail closed."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_test_candidate_index.py"
spec = importlib.util.spec_from_file_location("build_test_candidate_index", SCRIPT)
assert spec and spec.loader
indexer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(indexer)
SHA = "a" * 40


def test_index_counts_without_approving_semantic_coverage(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite name="suite">'
        '<testcase classname="unit.workflow" name="happy"/>'
        '<testcase classname="unit.workflow" name="bad"><failure/></testcase>'
        '<testcase classname="unit.workflow" name="skip"><skipped/></testcase>'
        '</testsuite></testsuites>'
    )
    data = indexer.collect(report, SHA)
    assert data["subject_sha"] == SHA
    assert data["counts"] == {"passed": 1, "failure": 1, "error": 0, "skipped": 1}
    assert data["requirement_mapping"] == "UNKNOWN"
    assert data["certification"] == "NOT_ASSERTED"
    assert len(data["source"]["sha256"]) == 64


@pytest.mark.parametrize("text,expected", [
    ('<testsuites/>', "empty"),
    ('<testsuite><testcase name="test"/></testsuite>', "classname"),
    ('<testsuite><testcase classname="a" name="x"/>'
     '<testcase classname="a" name="x"/></testsuite>', "duplicate"),
    ('<root/>', "root"),
])
def test_index_rejects_incomplete_junit(tmp_path, text, expected):
    file = tmp_path / "junit.xml"
    file.write_text(text)
    with pytest.raises(ValueError, match=expected):
        indexer.collect(file, SHA)


def test_index_rejects_invalid_sha_and_missing_file(tmp_path):
    with pytest.raises(ValueError, match="SHA"):
        indexer.collect(tmp_path / "missing.xml", "short")
    with pytest.raises(ValueError, match="JUnit"):
        indexer.collect(tmp_path / "missing.xml", SHA)
