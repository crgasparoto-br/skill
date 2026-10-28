#!/usr/bin/env python3
"""Official prepare -> literal replay -> derived closure orchestration, without publication."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from audit_artifact_io import load_json_artifact
from certificate_postcondition_replay import execute_replay, recognize_postconditions
from certificate_replay_io import json_bytes, read_object
from handoff_merge_preview import require_event_merge_preview
from handoff_postcondition import PROOF_KIND, file_metadata
from handoff_postcondition_records import finalize_records

if TYPE_CHECKING:
    from pathlib import Path


def material_event(event_path: Path, head: str, base: str) -> dict:
    event, _ = read_object(event_path)
    pr = event.get("pull_request") or {}
    if (pr.get("head") or {}).get("sha") != head or (pr.get("base") or {}).get("sha") != base:
        raise ValueError("postcondition event differs from the externally authenticated material/base")
    merge_preview = require_event_merge_preview(
        event_path, event["repository"]["full_name"], pr["number"], head, base)
    return {"repository": {"full_name": event["repository"]["full_name"]}, "pull_request": {
        "number": pr["number"], "merge_commit_sha": merge_preview,
        "base": {"sha": base, "ref": pr["base"]["ref"]},
        "head": {"sha": head, "repo": {"full_name": pr["head"]["repo"]["full_name"]}},
    }}


def prepare_replay_finalization(args, builder: list[str], resolved: dict[str, Path],
                                head: str, base: str, run_script) -> list[str]:
    """Return ordinary final builder arguments after real, fully verified replay."""
    source = resolved["audit_source_result"]
    plan = recognize_postconditions(source, args.root, head, expected_base=base)
    if not plan["items"]:
        return builder
    if "--phase" in builder or "--postcondition-proof" in builder:
        raise ValueError("postcondition orchestration requires an ordinary final builder invocation")
    audit = resolved["requirement_closure"].parent
    chain = audit / "postcondition"
    chain.mkdir(exist_ok=False)
    plan_path = chain / "plan.json"
    plan_path.write_bytes(json_bytes(plan))
    preparation = chain / "preparation.json"
    preparing = list(builder)
    preparing[preparing.index("--out") + 1] = str(preparation)
    run_script("build_handoff_certificate.py", *preparing, "--phase", "preparation",
               "--postcondition-plan", str(plan_path))
    event = chain / "replay-event.json"
    event.write_bytes(json_bytes(material_event(args.event, head, base)))
    receipts = {}
    (chain / "replay").mkdir()
    hosted = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    for index, item in enumerate(plan["items"]):
        key = item["source_kind"], item["source_id"]
        directory = chain / "replay" / f"{index:03d}"
        execute_replay(args.root, preparation, event, item["command"], plan["trusted_anchor_sha"],
                       output_dir=directory, source_kind=key[0], source_id=key[1],
                       expected_base=base, hosted_prefixes=hosted)
        receipts[key] = directory / "receipt.json"
    final = finalize_records(
        ledger=load_json_artifact(resolved["audit_remediation"], require_object=True),
        escape_closure=load_json_artifact(resolved["audit_escape_closure"], require_object=True),
        audit_result=source, plan_path=plan_path, preparation=preparation, event=event,
        receipts=receipts, repository=args.root, head_sha=head, expected_base=base)
    # No record changes before every replay is authenticated by the full verifier.
    for key, record in final.items():
        resolved[key].write_bytes(json_bytes(record))
    proof = {"schema_version": 1, "kind": PROOF_KIND,
             "preparation": file_metadata(preparation, audit), "plan": file_metadata(plan_path, audit),
             "event": file_metadata(event, audit),
             "receipts": [{"source_kind": key[0], "source_id": key[1], **file_metadata(path, audit)}
                          for key, path in sorted(receipts.items())]}
    proof_path = chain / "proof.json"
    proof_path.write_bytes(json_bytes(proof))
    return [*builder, "--postcondition-proof", str(proof_path)]
