#!/usr/bin/env python3
"""Classify whether existing entregar-issue artifacts belong to the current delivery target.

This is intentionally a preflight classifier, not a correctness validator. Its job is to
prevent `.audit/entregar-issue` files inherited from a base branch or another PR/issue
from being reused as if they belonged to the current delivery.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from audit_artifact_io import load_json_artifact

DEFAULT_AUDIT_DIR = Path('.audit/entregar-issue')
IDENTITY_ARTIFACTS = ('handoff-ready.json', 'specification-snapshot.json')


def _load_json(path: Path) -> dict[str, Any]:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f'expected JSON object: {path}')
    return value


def _compare(label: str, observed: Any, expected: Any, reasons: list[str]) -> None:
    if expected is None:
        return
    if observed != expected:
        reasons.append(f'{label} differs: observed={observed!r} expected={expected!r}')


def _git_blob(repository_path: Path, base_sha: str, repo_relative_path: str) -> bytes | None:
    """Read one path exactly as stored at base_sha without mutating the checkout."""
    proc = subprocess.run(
        ['git', '-C', str(repository_path), 'show', f'{base_sha}:{repo_relative_path}'],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _base_origin(
    *,
    audit_dir: Path,
    repository_path: Path | None,
    base_sha: str | None,
    base_audit_dir: Path | None = None,
) -> dict[str, Any]:
    """Determine whether identity artifacts in the head are byte-identical to the exact base.

    This check is deliberately exact-SHA and byte-based. Semantic equality is insufficient:
    a head-produced foreign certificate must not be mistaken for an inherited base artifact.
    """
    present = [name for name in IDENTITY_ARTIFACTS if (audit_dir / name).is_file()]
    result: dict[str, Any] = {
        'checked': False,
        'base_sha': base_sha,
        'present_identity_artifacts': present,
        'inherited_paths': [],
        'all_present_identity_artifacts_inherited': False,
        'comparison_mode': None,
    }
    if not present:
        return result

    inherited: list[str] = []
    if base_audit_dir is not None:
        base_audit_dir = base_audit_dir.resolve()
        result['checked'] = True
        result['comparison_mode'] = 'materialized-base'
        for name in present:
            current_path = audit_dir / name
            base_path = base_audit_dir / name
            if base_path.is_file() and current_path.read_bytes() == base_path.read_bytes():
                inherited.append(name)
    elif repository_path is not None and base_sha:
        repository_path = repository_path.resolve()
        try:
            relative_audit_dir = audit_dir.resolve().relative_to(repository_path)
        except ValueError:
            result['error'] = 'audit_dir is outside repository_path; exact base-origin check unavailable'
            return result
        result['checked'] = True
        result['comparison_mode'] = 'git-exact-base-sha'
        for name in present:
            current_path = audit_dir / name
            repo_relative = (relative_audit_dir / name).as_posix()
            base_bytes = _git_blob(repository_path, base_sha, repo_relative)
            if base_bytes is not None and current_path.read_bytes() == base_bytes:
                inherited.append(name)
    else:
        return result

    result['inherited_paths'] = inherited
    result['all_present_identity_artifacts_inherited'] = len(inherited) == len(present)
    return result


def classify_delivery_target(
    *,
    audit_dir: Path,
    repository: str,
    issue_number: int | None = None,
    work_item_kind: str,
    work_item_number: int,
    pull_request: int | None = None,
    base_ref: str | None = None,
    head_ref: str | None = None,
    repository_path: Path | None = None,
    base_sha: str | None = None,
    base_audit_dir: Path | None = None,
) -> dict[str, Any]:
    audit_dir = audit_dir.resolve()
    certificate_path = audit_dir / 'handoff-ready.json'
    snapshot_path = audit_dir / 'specification-snapshot.json'
    checked_paths = [str(certificate_path), str(snapshot_path)]
    base_origin = _base_origin(
        audit_dir=audit_dir,
        repository_path=repository_path,
        base_sha=base_sha,
        base_audit_dir=base_audit_dir,
    )

    canonical_issue_number = issue_number if issue_number is not None else (work_item_number if work_item_kind == 'issue' else None)
    canonical_pull_request = pull_request if pull_request is not None else (work_item_number if work_item_kind == 'pr' else None)
    expected_subject = {
        'repository': repository,
        'issue_number': canonical_issue_number,
        'pull_request_number': canonical_pull_request,
        'work_item_kind': work_item_kind,
        'work_item_number': work_item_number,
        'pull_request': canonical_pull_request,
        'base_ref': base_ref,
        'head_ref': head_ref,
    }

    common = {
        'schema_version': 1,
        'expected_subject': expected_subject,
        'checked_paths': checked_paths,
        'base_origin': base_origin,
    }

    if not certificate_path.is_file() and not snapshot_path.is_file():
        return {
            **common,
            'status': 'fresh',
            'reuse_allowed': False,
            'requires_fresh_handoff': True,
            'foreign_target_detected': False,
            'inherited_from_base': False,
            'observed_subject': None,
            'reasons': ['no existing entregar-issue handoff or specification snapshot'],
        }

    reasons: list[str] = []
    observed_subject: dict[str, Any] | None = None
    certificate: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None

    if certificate_path.is_file():
        try:
            certificate = _load_json(certificate_path)
        except Exception as exc:
            reasons.append(f'invalid existing handoff certificate: {exc}')
        if certificate is not None:
            subject = certificate.get('subject')
            if isinstance(subject, dict):
                observed_subject = dict(subject)
                _compare('subject.repository', subject.get('repository'), repository, reasons)
                _compare('subject.work_item_kind', subject.get('work_item_kind'), work_item_kind, reasons)
                _compare('subject.work_item_number', subject.get('work_item_number'), work_item_number, reasons)
                if 'issue_number' in subject:
                    _compare('subject.issue_number', subject.get('issue_number'), canonical_issue_number, reasons)
                if 'pull_request_number' in subject:
                    _compare('subject.pull_request_number', subject.get('pull_request_number'), canonical_pull_request, reasons)
                _compare('subject.pull_request', subject.get('pull_request'), canonical_pull_request, reasons)
                _compare('subject.base_ref', subject.get('base_ref'), base_ref, reasons)
                _compare('subject.head_ref', subject.get('head_ref'), head_ref, reasons)
            else:
                reasons.append('existing handoff certificate lacks semantic subject binding')

    if snapshot_path.is_file():
        try:
            snapshot = _load_json(snapshot_path)
        except Exception as exc:
            reasons.append(f'invalid existing specification snapshot: {exc}')
        if snapshot is not None:
            _compare('snapshot.repository', snapshot.get('repository'), repository, reasons)
            # The specification snapshot is always issue-scoped, even when the invocation target is a PR.
            if canonical_issue_number is not None:
                _compare('snapshot.issue', snapshot.get('issue'), canonical_issue_number, reasons)

    if reasons:
        foreign = any('differs:' in reason for reason in reasons)
        inherited = bool(
            foreign
            and base_origin.get('checked')
            and base_origin.get('all_present_identity_artifacts_inherited')
        )
        status = 'inherited-base-artifact' if inherited else ('foreign-target' if foreign else 'unbound-or-invalid')
        if inherited:
            reasons.append(
                'foreign identity artifacts are byte-identical to the exact base SHA; '
                'treat them as inherited history, never as output of the current delivery'
            )
        return {
            **common,
            'status': status,
            'reuse_allowed': False,
            'requires_fresh_handoff': True,
            'foreign_target_detected': foreign,
            'inherited_from_base': inherited,
            'observed_subject': observed_subject,
            'reasons': reasons,
        }

    if certificate is None:
        return {
            **common,
            'status': 'partial-current-target',
            'reuse_allowed': False,
            'requires_fresh_handoff': True,
            'foreign_target_detected': False,
            'inherited_from_base': False,
            'observed_subject': observed_subject,
            'reasons': ['current-target snapshot exists without a current-target handoff certificate'],
        }

    if certificate.get('status') != 'ready':
        return {
            **common,
            'status': 'unbound-or-invalid',
            'reuse_allowed': False,
            'requires_fresh_handoff': True,
            'foreign_target_detected': False,
            'inherited_from_base': False,
            'observed_subject': observed_subject,
            'reasons': ['existing current-target handoff certificate is not ready'],
        }

    return {
        **common,
        'status': 'current-target',
        'reuse_allowed': True,
        'requires_fresh_handoff': False,
        'foreign_target_detected': False,
        'inherited_from_base': False,
        'observed_subject': observed_subject,
        'reasons': ['existing handoff and snapshot are semantically bound to the current target'],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-dir', default=str(DEFAULT_AUDIT_DIR))
    parser.add_argument('--repository', required=True)
    parser.add_argument('--issue-number', type=int, help='Canonical issue delivered by the PR; required for PR-scoped delivery binding')
    parser.add_argument('--work-item-kind', choices=('issue', 'pr'), required=True)
    parser.add_argument('--work-item-number', type=int, required=True)
    parser.add_argument('--pull-request', type=int)
    parser.add_argument('--base-ref')
    parser.add_argument('--head-ref')
    parser.add_argument('--repository-path', help='Local git checkout used for exact base-origin comparison')
    parser.add_argument('--base-sha', help='Exact base commit SHA used for byte-identical inherited-artifact detection')
    parser.add_argument('--base-audit-dir', help='Materialized base .audit/entregar-issue directory for connector-only comparison')
    parser.add_argument('--out')
    args = parser.parse_args()

    result = classify_delivery_target(
        audit_dir=Path(args.audit_dir),
        repository=args.repository,
        issue_number=args.issue_number,
        work_item_kind=args.work_item_kind,
        work_item_number=args.work_item_number,
        pull_request=args.pull_request,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        repository_path=Path(args.repository_path) if args.repository_path else None,
        base_sha=args.base_sha,
        base_audit_dir=Path(args.base_audit_dir) if args.base_audit_dir else None,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if result['status'] in {'fresh', 'current-target'} else 3


if __name__ == '__main__':
    raise SystemExit(main())
