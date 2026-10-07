"""Regressões do lockfile de dependência e da política de exceção.

Cada teste abaixo corresponde a uma forma de o ambiente divergir sem que o repositório mude,
que era o achado A10 da análise: o CI instalava faixas abertas e a versão efetiva não era
registrada em lugar nenhum.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from scripts.validate_dependency_locks import main, parse_lock

REPO_ROOT = Path(__file__).resolve().parent.parent
DIGEST = "a" * 64
HEADER = (
    "# lockfile gerado de skill/requirements.txt\n"
    "# contexto: python 3.12.3 em linux x86_64\n"
    "# regenerar: python scripts/lock_dependencies.py --manifest skill/requirements.txt\n"
    "# nao editar a mao: alterar o manifest e regenerar\n"
)
LOCK = (
    HEADER
    + f"\ncryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
    + f"# via cryptography\ncffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n"
)
POLICY = json.dumps({
    "schema_version": 1,
    "exceptions": [
        {
            "id": "GHSA-0000-0000-0000",
            "package": "cffi",
            "justification": "correcao publicada apenas para versao incompativel com o runtime atual",
            "review_by": "2099-01-01",
        }
    ],
})


def build_repo(tmp_path: Path, manifest: str = "cryptography>=50.0.1\n", lock: str | None = LOCK,
               policy: str | None = POLICY) -> Path:
    skill = tmp_path / "skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "requirements.txt").write_text(manifest, encoding="utf-8")
    if lock is not None:
        (skill / "requirements.lock.txt").write_text(lock, encoding="utf-8")
    if policy is not None:
        config = tmp_path / "config"
        config.mkdir(exist_ok=True)
        (config / "dependency-policy.json").write_text(policy, encoding="utf-8")
    return tmp_path


def run(root: Path) -> int:
    return main(["--root", str(root), "--quiet"])


def test_repository_locks_and_policy_are_valid() -> None:
    assert run(REPO_ROOT) == 0


def test_repository_has_a_lockfile_beside_every_manifest() -> None:
    manifests = sorted(
        path for path in REPO_ROOT.glob("*/requirements*.txt") if not path.name.endswith(".lock.txt")
    )
    assert manifests, "o repositorio precisa declarar dependencias por skill"
    for manifest in manifests:
        lock = manifest.with_name(manifest.stem + ".lock.txt")
        assert lock.is_file(), f"sem lockfile para {manifest.relative_to(REPO_ROOT)}"


def test_repository_lockfiles_pin_exact_versions_with_hashes() -> None:
    for lock in sorted(REPO_ROOT.glob("*/requirements*.lock.txt")):
        entries, errors = parse_lock(lock.read_text(encoding="utf-8"))
        assert entries, f"{lock.name} sem entrada"
        assert errors == [], errors
        for name, entry in entries.items():
            assert entry["hashes"], f"{name} sem hash em {lock.name}"


def test_synchronized_fixture_is_accepted(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path)) == 0


def test_missing_lockfile_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, lock=None)) == 1


def test_declared_package_absent_from_lock_is_detected(tmp_path: Path) -> None:
    lock = HEADER + f"\ncffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n"
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_package_added_to_the_manifest_without_regenerating_is_detected(tmp_path: Path) -> None:
    manifest = "cryptography>=50.0.1\njsonschema>=4.26.0\n"
    assert run(build_repo(tmp_path, manifest=manifest)) == 1


def test_open_range_in_the_lock_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace("cryptography==50.0.2", "cryptography>=50.0.2")
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_entry_without_hash_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace(f"cffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n", "cffi==2.1.1\n")
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_entry_without_via_annotation_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace("# via cryptography\n", "")
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_via_annotation_pointing_to_unknown_package_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace("# via cryptography", "# via pacote-inexistente")
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_via_chain_that_never_reaches_a_declared_package_is_detected(tmp_path: Path) -> None:
    lock = (
        HEADER
        + f"\ncryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
        + f"# via orfa\norfa==1.0.0 \\\n    --hash=sha256:{DIGEST}\n"
        + f"# via orfa\nsegunda-orfa==1.0.0 \\\n    --hash=sha256:{DIGEST}\n"
    )
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_duplicated_entry_is_detected(tmp_path: Path) -> None:
    lock = LOCK + f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_header_without_source_manifest_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace("# lockfile gerado de skill/requirements.txt\n", "")
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_header_without_regeneration_command_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace(
        "# regenerar: python scripts/lock_dependencies.py --manifest skill/requirements.txt\n",
        "",
    )
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_include_directive_expands_the_declared_set(tmp_path: Path) -> None:
    """`requirements-dev.txt` herda `-r requirements.txt`: o lock precisa cobrir a uniao."""
    root = build_repo(tmp_path)
    skill = root / "skill"
    dev = skill / "requirements-dev.txt"
    dev.write_text("-r requirements.txt\npytest>=9.1.1\n", encoding="utf-8")
    assert run(root) == 1, "lock ausente do manifest de desenvolvimento precisa reprovar"

    pytest_entry = f"pytest==9.1.1 \\\n    --hash=sha256:{DIGEST}\n"
    (skill / "requirements-dev.lock.txt").write_text(
        HEADER.replace("skill/requirements.txt", "skill/requirements-dev.txt") + "\n"
        + f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
        + f"# via cryptography\ncffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n"
        + pytest_entry,
        encoding="utf-8",
    )
    assert run(root) == 0


def test_lockfile_is_not_mistaken_for_a_manifest(tmp_path: Path) -> None:
    root = build_repo(tmp_path)
    assert run(root) == 0
    assert not (root / "skill" / "requirements.lock.lock.txt").exists()


def test_policy_without_justification_is_detected(tmp_path: Path) -> None:
    policy = json.dumps({"schema_version": 1, "exceptions": [
        {"id": "GHSA-1", "package": "cffi", "justification": "curta", "review_by": "2099-01-01"},
    ]})
    assert run(build_repo(tmp_path, policy=policy)) == 1


def test_policy_without_review_date_is_detected(tmp_path: Path) -> None:
    policy = json.dumps({"schema_version": 1, "exceptions": [
        {"id": "GHSA-1", "package": "cffi", "justification": "x" * 30},
    ]})
    assert run(build_repo(tmp_path, policy=policy)) == 1


def test_policy_exception_for_unknown_package_is_detected(tmp_path: Path) -> None:
    policy = json.dumps({"schema_version": 1, "exceptions": [
        {"id": "GHSA-1", "package": "nao-esta-no-lock", "justification": "x" * 30, "review_by": "2099-01-01"},
    ]})
    assert run(build_repo(tmp_path, policy=policy)) == 1


def test_policy_with_duplicated_identifier_is_detected(tmp_path: Path) -> None:
    policy = json.dumps({"schema_version": 1, "exceptions": [
        {"id": "GHSA-1", "package": "cffi", "justification": "x" * 30, "review_by": "2099-01-01"},
        {"id": "GHSA-1", "package": "cffi", "justification": "y" * 30, "review_by": "2099-01-01"},
    ]})
    assert run(build_repo(tmp_path, policy=policy)) == 1


def test_policy_with_wrong_schema_version_is_detected(tmp_path: Path) -> None:
    policy = json.dumps({"schema_version": 2, "exceptions": []})
    assert run(build_repo(tmp_path, policy=policy)) == 1


def test_expired_review_date_warns_without_failing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Data vencida é decisão de pessoa, não defeito de arquivo: reporta e não reprova."""
    policy = json.dumps({"schema_version": 1, "exceptions": [
        {"id": "GHSA-1", "package": "cffi", "justification": "x" * 30, "review_by": "2000-01-01"},
    ]})
    root = build_repo(tmp_path, policy=policy)
    assert main(["--root", str(root)]) == 0
    assert "AVISO" in capsys.readouterr().out


def test_validator_never_opens_a_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("o validador deterministico nao pode usar rede")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    assert run(build_repo(tmp_path)) == 0
    assert run(REPO_ROOT) == 0


def test_validator_is_idempotent(tmp_path: Path) -> None:
    root = build_repo(tmp_path)
    assert [run(root) for _ in range(3)] == [0, 0, 0]


def test_audit_reports_unknown_when_the_tool_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ausência de verificação precisa ser UNKNOWN e nunca sucesso."""
    from scripts import audit_dependencies

    monkeypatch.setattr(audit_dependencies.shutil, "which", lambda _name: None)
    monkeypatch.setattr(audit_dependencies, "_module_available", lambda _name: False)
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "requirements.lock.txt").write_text(LOCK, encoding="utf-8")
    assert audit_dependencies.main(["--root", str(tmp_path)]) == 2
