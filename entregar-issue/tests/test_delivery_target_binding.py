from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER = ROOT / 'scripts' / 'delivery_target_binding.py'
CONTROLLER = ROOT / 'scripts' / 'controller_cli.py'


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')


def _foreign_package(repo: Path) -> None:
    audit = repo / '.audit' / 'entregar-issue'
    _write(audit / 'handoff-ready.json', {
        'schema_version': 2,
        'status': 'ready',
        'subject': {
            'repository': 'owner/repo',
            'work_item_kind': 'issue',
            'work_item_number': 359,
            'pull_request': 359,
            'base_ref': 'develop',
            'head_ref': 'fix/admin-adipometry-responsibility',
        },
    })
    _write(audit / 'specification-snapshot.json', {
        'schema_version': 1,
        'repository': 'owner/repo',
        'issue': 359,
        'sources': [],
    })


def test_classifier_rejects_foreign_target_package() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _foreign_package(repo)
        proc = subprocess.run([
            sys.executable, str(CLASSIFIER),
            '--audit-dir', str(repo / '.audit' / 'entregar-issue'),
            '--repository', 'owner/repo',
            '--work-item-kind', 'issue',
            '--work-item-number', '363',
            '--pull-request', '364',
            '--base-ref', 'develop',
            '--head-ref', 'feat/issue-363-professor-manual-ux',
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 3
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'foreign-target'
        assert payload['reuse_allowed'] is False
        assert payload['requires_fresh_handoff'] is True
        assert payload['foreign_target_detected'] is True
        assert any('work_item_number differs' in reason for reason in payload['reasons'])


def test_classifier_accepts_current_target_only_as_reuse_candidate() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        audit = repo / '.audit' / 'entregar-issue'
        _write(audit / 'handoff-ready.json', {
            'schema_version': 2,
            'status': 'ready',
            'subject': {
                'repository': 'owner/repo',
                'work_item_kind': 'issue',
                'work_item_number': 363,
                'pull_request': 364,
                'base_ref': 'develop',
                'head_ref': 'feat/issue-363-professor-manual-ux',
            },
        })
        _write(audit / 'specification-snapshot.json', {
            'schema_version': 1,
            'repository': 'owner/repo',
            'issue': 363,
            'sources': [],
        })
        proc = subprocess.run([
            sys.executable, str(CLASSIFIER),
            '--audit-dir', str(audit),
            '--repository', 'owner/repo',
            '--work-item-kind', 'issue',
            '--work-item-number', '363',
            '--pull-request', '364',
            '--base-ref', 'develop',
            '--head-ref', 'feat/issue-363-professor-manual-ux',
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'current-target'
        assert payload['reuse_allowed'] is True
        assert payload['requires_fresh_handoff'] is False


def test_partial_snapshot_requires_fresh_handoff() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        audit = repo / '.audit' / 'entregar-issue'
        _write(audit / 'specification-snapshot.json', {
            'schema_version': 1,
            'repository': 'owner/repo',
            'issue': 363,
            'sources': [],
        })
        proc = subprocess.run([
            sys.executable, str(CLASSIFIER),
            '--audit-dir', str(audit),
            '--repository', 'owner/repo',
            '--work-item-kind', 'issue',
            '--work-item-number', '363',
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 3
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'partial-current-target'
        assert payload['requires_fresh_handoff'] is True


def test_init_context_records_foreign_target_and_forbids_reuse() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _foreign_package(repo)
        out = repo / '.audit' / 'entregar-issue' / 'controller-context-new.json'
        proc = subprocess.run([
            sys.executable, str(CONTROLLER), 'init-context',
            '--repository', 'owner/repo',
            '--repository-path', str(repo),
            '--issue', '363',
            '--work-item-kind', 'issue',
            '--work-item-number', '363',
            '--base-ref', 'develop',
            '--branch', 'feat/issue-363-professor-manual-ux',
            '--pull-request', '364',
            '--out', str(out),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(out.read_text(encoding='utf-8'))
        assert payload['artifact_reuse']['status'] == 'foreign-target'
        assert payload['artifact_reuse']['reuse_allowed'] is False
        assert payload['artifact_reuse']['requires_fresh_handoff'] is True
        assert 'artifact-reuse=foreign-target' in proc.stdout


def test_refresh_context_reclassifies_binding_when_pull_request_changes() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        audit = repo / '.audit' / 'entregar-issue'
        _write(audit / 'handoff-ready.json', {
            'schema_version': 2,
            'status': 'ready',
            'subject': {
                'repository': 'owner/repo',
                'work_item_kind': 'issue',
                'work_item_number': 363,
                'pull_request': None,
                'base_ref': 'develop',
                'head_ref': 'feature/current-target',
            },
        })
        _write(audit / 'specification-snapshot.json', {
            'schema_version': 1,
            'repository': 'owner/repo',
            'issue': 363,
            'sources': [],
        })
        context = audit / 'controller-context.json'
        init = subprocess.run([
            sys.executable, str(CONTROLLER), 'init-context',
            '--repository', 'owner/repo',
            '--repository-path', str(repo),
            '--issue', '363',
            '--work-item-kind', 'issue',
            '--work-item-number', '363',
            '--base-ref', 'develop',
            '--branch', 'feature/current-target',
            '--out', str(context),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert init.returncode == 0, init.stdout
        assert json.loads(context.read_text(encoding='utf-8'))['artifact_reuse']['status'] == 'current-target'

        refresh = subprocess.run([
            sys.executable, str(CONTROLLER), 'refresh-context',
            '--context', str(context),
            '--pull-request', '364',
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert refresh.returncode == 0, refresh.stdout
        payload = json.loads(context.read_text(encoding='utf-8'))
        assert payload['pull_request'] == 364
        assert payload['artifact_reuse']['status'] == 'foreign-target'
        assert payload['artifact_reuse']['reuse_allowed'] is False
        assert 'artifact-reuse=foreign-target' in refresh.stdout


def test_refresh_context_reclassifies_after_foreign_package_is_rebuilt() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _foreign_package(repo)
        audit = repo / '.audit' / 'entregar-issue'
        context = audit / 'controller-context.json'
        init = subprocess.run([
            sys.executable, str(CONTROLLER), 'init-context',
            '--repository', 'owner/repo',
            '--repository-path', str(repo),
            '--issue', '363',
            '--work-item-kind', 'issue',
            '--work-item-number', '363',
            '--base-ref', 'develop',
            '--branch', 'feat/current-target',
            '--pull-request', '364',
            '--out', str(context),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert init.returncode == 0, init.stdout
        assert json.loads(context.read_text(encoding='utf-8'))['artifact_reuse']['status'] == 'foreign-target'

        _write(audit / 'handoff-ready.json', {
            'schema_version': 2,
            'status': 'ready',
            'subject': {
                'repository': 'owner/repo',
                'work_item_kind': 'issue',
                'work_item_number': 363,
                'pull_request': 364,
                'base_ref': 'develop',
                'head_ref': 'feat/current-target',
            },
        })
        _write(audit / 'specification-snapshot.json', {
            'schema_version': 1,
            'repository': 'owner/repo',
            'issue': 363,
            'sources': [],
        })

        refresh = subprocess.run([
            sys.executable, str(CONTROLLER), 'refresh-context',
            '--context', str(context),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert refresh.returncode == 0, refresh.stdout
        payload = json.loads(context.read_text(encoding='utf-8'))
        assert payload['artifact_reuse']['status'] == 'current-target'
        assert payload['artifact_reuse']['reuse_allowed'] is True
        assert 'artifact-reuse=current-target' in refresh.stdout


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ['git', '-C', str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert proc.returncode == 0, proc.stdout
    return proc.stdout.strip()


def _init_repo_with_foreign_audit_on_base(repo: Path) -> tuple[Path, str]:
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'test@example.invalid')
    _git(repo, 'config', 'user.name', 'Skill Test')
    audit = repo / '.audit' / 'entregar-issue'
    _write(audit / 'handoff-ready.json', {
        'schema_version': 2,
        'status': 'ready',
        'subject': {
            'repository': 'owner/repo',
            'issue_number': 101,
            'pull_request_number': 102,
            'work_item_kind': 'issue',
            'work_item_number': 101,
            'pull_request': 102,
            'base_ref': 'develop',
            'head_ref': 'feature/previous-delivery',
        },
    })
    _write(audit / 'specification-snapshot.json', {
        'schema_version': 1,
        'repository': 'owner/repo',
        'issue': 101,
        'sources': [],
    })
    (repo / 'README.md').write_text('base\n', encoding='utf-8')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'base with historical delivery artifacts')
    base_sha = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'checkout', '-b', 'feature/current-delivery')
    (repo / 'feature.txt').write_text('current delivery material change\n', encoding='utf-8')
    _git(repo, 'add', 'feature.txt')
    _git(repo, 'commit', '-m', 'current delivery material change')
    return audit, base_sha


def test_classifier_marks_byte_identical_foreign_base_artifacts_as_inherited_history() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        audit, base_sha = _init_repo_with_foreign_audit_on_base(repo)
        proc = subprocess.run([
            sys.executable, str(CLASSIFIER),
            '--audit-dir', str(audit),
            '--repository', 'owner/repo',
            '--issue-number', '201',
            '--work-item-kind', 'issue',
            '--work-item-number', '201',
            '--pull-request', '202',
            '--base-ref', 'develop',
            '--head-ref', 'feature/current-delivery',
            '--repository-path', str(repo),
            '--base-sha', base_sha,
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 3, proc.stdout
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'inherited-base-artifact'
        assert payload['reuse_allowed'] is False
        assert payload['requires_fresh_handoff'] is True
        assert payload['foreign_target_detected'] is True
        assert payload['inherited_from_base'] is True
        assert payload['base_origin']['checked'] is True
        assert payload['base_origin']['comparison_mode'] == 'git-exact-base-sha'
        assert sorted(payload['base_origin']['inherited_paths']) == [
            'handoff-ready.json',
            'specification-snapshot.json',
        ]


def test_classifier_does_not_call_head_modified_foreign_certificate_inherited() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        audit, base_sha = _init_repo_with_foreign_audit_on_base(repo)
        certificate = json.loads((audit / 'handoff-ready.json').read_text(encoding='utf-8'))
        certificate['producer_note'] = 'written on current branch'
        _write(audit / 'handoff-ready.json', certificate)
        proc = subprocess.run([
            sys.executable, str(CLASSIFIER),
            '--audit-dir', str(audit),
            '--repository', 'owner/repo',
            '--issue-number', '201',
            '--work-item-kind', 'issue',
            '--work-item-number', '201',
            '--pull-request', '202',
            '--base-ref', 'develop',
            '--head-ref', 'feature/current-delivery',
            '--repository-path', str(repo),
            '--base-sha', base_sha,
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 3, proc.stdout
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'foreign-target'
        assert payload['inherited_from_base'] is False
        assert payload['base_origin']['all_present_identity_artifacts_inherited'] is False


def test_classifier_supports_connector_materialized_base_comparison() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        head_audit = root / 'head' / '.audit' / 'entregar-issue'
        base_audit = root / 'base' / '.audit' / 'entregar-issue'
        for audit in (head_audit, base_audit):
            _write(audit / 'handoff-ready.json', {
                'schema_version': 2,
                'status': 'ready',
                'subject': {
                    'repository': 'owner/repo',
                    'issue_number': 11,
                    'pull_request_number': 12,
                    'work_item_kind': 'issue',
                    'work_item_number': 11,
                    'pull_request': 12,
                    'base_ref': 'develop',
                    'head_ref': 'feature/previous',
                },
            })
            _write(audit / 'specification-snapshot.json', {
                'schema_version': 1,
                'repository': 'owner/repo',
                'issue': 11,
                'sources': [],
            })
        proc = subprocess.run([
            sys.executable, str(CLASSIFIER),
            '--audit-dir', str(head_audit),
            '--base-audit-dir', str(base_audit),
            '--repository', 'owner/repo',
            '--issue-number', '21',
            '--work-item-kind', 'issue',
            '--work-item-number', '21',
            '--pull-request', '22',
            '--base-ref', 'develop',
            '--head-ref', 'feature/current',
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 3, proc.stdout
        payload = json.loads(proc.stdout)
        assert payload['status'] == 'inherited-base-artifact'
        assert payload['base_origin']['comparison_mode'] == 'materialized-base'
        assert payload['inherited_from_base'] is True


def test_controller_init_context_propagates_exact_base_origin_classification() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        audit, base_sha = _init_repo_with_foreign_audit_on_base(repo)
        context = audit / 'controller-context-current.json'
        head_sha = _git(repo, 'rev-parse', 'HEAD')
        proc = subprocess.run([
            sys.executable, str(CONTROLLER), 'init-context',
            '--repository', 'owner/repo',
            '--repository-path', str(repo),
            '--issue', '201',
            '--work-item-kind', 'issue',
            '--work-item-number', '201',
            '--base-ref', 'develop',
            '--branch', 'feature/current-delivery',
            '--pull-request', '202',
            '--head-sha', head_sha,
            '--base-sha', base_sha,
            '--out', str(context),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(context.read_text(encoding='utf-8'))
        assert payload['artifact_reuse']['status'] == 'inherited-base-artifact'
        assert payload['artifact_reuse']['reuse_allowed'] is False
        assert payload['artifact_reuse']['inherited_from_base'] is True
        assert 'artifact-reuse=inherited-base-artifact' in proc.stdout
