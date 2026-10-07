"""Regressões do lockfile de dependência, da política de exceção e da auditoria.

Cada teste corresponde a uma forma de o ambiente divergir sem que o repositório mude, que era
o achado A10 da análise: o CI instalava faixas abertas e a versão efetiva não era registrada
em lugar nenhum.

O conjunto cobre também as três formas de o gate aprovar um lockfile que não representa o
manifest, encontradas em auditoria independente: digest arbitrário com formato válido, versão
fixada fora do especificador declarado e exceção de política sem vínculo com o lockfile ou
com o achado.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from scripts import audit_dependencies
from scripts.validate_dependency_locks import compare, main, parse_lock, satisfies

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
    + "\n# arquivo: cryptography-50.0.2-cp311-abi3-manylinux_2_34_x86_64.whl\n"
    + f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
    + "# via cryptography\n# arquivo: cffi-2.1.1-py3-none-any.whl\n"
    + f"cffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n"
)
POLICY = json.dumps({
    "schema_version": 1,
    "exceptions": [
        {
            "id": "GHSA-0000-0000-0000",
            "package": "cffi",
            "version": "2.1.1",
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


def policy_with(**overrides: str) -> str:
    entry = {
        "id": "GHSA-0000-0000-0000",
        "package": "cffi",
        "version": "2.1.1",
        "justification": "x" * 30,
        "review_by": "2099-01-01",
    }
    entry.update(overrides)
    return json.dumps({"schema_version": 1, "exceptions": [entry]})


# --------------------------------------------------------------- estado do repositório


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


def test_repository_lockfiles_pin_exact_versions_with_artifact_and_hash() -> None:
    for lock in sorted(REPO_ROOT.glob("*/requirements*.lock.txt")):
        entries, errors = parse_lock(lock.read_text(encoding="utf-8"))
        assert entries, f"{lock.name} sem entrada"
        assert errors == [], errors
        for name, entry in entries.items():
            assert entry["hashes"], f"{name} sem hash em {lock.name}"
            assert entry["artifact"], f"{name} sem '# arquivo' em {lock.name}"


def test_synchronized_fixture_is_accepted(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path)) == 0


# --------------------------------------------------------------- sincronização


def test_missing_lockfile_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, lock=None)) == 1


def test_declared_package_absent_from_lock_is_detected(tmp_path: Path) -> None:
    lock = HEADER + "\n# arquivo: cffi-2.1.1-py3-none-any.whl\n" + f"cffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n"
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_package_added_to_the_manifest_without_regenerating_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, manifest="cryptography>=50.0.1\njsonschema>=4.26.0\n")) == 1


def test_open_range_in_the_lock_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, lock=LOCK.replace("cryptography==50.0.2", "cryptography>=50.0.2"))) == 1


def test_wildcard_version_in_the_lock_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, lock=LOCK.replace("cryptography==50.0.2", "cryptography==50.*"))) == 1


def test_version_below_the_declared_floor_is_detected(tmp_path: Path) -> None:
    """Versão exata fora do especificador declarado não representa o manifest."""
    assert run(build_repo(tmp_path, lock=LOCK.replace("cryptography==50.0.2", "cryptography==1.0.0"))) == 1


def test_version_above_the_declared_ceiling_is_detected(tmp_path: Path) -> None:
    manifest = "cryptography<50.0.0\n"
    assert run(build_repo(tmp_path, manifest=manifest)) == 1


def test_version_satisfying_the_declared_specifier_is_accepted(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, manifest="cryptography>=50.0.1,<51\n")) == 0


def test_entry_without_hash_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace(f"cffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n", "cffi==2.1.1\n")
    assert run(build_repo(tmp_path, lock=lock)) == 1


@pytest.mark.parametrize("digest", ["f" * 64, "0" * 64])
def test_fabricated_digest_is_not_claimed_as_verified_offline(tmp_path: Path, digest: str) -> None:
    """O gate offline prova vínculo entre nome, versão, artefato e digest, e não integridade.

    Nenhum digest pode ser conferido sem o artefato, e por isso o teste declara o limite em
    vez de fingir que ele não existe: quem confere integridade é
    `scripts/audit_dependencies.py`, com `pip download --require-hashes`.
    """
    lock = LOCK.replace(f"--hash=sha256:{DIGEST}", f"--hash=sha256:{digest}", 1)
    assert run(build_repo(tmp_path, lock=lock)) == 0


def test_entry_without_artifact_declaration_is_detected(tmp_path: Path) -> None:
    lock = "\n".join(line for line in LOCK.split("\n") if "arquivo: cryptography" not in line)
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_artifact_of_another_package_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace("# arquivo: cryptography-50.0.2", "# arquivo: outracoisa-50.0.2")
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_artifact_with_a_different_version_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace(
        "# arquivo: cryptography-50.0.2-cp311-abi3-manylinux_2_34_x86_64.whl",
        "# arquivo: cryptography-9.9.9-py3-none-any.whl",
    )
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_entry_without_via_annotation_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, lock=LOCK.replace("# via cryptography\n", ""))) == 1


def test_via_annotation_pointing_to_unknown_package_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, lock=LOCK.replace("# via cryptography", "# via pacote-inexistente"))) == 1


def test_via_chain_that_never_reaches_a_declared_package_is_detected(tmp_path: Path) -> None:
    lock = (
        HEADER
        + "\n# arquivo: cryptography-50.0.2-py3-none-any.whl\n"
        + f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
        + "# via orfa\n# arquivo: orfa-1.0.0-py3-none-any.whl\n"
        + f"orfa==1.0.0 \\\n    --hash=sha256:{DIGEST}\n"
        + "# via orfa\n# arquivo: segunda-orfa-1.0.0-py3-none-any.whl\n"
        + f"segunda-orfa==1.0.0 \\\n    --hash=sha256:{DIGEST}\n"
    )
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_duplicated_entry_is_detected(tmp_path: Path) -> None:
    lock = LOCK + "# arquivo: cryptography-50.0.2-py3-none-any.whl\n" + f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_header_without_source_manifest_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, lock=LOCK.replace("# lockfile gerado de skill/requirements.txt\n", ""))) == 1


def test_header_without_regeneration_command_is_detected(tmp_path: Path) -> None:
    lock = LOCK.replace(
        "# regenerar: python scripts/lock_dependencies.py --manifest skill/requirements.txt\n", ""
    )
    assert run(build_repo(tmp_path, lock=lock)) == 1


def test_include_directive_expands_the_declared_set(tmp_path: Path) -> None:
    """`requirements-dev.txt` herda `-r requirements.txt`: o lock precisa cobrir a união."""
    root = build_repo(tmp_path)
    skill = root / "skill"
    (skill / "requirements-dev.txt").write_text("-r requirements.txt\npytest>=9.1.1\n", encoding="utf-8")
    assert run(root) == 1, "lock ausente do manifest de desenvolvimento precisa reprovar"

    dev_header = HEADER.replace("skill/requirements.txt", "skill/requirements-dev.txt")
    (skill / "requirements-dev.lock.txt").write_text(
        dev_header
        + "\n# arquivo: cryptography-50.0.2-py3-none-any.whl\n"
        + f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
        + "# via cryptography\n# arquivo: cffi-2.1.1-py3-none-any.whl\n"
        + f"cffi==2.1.1 \\\n    --hash=sha256:{DIGEST}\n"
        + "# arquivo: pytest-9.1.1-py3-none-any.whl\n"
        + f"pytest==9.1.1 \\\n    --hash=sha256:{DIGEST}\n",
        encoding="utf-8",
    )
    assert run(root) == 0


def test_lockfile_is_not_mistaken_for_a_manifest(tmp_path: Path) -> None:
    root = build_repo(tmp_path)
    assert run(root) == 0
    assert not (root / "skill" / "requirements.lock.lock.txt").exists()


# --------------------------------------------------------------- política


def test_policy_without_justification_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, policy=policy_with(justification="curta"))) == 1


def test_policy_without_review_date_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, policy=policy_with(review_by=""))) == 1


def test_policy_without_version_is_detected(tmp_path: Path) -> None:
    """Tolerar pacote sem dizer a versão permitiria encobrir qualquer versão futura."""
    assert run(build_repo(tmp_path, policy=policy_with(version=""))) == 1


def test_policy_version_not_locked_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, policy=policy_with(version="9.9.9"))) == 1


def test_policy_exception_for_unknown_package_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, policy=policy_with(package="nao-esta-no-lock"))) == 1


def test_policy_with_duplicated_identifier_is_detected(tmp_path: Path) -> None:
    entry = json.loads(policy_with())["exceptions"][0]
    policy = json.dumps({"schema_version": 1, "exceptions": [entry, dict(entry)]})
    assert run(build_repo(tmp_path, policy=policy)) == 1


def test_policy_with_wrong_schema_version_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, policy=json.dumps({"schema_version": 2, "exceptions": []}))) == 1


def test_policy_with_alternative_iso_date_is_detected(tmp_path: Path) -> None:
    """`date.fromisoformat` aceita a forma básica, e a norma exige `YYYY-MM-DD`."""
    assert run(build_repo(tmp_path, policy=policy_with(review_by="20990101"))) == 1


def test_policy_with_invalid_date_is_detected(tmp_path: Path) -> None:
    assert run(build_repo(tmp_path, policy=policy_with(review_by="2099-13-45"))) == 1


def test_expired_review_date_warns_without_failing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Data vencida é decisão de pessoa, não defeito de arquivo: reporta e não reprova."""
    root = build_repo(tmp_path, policy=policy_with(review_by="2000-01-01"))
    assert main(["--root", str(root)]) == 0
    assert "AVISO" in capsys.readouterr().out


