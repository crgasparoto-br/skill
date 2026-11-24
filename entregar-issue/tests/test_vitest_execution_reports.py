from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from vitest_execution_reports import (
    collect_vitest_observations,
    require_unique_vitest_pass,
)

RUNNER_ROOT = "/workspace/test-project"
ROWS = {
    "tests/first.test.js": [
        ([], "same title", "passed"),
        (["outer", "nested"], "skipped case", "skipped"),
        (["outer", "nested"], "todo case", "todo"),
    ],
    "tests/second.test.js": [
        ([], "same title", "passed"),
        (["parameterized"], "repeated title", "passed"),
        (["parameterized"], "repeated title", "passed"),
    ],
}


def native_output_pair():
    total = sum(map(len, ROWS.values()))
    root = ET.Element("testsuites", name="vitest tests", tests=str(total), errors="0", failures="0")
    files = []
    passed = 0
    for path, cases in ROWS.items():
        junit_suite = ET.SubElement(root, "testsuite", name=path, tests=str(len(cases)),
                                   skipped=str(sum(status != "passed" for _, _, status in cases)),
                                   errors="0", failures="0")
        assertions = []
        for parents, title, status in cases:
            case = ET.SubElement(junit_suite, "testcase", classname=path,
                                 name=" > ".join([*parents, title]))
            if status != "passed":
                ET.SubElement(case, "skipped")
            else:
                passed += 1
            assertions.append({"ancestorTitles": parents, "title": title, "status": status})
        files.append({"name": f"{RUNNER_ROOT}/{path}", "status": "passed", "assertionResults": assertions})
    report = {"success": True, "numTotalTests": total, "numPassedTests": passed, "numFailedTests": 0,
              "testResults": files}
    return ET.tostring(root, encoding="utf-8"), report


def collect(junit, report):
    return collect_vitest_observations(junit=junit, runner_json=json.dumps(report).encode(),
                                       runner_root=RUNNER_ROOT)


def test_native_reports_keep_source_order_nested_labels_and_skips():
    observations = collect(*native_output_pair())
    require_unique_vitest_pass(observations, "tests/first.test.js", "same title")
    require_unique_vitest_pass(observations, "tests/second.test.js", "same title")
    assert observations["tests/first.test.js", "outer > nested > skipped case"] == ("skipped",)
    assert observations["tests/first.test.js", "outer > nested > todo case"] == ("skipped",)
    assert observations["tests/second.test.js", "parameterized > repeated title"] == ("passed", "passed")


@pytest.mark.parametrize(("path", "title"), [
    ("tests/first.test.js", "outer > nested > skipped case"),
    ("tests/second.test.js", "parameterized > repeated title"),
    ("tests/third.test.js", "same title"),
])
def test_grounding_requires_one_named_case_that_passed(path, title):
    with pytest.raises(ValueError, match="unambiguous passed case"):
        require_unique_vitest_pass(collect(*native_output_pair()), path, title)


def test_native_reports_must_agree_on_case_order_in_each_source():
    junit, report = native_output_pair()
    cases = report["testResults"][0]["assertionResults"]
    cases.reverse()
    with pytest.raises(ValueError, match="native reports disagree"):
        collect(junit, report)


def test_native_reports_must_agree_on_source_identity():
    junit, report = native_output_pair()
    report["testResults"][0]["name"] = f"{RUNNER_ROOT}/tests/another.test.js"
    with pytest.raises(ValueError, match="native reports disagree"):
        collect(junit, report)
