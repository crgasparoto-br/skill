"""Testes do contrato executavel de handoff de release."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_handoff import build_report, load_json, markdown_report
from scripts.release_handoff import main as contract_main
from scripts.release_handoff import significant
from scripts.validate_release_handoff import policy_errors, script_errors, validate_release_handoff

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/release-handoff.json").read_text(encoding="utf-8"))
DEVELOP = "c" * 40
MAIN = "d" * 40


def evidence(
    *,
    audit: str = "approved",
    develop: str = DEVELOP,
    main: str = MAIN,
    drop: str = "",
    extra: bool = False,
) -> dict:
    """Evidencia sintetica, com os desvios pedidos pelo teste."""
    items = {
        "issues-delivered": {"value": "45", "source": "github"},
        "develop-sha": {"value": develop, "source": "git"},
        "gates": {"value": "ok", "source": "local"},
        "independent-audit": {"value": audit, "source": "auditar-issue"},
        "divergence": {"value": "sim", "source": "git"},
    }
    if drop:
        items.pop(drop)
    if extra:
        items["surpresa"] = {"value": "x", "source": "manual"}
    return {"schema_version": 1, "main": main, "items": items}


def report_for(document: dict, develop: str = DEVELOP, main: str = MAIN) -> dict:
    """Relatorio para a evidencia informada."""
    return build_report(POLICY, document, {"develop": develop, "main": main})


def test_policy_declares_required_evidence_with_reason() -> None:
    """Cada item obrigatorio precisa de descricao e motivo declarados."""
    required = POLICY["required"]
    assert {item["id"] for item in required} >= {
        "issues-delivered",
        "develop-sha",
        "gates",
        "independent-audit",
        "divergence",
    }
    for item in required:
        assert item["description"].strip()
        assert item["reason"].strip()


def test_contract_does_not_hold_merge_authority() -> None:
    """O contrato nao pode declarar autoridade de merge, tag ou publicacao."""
    authority = POLICY["authority"]
    assert authority["merges"] is False
    assert authority["tags"] is False
    assert authority["publishes"] is False


def test_contract_source_has_no_forbidden_command() -> None:
    """O contrato nao pode invocar merge, tag, publicacao ou escrita em git."""
    text = (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8")
    for command in ("gh pr merge", "gh release", "git push", "git tag", "git merge", "git commit"):
        assert command not in text


def test_complete_evidence_is_approved() -> None:
    """Evidencia completa e valida aprova o handoff."""
    report = report_for(evidence())
    assert report["ready"] is True
    assert report["problems"] == []
    assert [row["id"] for row in report["items"]] == [item["id"] for item in POLICY["required"]]


def test_missing_required_item_is_rejected() -> None:
    """Item obrigatorio sem evidencia reprova o handoff."""
    report = report_for(evidence(drop="gates"))
    assert report["ready"] is False
    assert any("gates" in problem and "sem evidencia" in problem for problem in report["problems"])


def test_unapproved_audit_is_rejected() -> None:
    """Parecer de auditoria fora da lista aprovada reprova o handoff."""
    report = report_for(evidence(audit="rejected"))
    assert report["ready"] is False
    assert any("nao esta aprovado" in problem for problem in report["problems"])


def test_equal_develop_and_main_is_rejected() -> None:
    """`develop` igual a `main` significa que nao ha release a promover."""
    report = report_for(evidence(main=DEVELOP), develop=DEVELOP, main=DEVELOP)
    assert report["ready"] is False
    assert any("mesmo commit" in problem for problem in report["problems"])


def test_invalid_sha_is_rejected() -> None:
    """Commit que nao e hexadecimal de 40 caracteres reprova o handoff."""
    document = evidence(develop="nao-e-sha")
    report = report_for(document, develop="nao-e-sha")
    assert report["ready"] is False
    assert any("hexadecimal" in problem for problem in report["problems"])


def test_unknown_evidence_identifier_is_rejected() -> None:
    """Identificador de evidencia desconhecido reprova o handoff."""
    report = report_for(evidence(extra=True))
    assert report["ready"] is False
    assert any("desconhecido" in problem for problem in report["problems"])


def test_evidence_from_another_commit_is_rejected() -> None:
    """A evidencia precisa apontar o commit de `develop` informado."""
    report = report_for(evidence(), develop="e" * 40)
    assert report["ready"] is False
    assert any("diferente do informado" in problem for problem in report["problems"])


def test_report_is_deterministic_and_marked() -> None:
    """A mesma entrada produz a mesma saida, e o relatorio marca cada item."""
    first = markdown_report(report_for(evidence()))
    second = markdown_report(report_for(evidence()))
    assert first == second
    for item in POLICY["required"]:
        assert f"`{item['id']}`" in first
    assert "nao pronto" not in first


def test_invalid_evidence_file_fails_closed(tmp_path: Path) -> None:
    """Evidencia ausente ou invalida falha fechado, sem aprovar em silencio."""
    broken = tmp_path / "evidence.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_json(broken)


def test_non_integer_version_is_rejected() -> None:
    """Achado bloqueante: `True` e `1.0` nao sao a versao inteira declarada."""
    for version in (True, 1.0, 2, None):
        document = evidence()
        document["schema_version"] = version
        report = report_for(document)
        assert report["ready"] is False, f"versao {version!r} foi aceita"
    document = evidence()
    document.pop("schema_version")
    assert report_for(document)["ready"] is False


def test_missing_evidence_source_is_rejected() -> None:
    """Achado nao bloqueante: a origem da evidencia precisa existir."""
    document = evidence()
    document["items"]["gates"] = {"value": "ok"}
    report = report_for(document)
    assert report["ready"] is False
    assert any("origem" in problem for problem in report["problems"])


def test_policy_version_must_be_exact_integer() -> None:
    """Achado bloqueante: a versao da politica tambem precisa ser o inteiro exato."""
    for version in (True, 1.0, 2, None):
        invalid = dict(POLICY)
        invalid["policy_version"] = version
        assert any("policy_version" in error for error in policy_errors(invalid)), f"versao {version!r}"


def test_duplicate_id_across_sections_is_rejected() -> None:
    """Identificador repetido entre obrigatorios e opcionais e recusado."""
    invalid = dict(POLICY)
    invalid["optional"] = [*POLICY["optional"], dict(POLICY["required"][0])]
    assert any("opcionais" in error for error in policy_errors(invalid))


def test_dynamic_import_in_contract_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante: autoridade adquirida em execucao precisa ser recusada."""
    original = (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8")
    injected = original.replace(
        '    return parser.parse_args(argv)',
        '    import importlib\n    importlib.import_module("subprocess")\n    return parser.parse_args(argv)',
        1,
    )
    assert injected != original
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(injected, encoding="utf-8")
    errors = script_errors(tmp_path)
    assert any("importa" in error for error in errors)


def test_contract_imports_stay_in_the_allowed_list() -> None:
    """O contrato entregue so importa o que a lista permitida declara."""
    assert script_errors(ROOT) == []


@pytest.mark.parametrize("snippet", [
    'acquired = getattr(__builtins__, "__import__")("subprocess")',
    'pathlib.os.system("id")',
    'import importlib',
    'mod = __import__("subprocess")',
    'mod = sys.modules["subprocess"]',
    'name = "subprocess"',
    'eval("1")',
    'handle = open("x")',
])
def test_indirect_authority_is_rejected(tmp_path: Path, snippet: str) -> None:
    """Achado bloqueante B2-R: autoridade indireta tambem precisa ser recusada."""
    original = (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8")
    injected = original.replace("def parse_arguments(", f"{snippet}\n\n\ndef parse_arguments(", 1)
    assert injected != original
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(injected, encoding="utf-8")
    assert script_errors(tmp_path), f"forma indireta aceita: {snippet}"


def test_whitespace_only_evidence_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante B3: espaco em branco nao e evidencia nem origem."""
    document = evidence()
    for key in ("issues-delivered", "gates", "divergence"):
        document["items"][key] = {"value": " ", "source": " "}
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    code = contract_main(["--root", str(ROOT), "--evidence", str(path), "--develop", DEVELOP, "--main", MAIN])
    assert code == 1


def test_contract_and_policy_must_not_be_symlinks(tmp_path: Path) -> None:
    """Achado bloqueante B4: contrato e politica precisam ser arquivos regulares confinados."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside/policy.json").write_text(
        (ROOT / "config/release-handoff.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "outside/contract.py").write_text(
        (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "config/release-handoff.json").symlink_to(tmp_path / "outside/policy.json")
    (tmp_path / "scripts/release_handoff.py").symlink_to(tmp_path / "outside/contract.py")
    errors = validate_release_handoff(tmp_path)
    assert any("link simbolico" in error for error in errors)


def test_contract_rejects_invalid_policy_on_its_own(tmp_path: Path) -> None:
    """Ressalva: rodar o contrato sozinho tambem precisa recusar politica invalida."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    invalid = json.loads(json.dumps(POLICY))
    invalid["policy_version"] = True
    (tmp_path / "config/release-handoff.json").write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "scripts/release_handoff.py").write_text(
        (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    code = contract_main(["--root", str(tmp_path), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", MAIN])
    assert code == 1


@pytest.mark.parametrize("character", ["\u200b", "\u200e", "\ufeff", "\u00a0", "\t", "\n", " "])
def test_invisible_character_is_not_evidence(character: str) -> None:
    """Achado bloqueante B3 residual: caractere de formato ou controle nao e evidencia."""
    assert significant(character) == ""
    document = evidence()
    document["items"]["issues-delivered"] = {"value": character, "source": character}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("snippet", [
    'Path.__init__.__globals__["o"+"s"].__dict__["s"+"ystem"]("id")',
    'value = self.__class__',
    'value = object.__subclasses__()',
    'value = getattr(__builtins__, "__import__")',
])
def test_dunder_introspection_is_rejected(tmp_path: Path, snippet: str) -> None:
    """Achado bloqueante B2-R residual: introspeccao por dunder precisa ser recusada."""
    original = (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8")
    injected = original.replace("def parse_arguments(", f"{snippet}\n\n\ndef parse_arguments(", 1)
    assert injected != original
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(injected, encoding="utf-8")
    assert script_errors(tmp_path), f"introspeccao aceita: {snippet}"


def test_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante B4 residual: componente-pai simbolico tambem precisa ser recusado."""
    (tmp_path / "real/config").mkdir(parents=True)
    (tmp_path / "real/scripts").mkdir(parents=True)
    (tmp_path / "real/config/release-handoff.json").write_text(
        (ROOT / "config/release-handoff.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "real/scripts/release_handoff.py").write_text(
        (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "config").symlink_to(tmp_path / "real/config")
    (tmp_path / "scripts").symlink_to(tmp_path / "real/scripts")
    assert any("link simbolico" in error for error in validate_release_handoff(tmp_path))


def test_empty_policy_is_rejected_by_the_contract_alone(tmp_path: Path) -> None:
    """Achado novo: politica sem a evidencia obrigatoria nao passa no contrato sozinho."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(
        (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "config/release-handoff.json").write_text(
        json.dumps({
            "policy_version": 1,
            "authority": {"merges": False, "tags": False, "publishes": False},
            "required": [],
            "optional": [],
            "verdicts": {"audit_approved": ["approved"]},
        }),
        encoding="utf-8",
    )
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"schema_version": 1, "main": MAIN, "items": {}}), encoding="utf-8")
    assert contract_main(["--root", str(tmp_path), "--evidence", str(path), "--develop", DEVELOP, "--main", MAIN]) == 1