# --------------------------------------------------------------- versão e especificador


@pytest.mark.parametrize(
    ("version", "specifier", "expected"),
    [
        ("50.0.2", ">=50.0.1", True),
        ("50.0.1", ">=50.0.1", True),
        ("50.0.0", ">=50.0.1", False),
        ("50.0.2", ">50.0.2", False),
        ("50.0.2", "<=50.0.2", True),
        ("1.0", "==1.0.0", True),
        ("1.0.0", "==1.0", True),
        ("50.0.2", "!=50.0.2", False),
        ("50.0.3", "!=50.0.2", True),
        ("50.0.9", "~=50.0.1", True),
        ("51.0.0", "~=50.0.1", False),
        ("6.0.3", ">=6.0.3", True),
        ("9.1.1", ">=9.1.1", True),
        ("2.0.0rc1", ">=2.0.0a1", True),
        ("2.0.0rc1", ">=2.0.0", False),
    ],
)
def test_specifier_satisfaction(version: str, specifier: str, expected: bool) -> None:
    assert satisfies(version, specifier) is expected


def test_unsupported_specifier_operator_is_rejected() -> None:
    """Especificador que o gate não entende não pode virar aprovação silenciosa."""
    assert satisfies("1.0.0", "===1.0.0") is False
    # `~=1` não tem dois segmentos de release e não é PEP 440 válido: reprova em vez de aproximar.
    assert satisfies("1.0.0", "~=1") is False
    assert satisfies("1.0.0", "~=1.0") is True


