"""Testes do contrato executavel de handoff de release."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.release_handoff import build_report, load_json, markdown_report, significant
from scripts.release_handoff import main as contract_main
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


@pytest.mark.parametrize("character", ["\u034f", "\u0301", "\u200b", "\u00a0", "\t", " "])
def test_combining_and_invisible_characters_are_not_evidence(character: str) -> None:
    """Achado bloqueante B3 residual: marca combinante tambem e invisivel e nao e evidencia."""
    assert significant(character) == ""
    document = evidence()
    document["items"]["issues-delivered"] = {"value": character, "source": character}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("separator", [" ", "\t", "\n"])
def test_sha_with_internal_separator_is_rejected(separator: str) -> None:
    """Regressao: normalizar o commit apagaria o separador interno e o faria parecer valido."""
    broken = "a" * 20 + separator + "a" * 20
    assert significant(broken) == "a" * 40
    report = report_for(evidence(), develop=broken)
    assert report["ready"] is False
    assert any("develop" in problem for problem in report["problems"])


def test_hard_linked_report_destination_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante B4: destino com mais de um link levaria a escrita para outro arquivo."""
    (tmp_path / "outside").mkdir()
    (tmp_path / "reports").mkdir()
    victim = tmp_path / "outside/victim.md"
    victim.write_text("intacto", encoding="utf-8")
    destination = tmp_path / "reports/handoff.md"
    destination.hardlink_to(victim)
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    with pytest.raises(SystemExit):
        contract_main(
            ["--root", str(ROOT), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", MAIN,
             "--report", str(destination)]
        )
    assert victim.read_text(encoding="utf-8") == "intacto"