def test_version_comparison_pads_the_release() -> None:
    assert compare("1.0", "1.0.0") == 0
    assert compare("1.0.1", "1.0") == 1
    assert compare("1.0", "1.0.1") == -1


# --------------------------------------------------------------- determinismo


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


# --------------------------------------------------------------- auditoria


def prepare_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report: dict,
                  exceptions: list[dict] | None = None, artifact_ok: bool = True,
                  unknown: str = "") -> int:
    skill = tmp_path / "skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "requirements.lock.txt").write_text(LOCK, encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "dependency-policy.json").write_text(
        json.dumps({"schema_version": 1, "exceptions": exceptions or []}), encoding="utf-8"
    )
    monkeypatch.setattr(audit_dependencies, "verify_artifacts", lambda _lock: (artifact_ok, unknown))
    monkeypatch.setattr(audit_dependencies, "audit", lambda _lock: (report, ""))
    return audit_dependencies.main(["--root", str(tmp_path)])


def report_with(identifier: str, package: str, version: str, aliases: list[str] | None = None) -> dict:
    return {"dependencies": [{"name": package, "version": version, "vulns": [
        {"id": identifier, "aliases": aliases or [], "fix_versions": []},
    ]}]}


def test_audit_approves_when_no_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert prepare_audit(tmp_path, monkeypatch, {"dependencies": []}) == 0


def test_audit_rejects_finding_without_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = report_with("GHSA-1", "cryptography", "50.0.2")
    assert prepare_audit(tmp_path, monkeypatch, report) == 1


def test_audit_accepts_a_matching_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = report_with("GHSA-1", "cryptography", "50.0.2")
    exceptions = [{"id": "GHSA-1", "package": "cryptography", "version": "50.0.2"}]
    assert prepare_audit(tmp_path, monkeypatch, report, exceptions) == 0


def test_audit_rejects_exception_for_another_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exceção de um pacote não pode encobrir achado de outro."""
    report = report_with("GHSA-1", "cryptography", "50.0.2")
    exceptions = [{"id": "GHSA-1", "package": "cffi", "version": "50.0.2"}]
    assert prepare_audit(tmp_path, monkeypatch, report, exceptions) == 1


def test_audit_rejects_exception_for_another_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = report_with("GHSA-1", "cryptography", "50.0.3")
    exceptions = [{"id": "GHSA-1", "package": "cryptography", "version": "50.0.2"}]
    assert prepare_audit(tmp_path, monkeypatch, report, exceptions) == 1


def test_audit_rejects_exception_without_a_matching_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exceção que tolera algo que o banco não reporta é erro ou aviso retirado."""
    exceptions = [{"id": "GHSA-NOT-REPORTED", "package": "cryptography", "version": "50.0.2"}]
    assert prepare_audit(tmp_path, monkeypatch, {"dependencies": []}, exceptions) == 1


def test_audit_accepts_exception_matched_by_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = report_with("GHSA-1", "cryptography", "50.0.2", aliases=["CVE-2026-1"])
    exceptions = [{"id": "CVE-2026-1", "package": "cryptography", "version": "50.0.2"}]
    assert prepare_audit(tmp_path, monkeypatch, report, exceptions) == 0


def test_audit_rejects_divergent_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert prepare_audit(tmp_path, monkeypatch, {"dependencies": []}, artifact_ok=False) == 1


def test_audit_reports_unknown_when_digest_cannot_be_checked(tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    code = prepare_audit(tmp_path, monkeypatch, {"dependencies": []}, artifact_ok=False,
                         unknown="rede indisponivel")
    assert code == 2


def test_audit_reports_unknown_when_the_tool_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ausência de verificação precisa ser UNKNOWN e nunca sucesso."""
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "requirements.lock.txt").write_text(LOCK, encoding="utf-8")
    monkeypatch.setattr(audit_dependencies, "verify_artifacts", lambda _lock: (True, ""))
    monkeypatch.setattr(audit_dependencies.shutil, "which", lambda _name: None)
    monkeypatch.setattr(audit_dependencies, "module_available", lambda _name: False)
    assert audit_dependencies.main(["--root", str(tmp_path)]) == 2


def test_audit_reports_unknown_without_lockfiles(tmp_path: Path) -> None:
    assert audit_dependencies.main(["--root", str(tmp_path)]) == 2


# ------------------------------------------- segunda rodada de auditoria independente


MINIMAL_LOCK = (
    HEADER
    + "\n# arquivo: cryptography-50.0.2-py3-none-any.whl\n"
    + f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
)
EMPTY_LOCK = HEADER + "\n"
NO_EXCEPTIONS = json.dumps({"schema_version": 1, "exceptions": []})


def minimal(tmp_path: Path, manifest: str = "cryptography>=50.0.1\n", lock: str = MINIMAL_LOCK) -> Path:
    return build_repo(tmp_path, manifest=manifest, lock=lock, policy=NO_EXCEPTIONS)


def test_missing_include_is_detected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Manifest que não pode ser lido não pode ser considerado coberto."""
    root = minimal(tmp_path, manifest="-r nao-existe.txt\n", lock=EMPTY_LOCK)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "inclusao ausente" in capsys.readouterr().err


def test_cyclic_include_is_detected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = minimal(tmp_path, manifest="-r requirements.txt\n", lock=EMPTY_LOCK)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "inclusao ciclica" in capsys.readouterr().err


@pytest.mark.parametrize("artifact", [
    "cryptography-50.0.2",
    "cryptography-50.0.2.txt",
    "cryptography-50.0.2.exe",
])
def test_artifact_without_a_distribution_suffix_is_detected(tmp_path: Path, artifact: str) -> None:
    """Sem sufixo de distribuição, a anotação não nomeia um artefato verificável."""
    lock = MINIMAL_LOCK.replace("cryptography-50.0.2-py3-none-any.whl", artifact)
    assert run(minimal(tmp_path, lock=lock)) == 1


def test_false_marker_does_not_require_the_package(tmp_path: Path) -> None:
    """Marcador falso no contexto registrado torna a ausência legítima."""
    manifest = 'cryptography>=50.0.1; python_version < "3.0"\n'
    assert run(minimal(tmp_path, manifest=manifest, lock=EMPTY_LOCK)) == 0


def test_true_marker_requires_the_package(tmp_path: Path) -> None:
    manifest = 'cryptography>=50.0.1; python_version >= "3.10"\n'
    assert run(minimal(tmp_path, manifest=manifest, lock=EMPTY_LOCK)) == 1
    assert run(minimal(tmp_path, manifest=manifest, lock=MINIMAL_LOCK)) == 0


def test_header_without_resolution_context_is_detected(tmp_path: Path,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    lock = MINIMAL_LOCK.replace("# contexto: python 3.12.3 em linux x86_64\n", "")
    root = minimal(tmp_path, lock=lock)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "sem o contexto de resolucao" in capsys.readouterr().err


def test_forged_header_context_does_not_disable_a_true_marker(tmp_path: Path) -> None:
    """O cabeçalho é comentário editável e não pode ser a autoridade do marcador.

    Declarar um contexto falso para tornar o marcador falso omitiria uma dependência real, e
    por isso o marcador é avaliado contra o interpretador que executa o gate.
    """
    lock = EMPTY_LOCK.replace("python 3.12.3 em linux x86_64", "python 2.7.0 em win32 x86_64")
    manifest = 'cryptography>=50.0.1; python_version >= "3.10"\n'
    assert run(minimal(tmp_path, manifest=manifest, lock=lock)) == 1


def test_unevaluable_marker_is_detected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Marcador que o gate não avalia reprova em vez de ser ignorado."""
    root = minimal(tmp_path, manifest='cryptography>=50.0.1; coisa == "x"\n', lock=MINIMAL_LOCK)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "marcador nao avaliado" in capsys.readouterr().err


@pytest.mark.parametrize(("version", "specifier", "expected"), [
    ("1.0+abc", "==1.0+def", False),
    ("1.0+abc", "==1.0+abc", True),
    ("1.0+abc", "==1.0", True),
    ("1.0.0", "garbage", False),
    ("1.0.0", ">=1.0.0 garbage", False),
    ("1.0.0", ">=1.0.0,", False),
    ("1.0.0", ">=1.0.0, <2", True),
    ("1!2.0", ">=2.0", True),
    ("2.0.0rc1", "<2.0.0", True),
    ("2.0.0rc1", ">=2.0.0", False),
])
def test_strict_specifier_and_local_version(version: str, specifier: str, expected: bool) -> None:
    assert satisfies(version, specifier) is expected


def test_version_with_unknown_suffix_is_detected(tmp_path: Path) -> None:
    """`1.0.0foo` não é PEP 440 e não pode passar como 1.0.0."""
    lock = MINIMAL_LOCK.replace("cryptography==50.0.2", "cryptography==50.0.2foo")
    assert run(minimal(tmp_path, lock=lock)) == 1


def test_marker_environment_is_the_running_interpreter() -> None:
    import sys

    from scripts.validate_dependency_locks import marker_environment

    environment = marker_environment()
    assert environment["python_version"] == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert environment["python_full_version"].startswith(environment["python_version"])
    assert environment["sys_platform"] == sys.platform
    assert environment["implementation_name"] == sys.implementation.name


def test_marker_operator_precedence_matches_pep508() -> None:
    """`and` liga mais forte que `or`: da esquerda para a direita inverteria o resultado."""
    from scripts.validate_dependency_locks import evaluate_marker, marker_environment

    environment = marker_environment()
    assert evaluate_marker('python_version >= "3.0" or python_version >= "3.0" and sys_platform == "nope"',
                           environment) is True
    assert evaluate_marker('python_version < "3.0" and sys_platform == "linux"', environment) is False
    assert evaluate_marker('python_version < "3.0" or sys_platform == "linux"', environment) is True
    # O gate não aproxima: qualquer átomo que ele não saiba avaliar reprova.
    with pytest.raises(ValueError):
        evaluate_marker('coisa == "x"', environment)


@pytest.mark.parametrize(("artifact", "expected"), [
    ("cryptography-50.0.2-py3-none-any.whl", True),
    ("cryptography-50.0.2.tar.gz", True),
    ("cryptography-50.0.20-py3-none-any.whl", False),
    ("cryptography-50.0.2-py3-none-any.whl.whl", False),
    ("cffi-50.0.2-py3-none-any.whl", False),
])
def test_artifact_binding_is_exact(artifact: str, expected: bool) -> None:
    """Versão por substring aceitaria 50.0.20 para 50.0.2."""
    from scripts.validate_dependency_locks import artifact_matches

    assert artifact_matches("cryptography", "50.0.2", artifact) is expected


def test_include_of_an_existing_non_manifest_is_detected(tmp_path: Path,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    root = minimal(tmp_path, manifest="-r not-manifest.json\n", lock=EMPTY_LOCK)
    (root / "skill" / "not-manifest.json").write_text('{"not": "requirements"}', encoding="utf-8")
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "nao interpretavel" in capsys.readouterr().err


def test_uninterpretable_requirement_line_is_detected(tmp_path: Path,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    """Linha descartada em silêncio poderia esconder dependência ou aceitar manifest inválido."""
    root = minimal(tmp_path, manifest="@not-a-requirement\n", lock=EMPTY_LOCK)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "nao interpretavel" in capsys.readouterr().err


def test_unsupported_short_option_is_detected(tmp_path: Path) -> None:
    root = minimal(tmp_path, manifest="-Z algo\n", lock=EMPTY_LOCK)
    assert run(root) == 1


# ------------------------------------------- quarta rodada de auditoria independente


@pytest.mark.parametrize("marker", [
    'python_version < "3.0" and coisa == "x"',
    'python_version >= "3.0" or coisa == "x"',
    'coisa == "x" and python_version >= "3.0"',
])
def test_marker_grammar_is_validated_before_any_short_circuit(marker: str) -> None:
    """Átomo desconhecido não pode ser escondido atrás do resultado já decidido.

    Sem isso, um marcador que o gate afirma não entender dispensaria a dependência.
    """
    from scripts.validate_dependency_locks import evaluate_marker, marker_environment

    with pytest.raises(ValueError):
        evaluate_marker(marker, marker_environment())


def test_marker_hidden_by_short_circuit_cannot_drop_a_package(tmp_path: Path) -> None:
    manifest = 'cryptography>=50.0.1; python_version < "3.0" and coisa == "x"\n'
    assert run(minimal(tmp_path, manifest=manifest, lock=EMPTY_LOCK)) == 1


@pytest.mark.parametrize("option", [
    "--constraint constraints.txt",
    "--index-url https://exemplo.invalid/simple",
    "--extra-index-url https://exemplo.invalid/simple",
])
def test_unsupported_long_option_is_detected(tmp_path: Path, option: str) -> None:
    """Opção ignorada em silêncio poderia esconder resolução que o manifest não representa."""
    manifest = f"{option}\ncryptography>=50.0.1\n"
    assert run(minimal(tmp_path, manifest=manifest, lock=MINIMAL_LOCK)) == 1


def test_unsupported_long_option_inside_an_include_is_detected(tmp_path: Path) -> None:
    root = minimal(tmp_path, manifest="-r extra.txt\n", lock=EMPTY_LOCK)
    (root / "skill" / "extra.txt").write_text(
        "--index-url https://exemplo.invalid/simple\n", encoding="utf-8"
    )
    assert run(root) == 1


@pytest.mark.parametrize("version", [
    "50.0.2post1a1",
    "1.0dev1post1",
    "1.0a1b1",
])
def test_pep440_invalid_suffix_order_is_detected(tmp_path: Path, version: str) -> None:
    """A PEP 440 admite um sufixo de cada tipo, na ordem pré, pós e dev."""
    lock = MINIMAL_LOCK.replace("cryptography==50.0.2", f"cryptography=={version}")
    assert run(minimal(tmp_path, lock=lock)) == 1


@pytest.mark.parametrize(("version", "specifier", "expected"), [
    ("50.0.2", ">=50.0.1+abc", False),
    ("50.0.2", "==50.0+abc", False),
    ("50.0+abc", "==50.0+abc", True),
    ("50.0+abc", "==50.0", True),
    ("50.0.2", "==50.0.2+abc.*", False),
])
def test_local_version_is_not_allowed_in_ordered_specifier(version: str, specifier: str,
                                                            expected: bool) -> None:
    assert satisfies(version, specifier) is expected


# ------------------------------------------- quinta rodada de auditoria independente


@pytest.mark.parametrize(("version", "specifier", "expected"), [
    ("50.0.2", "==50.0.2+abc", False),
    ("50.0.2+abc", "==50.0.2+abc", True),
    ("50.0.2+abc", "==50.0.2", True),
    ("50.0.2", "!=50.0.2+abc", True),
    ("50.0.2+abc", "!=50.0.2+abc", False),
    ("50.0.2+abc", "==50.0.*", True),
])
def test_local_target_in_equality(version: str, specifier: str, expected: bool) -> None:
    """Com alvo local, a igualdade exige o mesmo local; sem alvo local, ele é ignorado."""
    assert satisfies(version, specifier) is expected


def test_manifest_requiring_local_version_rejects_a_lock_without_it(tmp_path: Path) -> None:
    manifest = "cryptography==50.0.2+abc\n"
    assert run(minimal(tmp_path, manifest=manifest, lock=MINIMAL_LOCK)) == 1


def test_absolute_include_outside_the_root_is_detected(tmp_path: Path,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    """Inclusão fora da raiz permitiria controlar o conjunto coberto por arquivo não versionado."""
    outside = tmp_path / "externo.txt"
    outside.write_text("", encoding="utf-8")
    root = minimal(tmp_path / "repo", manifest=f"--requirement {outside}\n", lock=EMPTY_LOCK)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "inclusao absoluta" in capsys.readouterr().err


def test_relative_include_leaving_the_root_is_detected(tmp_path: Path,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "externo.txt").write_text("", encoding="utf-8")
    # `repo/skill/../../externo.txt` resolve para fora de `repo`.
    root = minimal(tmp_path / "repo", manifest="-r ../../externo.txt\n", lock=EMPTY_LOCK)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "fora da raiz" in capsys.readouterr().err


@pytest.mark.parametrize("option", ["    --trusted-host exemplo.invalid", "    --index-url https://exemplo.invalid"])
def test_unsupported_option_in_lockfile_is_detected(tmp_path: Path, option: str) -> None:
    """O lockfile só declara `--hash`: outra opção seria ignorada em silêncio."""
    lock = MINIMAL_LOCK + option + "\n"
    assert run(minimal(tmp_path, lock=lock)) == 1


def test_repeated_artifact_annotation_is_detected(tmp_path: Path) -> None:
    lock = EMPTY_LOCK + (
        "# arquivo: errado-1.0.0.whl\n"
        "# arquivo: cryptography-50.0.2-py3-none-any.whl\n"
        f"cryptography==50.0.2 \\\n    --hash=sha256:{DIGEST}\n"
    )
    assert run(minimal(tmp_path, lock=lock)) == 1


# ------------------------------------------- sexta rodada de auditoria independente


def build_outside_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Par manifest/lock regular dentro da raiz e cópia fora dela."""
    root = tmp_path / "repo"
    (root / "skill").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "dependency-policy.json").write_text(
        json.dumps({"schema_version": 1, "exceptions": []}), encoding="utf-8"
    )
    outside = tmp_path / "externo"
    outside.mkdir()
    (outside / "requirements.txt").write_text("cryptography>=50.0.1\n", encoding="utf-8")
    (outside / "requirements.lock.txt").write_text(MINIMAL_LOCK, encoding="utf-8")
    return root, outside, root / "skill"


def test_symlinked_manifest_outside_the_root_is_detected(tmp_path: Path,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    """Manifest fora da raiz traria para a verificação arquivo que o repositório não versiona."""
    root, outside, skill = build_outside_pair(tmp_path)
    (skill / "requirements.txt").symlink_to(outside / "requirements.txt")
    (skill / "requirements.lock.txt").write_text(MINIMAL_LOCK, encoding="utf-8")
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "manifest resolve para fora" in capsys.readouterr().err


def test_symlinked_lockfile_outside_the_root_is_detected(tmp_path: Path,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    root, outside, skill = build_outside_pair(tmp_path)
    (skill / "requirements.txt").write_text("cryptography>=50.0.1\n", encoding="utf-8")
    (skill / "requirements.lock.txt").symlink_to(outside / "requirements.lock.txt")
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "lockfile resolve para fora" in capsys.readouterr().err


def test_regular_manifest_and_lockfile_still_pass(tmp_path: Path) -> None:
    root, _, skill = build_outside_pair(tmp_path)
    (skill / "requirements.txt").write_text("cryptography>=50.0.1\n", encoding="utf-8")
    (skill / "requirements.lock.txt").write_text(MINIMAL_LOCK, encoding="utf-8")
    assert main(["--root", str(root), "--quiet"]) == 0


def test_confined_helper_rejects_escaping_paths(tmp_path: Path) -> None:
    from scripts.validate_dependency_locks import confined

    root = tmp_path / "repo"
    root.mkdir()
    inside = root / "skill" / "requirements.txt"
    inside.parent.mkdir()
    inside.write_text("cryptography>=50.0.1\n", encoding="utf-8")
    outside = tmp_path / "externo.txt"
    outside.write_text("", encoding="utf-8")
    link = root / "skill" / "link.txt"
    link.symlink_to(outside)
    assert confined(inside, root) is True
    assert confined(outside, root) is False
    assert confined(link, root) is False


# ------------------------------------------- sétima rodada de auditoria independente


@pytest.mark.parametrize(("left", "right", "expected"), [
    ("50.0.2post1.dev1", "50.0.2post1", -1),
    ("50.0.2post1", "50.0.2post1.dev1", 1),
    ("1.0.dev1", "1.0a1", -1),
    ("1.0a1.dev1", "1.0a1", -1),
    ("1.0a1", "1.0b1", -1),
    ("1.0", "1.0.post1", -1),
    ("1.0", "1.0.0", 0),
    ("2.0.0rc1", "2.0.0", -1),
])
def test_pep440_ordering_of_phase_axes(left: str, right: str, expected: int) -> None:
    """Pré, pós e dev são eixos independentes: colapsá-los tornaria `post1.dev1` igual a `post1`."""
    assert compare(left, right) == expected


def test_dev_suffix_after_post_is_not_equal(tmp_path: Path) -> None:
    manifest = "cryptography==50.0.2post1\n"
    lock = MINIMAL_LOCK.replace("cryptography==50.0.2", "cryptography==50.0.2post1.dev1")
    lock = lock.replace("cryptography-50.0.2-py3-none-any.whl", "cryptography-50.0.2post1.dev1-py3-none-any.whl")
    assert run(minimal(tmp_path, manifest=manifest, lock=lock)) == 1


@pytest.mark.parametrize(("artifact", "expected"), [
    ("cryptography-50.0.2-py3-none-any.whl", True),
    ("cryptography-50.0.2-fake.whl", False),
    ("cryptography-50.0.2.tar.gz", True),
    ("cryptography-50.0.2-extra.tar.gz", False),
])
def test_distribution_grammar(artifact: str, expected: bool) -> None:
    """A wheel nomeia Python, ABI e plataforma; o sdist tem exatamente dois campos."""
    from scripts.validate_dependency_locks import artifact_matches

    assert artifact_matches("cryptography", "50.0.2", artifact) is expected


@pytest.mark.parametrize("mode", ["dangling", "directory"])
def test_non_regular_manifest_is_not_silently_skipped(tmp_path: Path, mode: str,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    """Omitir o manifest faria uma mudança deixar de ser verificada sem erro."""
    root = tmp_path / "repo"
    (root / "skill").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "dependency-policy.json").write_text(
        json.dumps({"schema_version": 1, "exceptions": []}), encoding="utf-8"
    )
    (root / "skill" / "requirements.lock.txt").write_text(MINIMAL_LOCK, encoding="utf-8")
    # O alvo fica dentro da raiz para exercitar a regra de arquivo não regular, e não a de
    # confinamento.
    target = root / "skill" / ("sumiu.txt" if mode == "dangling" else "dir")
    if mode == "directory":
        target.mkdir()
    (root / "skill" / "requirements.txt").symlink_to(target)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "nao regular" in capsys.readouterr().err


def test_discovery_includes_symlinked_manifest(tmp_path: Path) -> None:
    from scripts.validate_dependency_locks import discover_manifests

    root = tmp_path / "repo"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "requirements.txt").symlink_to(tmp_path / "sumiu.txt")
    assert [path.name for path in discover_manifests(root)] == ["requirements.txt"]


# ------------------------------------------- oitava rodada de auditoria independente


@pytest.mark.parametrize(("version", "specifier", "expected"), [
    ("50.0.2a1", "!=50.0.2.*", False),
    ("50.0.2a1", "==50.0.2.*", True),
    ("50.0.2", "==50.0.2.*", True),
    ("50.0.2.1", "==50.0.2.*", True),
    ("50.0.2.post1", "==50.0.2.*", True),
    ("50.0.3", "==50.0.2.*", False),
    ("50.0.3", "!=50.0.2.*", True),
])
def test_wildcard_matches_the_release_prefix(version: str, specifier: str, expected: bool) -> None:
    """Casar por texto perderia `50.0.2a1` em `!=50.0.2.*`, que a PEP 440 exclui."""
    assert satisfies(version, specifier) is expected


@pytest.mark.parametrize(("artifact", "expected"), [
    ("cryptography-50.0.2-py3-none-any.whl", True),
    ("cryptography-50.0.2-1abc-py3-none-any.whl", True),
    ("cryptography-50.0.2-extra-py3-none-any.whl", False),
    ("cryptography-50.0.2-fake.whl", False),
    ("cryptography-50.0.2.tar.gz", True),
])
def test_wheel_grammar_fields(artifact: str, expected: bool) -> None:
    """Campo intermediário livre não é distribuição publicável; etiqueta de build começa com dígito."""
    from scripts.validate_dependency_locks import artifact_matches

    assert artifact_matches("cryptography", "50.0.2", artifact) is expected


def build_lock_only(tmp_path: Path, symlink_outside: bool) -> Path:
    root = tmp_path / "repo"
    (root / "skill").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "dependency-policy.json").write_text(
        json.dumps({"schema_version": 1, "exceptions": []}), encoding="utf-8"
    )
    lock = root / "skill" / "requirements.lock.txt"
    if symlink_outside:
        outside = tmp_path / "externo.lock.txt"
        outside.write_text(MINIMAL_LOCK, encoding="utf-8")
        lock.symlink_to(outside)
    else:
        lock.write_text(MINIMAL_LOCK, encoding="utf-8")
    return root


def test_orphan_external_lockfile_is_detected(tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    """Lockfile externo não pode alimentar o índice da política nem passar despercebido."""
    root = build_lock_only(tmp_path, symlink_outside=True)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "resolve para fora" in capsys.readouterr().err


def test_orphan_internal_lockfile_is_detected(tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    root = build_lock_only(tmp_path, symlink_outside=False)
    assert main(["--root", str(root), "--quiet"]) == 1
    assert "sem manifest correspondente" in capsys.readouterr().err


def test_locked_index_ignores_lockfiles_outside_the_root(tmp_path: Path) -> None:
    from scripts.validate_dependency_locks import locked_index

    root = build_lock_only(tmp_path, symlink_outside=True)
    assert locked_index(root) == {}


@pytest.mark.parametrize("name", ["evil!", "evil+"])
def test_invalid_package_name_in_lockfile_is_detected(tmp_path: Path, name: str) -> None:
    """`!` e `+` não fazem parte da gramática de nome de distribuição."""
    lock = MINIMAL_LOCK.replace("cryptography==", f"{name}==", 1)
    assert run(minimal(tmp_path, lock=lock)) == 1