def test_non_textual_audit_verdict_is_rejected_by_the_contract_alone(tmp_path: Path) -> None:
    """Gap: parecer nao textual na politica precisa ser recusado pelo contrato sozinho."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(
        (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    policy = json.loads(json.dumps(POLICY))
    policy["verdicts"]["audit_approved"] = ["approved", 1, None, {}]
    (tmp_path / "config/release-handoff.json").write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence()), encoding="utf-8")
    assert contract_main(["--root", str(tmp_path), "--evidence", str(path), "--develop", DEVELOP, "--main", MAIN]) == 1


def test_reserved_attribute_introspection_is_rejected(tmp_path: Path) -> None:
    """Achado adicional: `sys._getframe` tambem entrega as builtins."""
    original = (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8")
    snippet = '_runner = sys._getframe().f_builtins["_" + "_import__"]("sub" + "process")'
    injected = original.replace("def parse_arguments(", f"{snippet}\n\n\ndef parse_arguments(", 1)
    assert injected != original
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(injected, encoding="utf-8")
    assert script_errors(tmp_path)


@pytest.mark.parametrize("filler", ["\u3164", "\u115f", "\u1160", "\uffa0", "\U00013441", "\U00013442", "\u2800", "\u2060"])
def test_visually_empty_filler_is_not_evidence(filler: str) -> None:
    """Achado bloqueante B3-R5: preenchedor invisivel tem categoria de letra e nao e evidencia."""
    assert significant(filler) == ""
    document = evidence()
    document["items"]["issues-delivered"] = {"value": filler, "source": filler}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("separator", [" ", "\t", "\u200b", "\u034f", "-"])
def test_declared_sha_with_internal_separator_is_rejected(separator: str) -> None:
    """Achado bloqueante B3/SHA-R5: o valor declarado do commit precisa chegar intacto a validacao."""
    document = evidence()
    document["items"]["develop-sha"] = {"value": DEVELOP[:20] + separator + DEVELOP[20:], "source": "git"}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_occupied_temporary_path_is_rejected(tmp_path: Path, kind: str) -> None:
    """Achado bloqueante B4-R5: o arquivo temporario tambem precisa ser exclusivo."""
    (tmp_path / "outside").mkdir()
    (tmp_path / "reports").mkdir()
    victim = tmp_path / "outside/victim.md"
    victim.write_text("intacto", encoding="utf-8")
    temporary = tmp_path / "reports/handoff.md.parcial"
    if kind == "symlink":
        temporary.symlink_to(victim)
    else:
        os.mkfifo(temporary)
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    with pytest.raises(SystemExit):
        contract_main(
            ["--root", str(ROOT), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", MAIN,
             "--report", str(tmp_path / "reports/handoff.md")]
        )
    assert victim.read_text(encoding="utf-8") == "intacto"


def test_report_without_destination_directory_fails_closed(tmp_path: Path) -> None:
    """Robustez: destino sem diretorio-pai precisa reprovar de forma limpa."""
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    with pytest.raises(SystemExit):
        contract_main(
            ["--root", str(ROOT), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", MAIN,
             "--report", str(tmp_path / "ausente/handoff.md")]
        )


@pytest.mark.parametrize("filler", ["\u3164", "\u115f", "\uffa0", "\U00013441", "\u2800"])
def test_blank_filler_in_value_is_rejected(filler: str) -> None:
    """Achado bloqueante B1: o valor declarado tambem precisa passar pela regra de visibilidade."""
    document = evidence()
    document["items"]["issues-delivered"] = {"value": filler, "source": "github"}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("value", ["x", "1", "z"])
def test_single_character_value_is_rejected(value: str) -> None:
    """Achado bloqueante B1: valor de um caractere nao e evidencia utilizavel."""
    document = evidence()
    document["items"]["gates"] = {"value": value, "source": "local"}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("source", ["g", "gi\u200bthub", "lo\u034fcal", "\u3164"])
def test_obfuscated_source_is_rejected(source: str) -> None:
    """Achado bloqueante B2: origem nao pode ser reduzida nem ter um caractere."""
    document = evidence()
    document["items"]["gates"] = {"value": "ok", "source": source}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("value", ["4\u200b5", "a\u034fb"])
def test_obfuscated_value_is_rejected(value: str) -> None:
    """Achado bloqueante B1/B2: caractere invisivel embutido nao pode ser apagado e aceito."""
    document = evidence()
    document["items"]["issues-delivered"] = {"value": value, "source": "github"}
    assert report_for(document)["ready"] is False


@pytest.mark.parametrize("destination", ["reports/relativo.md", "../fora.md"])
def test_report_destination_outside_root_is_rejected(tmp_path: Path, destination: str) -> None:
    """Achado bloqueante B4: relatorio precisa ficar dentro da raiz auditada."""
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    with pytest.raises(SystemExit):
        contract_main(
            ["--root", str(ROOT), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", MAIN,
             "--report", destination]
        )


def test_audit_verdict_with_embedded_invisible_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante B3: parecer com caractere invisivel embutido nao pode passar."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(
        (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    policy = json.loads(json.dumps(POLICY))
    policy["verdicts"]["audit_approved"] = ["approved\u200b"]
    (tmp_path / "config/release-handoff.json").write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    document = evidence()
    document["items"]["independent-audit"] = {"value": "approved\u200b", "source": "auditar-issue"}
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert contract_main(["--root", str(tmp_path), "--evidence", str(path), "--develop", DEVELOP, "--main", MAIN]) == 1


@pytest.mark.parametrize("text", ["aa\ue000bb", "ok\U0001f642", "a\u00a0b", "a\u3000b", "aaaa", "1111"])
def test_weak_or_foreign_text_is_rejected(text: str) -> None:
    """Achado bloqueante B1: uso privado, emoji, espaco especial e texto repetido nao sao evidencia."""
    document = evidence()
    document["items"]["issues-delivered"] = {"value": text, "source": text}
    assert report_for(document)["ready"] is False


def test_main_conflicting_with_evidence_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante B3: argumento e evidencia nao podem divergir para `main`."""
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    with pytest.raises(SystemExit):
        contract_main(
            ["--root", str(ROOT), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", "e" * 40]
        )


@pytest.mark.parametrize("flag", ["--develop", "--main"])
def test_blank_sha_argument_is_rejected(tmp_path: Path, flag: str) -> None:
    """Achado não bloqueante: argumento informado vazio nao pode cair no fallback silencioso."""
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    arguments = ["--root", str(ROOT), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", MAIN]
    arguments[arguments.index(flag) + 1] = " "
    with pytest.raises(SystemExit):
        contract_main(arguments)


def test_report_cannot_overwrite_handoff_artifacts(tmp_path: Path) -> None:
    """Achado bloqueante B2: destino nao pode sobrescrever contrato, politica ou evidencia."""
    root = tmp_path
    evidence_path = root / "evidence.json"
    evidence_path.write_text(json.dumps(evidence()), encoding="utf-8")
    # O contrato importado e o do proprio repositorio, portanto os alvos protegidos sao os dele.
    targets = [ROOT / "scripts/release_handoff.py", ROOT / "config/release-handoff.json", evidence_path]
    for target in targets:
        with pytest.raises(SystemExit):
            contract_main(
                ["--root", str(ROOT), "--evidence", str(evidence_path), "--develop", DEVELOP, "--main", MAIN,
                 "--report", str(target)]
            )
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["items"]["issues-delivered"]["value"] == "45"


def test_duplicated_policy_verdict_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante B4: politica que repete parecer e malformada."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "scripts/release_handoff.py").write_text(
        (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    policy = json.loads(json.dumps(POLICY))
    policy["verdicts"]["audit_approved"] = ["approved", "approved"]
    (tmp_path / "config/release-handoff.json").write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    assert contract_main(["--root", str(tmp_path), "--evidence", str(ROOT / "config/release-handoff.json"),
                          "--develop", DEVELOP, "--main", MAIN]) == 1


def test_optional_item_present_with_weak_value_is_reported() -> None:
    """Ressalva: item opcional presente tambem precisa de conteudo utilizavel."""
    document = evidence()
    document["items"]["behavioural-evals"] = {"value": "aaaa", "source": "aaaa"}
    report = report_for(document)
    assert any("behavioural-evals" in problem for problem in report["problems"])


@pytest.mark.parametrize("bad", [7, [], True, None, {}, ""])
def test_invalid_main_in_evidence_is_rejected(bad: object) -> None:
    """Achado bloqueante B1: `main` presente e invalido nao pode ser tratado como ausente."""
    document = evidence()
    document["main"] = bad
    assert report_for(document)["ready"] is False


def test_duplicated_json_key_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante B2: chave repetida e entrada ambigua e precisa reprovar."""
    path = tmp_path / "evidence.json"
    raw = json.dumps(evidence())
    duplicated = raw.replace(f'"main": "{MAIN}"', f'"main": "{"e" * 40}", "main": "{MAIN}"')
    assert duplicated != raw
    path.write_text(duplicated, encoding="utf-8")
    with pytest.raises(SystemExit):
        contract_main(["--root", str(ROOT), "--evidence", str(path), "--develop", DEVELOP, "--main", MAIN])


def test_unknown_evidence_field_is_rejected() -> None:
    """Ressalva: campo desconhecido deixa a evidencia ambigua."""
    document = evidence()
    document["surpresa"] = "x"
    assert report_for(document)["ready"] is False


def test_unknown_item_field_is_rejected() -> None:
    """Ressalva: campo extra dentro do item tambem deixa a evidencia ambigua."""
    document = evidence()
    document["items"]["gates"]["extra"] = "x"
    with pytest.raises(SystemExit):
        report_for(document)


def test_missing_main_in_evidence_is_rejected() -> None:
    """Achado bloqueante B1: argumento nao supre a ausencia do campo obrigatorio."""
    document = evidence()
    del document["main"]
    assert report_for(document)["ready"] is False


def test_duplicated_policy_verdict_fails_in_the_contract(tmp_path: Path) -> None:
    """Achado bloqueante B2: o proprio contrato recusa politica com parecer repetido."""
    root = tmp_path
    (root / "config").mkdir()
    policy = json.loads(json.dumps(POLICY))
    policy["verdicts"]["audit_approved"] = ["approved", "approved"]
    (root / "config/release-handoff.json").write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    path = root / "evidence.json"
    path.write_text(json.dumps(evidence()), encoding="utf-8")
    assert contract_main(["--root", str(root), "--evidence", str(path), "--develop", DEVELOP, "--main", MAIN]) == 1


@pytest.mark.parametrize("bad", [None, [], 7, True, "approved"])
def test_optional_item_with_invalid_shape_is_rejected(bad: object) -> None:
    """Ressalva: item opcional presente com estrutura invalida nao pode ser ignorado."""
    document = evidence()
    document["items"]["behavioural-evals"] = bad
    assert report_for(document)["ready"] is False


def test_invalid_utf8_fails_closed_without_traceback(tmp_path: Path) -> None:
    """Ressalva: UTF-8 invalido precisa falhar de forma controlada."""
    path = tmp_path / "evidence.json"
    path.write_bytes(b'{"schema_version": 1, "main": "\xff\xfe"}')
    with pytest.raises(SystemExit):
        contract_main(["--root", str(ROOT), "--evidence", str(path), "--develop", DEVELOP, "--main", MAIN])


def test_colliding_report_destinations_are_rejected(tmp_path: Path) -> None:
    """Ressalva: os dois relatorios nao podem disputar o mesmo destino."""
    target = tmp_path / "relatorio.md"
    with pytest.raises(SystemExit):
        contract_main(["--root", str(ROOT), "--evidence", str(ROOT / "config/release-handoff.json"),
                       "--develop", DEVELOP, "--main", MAIN, "--report", str(target), "--json-report", str(target)])
