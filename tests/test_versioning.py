from __future__ import annotations

import builtins
import json
import shutil
import subprocess
from pathlib import Path

from scripts.catalog import load_catalog
from scripts.validate_versioning import (
    parse_lineage,
    parse_semver,
    release_alignment_errors,
    validate_json_schema,
    validate_versioning,
)

ROOT = Path(__file__).resolve().parents[1]


def _versioning_fixture(tmp_path: Path) -> Path:
    files = [
        "VERSION",
        "CHANGELOG.md",
        "docs/RELEASE.md",
        "config/compatibility.json",
        "config/skills-catalog.json",
        "config/skill-system-requirements.json",
        ".github/skill-system-capabilities.json",
        "schemas/compatibility.schema.json",
        "config/platform-adapters.json",
    ]
    for item in files:
        destination = tmp_path / item
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item, destination)
    for skill in load_catalog(ROOT)["skills"]:
        item = f"{skill['id']}/contracts/version.json"
        destination = tmp_path / item
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item, destination)
    return tmp_path


def _write_compatibility(root: Path, document: dict) -> None:
    (root / "config/compatibility.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_versioning_manifest_is_consistent() -> None:
    assert validate_versioning(ROOT) == []


def test_semver_parser_accepts_public_versions_and_rejects_ambiguous_values() -> None:
    assert parse_semver("0.1.0") == (0, 1, 0)
    assert parse_semver("1.0.0") == (1, 0, 0)
    assert parse_semver("01.2.3") is None
    assert parse_semver("2026-09-29.2") is None


def test_lineage_parser_rejects_impossible_dates_and_zero_snapshots() -> None:
    assert parse_lineage("2026-09-29.2") is not None
    assert parse_lineage("2026-02-30.1") is None
    assert parse_lineage("2026-09-29.0") is None
    assert parse_lineage("2026-09-999.1") is None


def test_compatibility_schema_rejects_missing_required_fields(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    document = json.loads((root / "config/compatibility.json").read_text(encoding="utf-8"))
    del document["contract_policy"]["compatibility_mode"]
    _write_compatibility(root, document)
    errors = validate_versioning(root)
    assert any("compatibility schema" in error and "compatibility_mode" in error for error in errors)


def test_versioning_rejects_system_version_drift(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    document = json.loads((root / "config/compatibility.json").read_text(encoding="utf-8"))
    document["system_version"] = "2026-09-28.1"
    _write_compatibility(root, document)
    errors = validate_versioning(root)
    assert any("differs from requirements manifest" in error for error in errors)
    assert any("differs from capabilities manifest" in error for error in errors)


def test_versioning_rejects_impossible_lineage_date(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    document = json.loads((root / "config/compatibility.json").read_text(encoding="utf-8"))
    document["contract_policy"]["internal_lineage_version"] = "2026-02-30.1"
    _write_compatibility(root, document)
    errors = validate_versioning(root)
    assert any("internal_lineage_version must use a valid" in error for error in errors)


def test_versioning_rejects_adapter_introduction_drift(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    platform_path = root / "config/platform-adapters.json"
    platform = json.loads(platform_path.read_text(encoding="utf-8"))
    platform["adapters"][0]["introduced_in"] = "0.1.0"
    platform_path.write_text(json.dumps(platform, indent=2) + "\n", encoding="utf-8")
    errors = validate_versioning(root)
    assert any("compatibility min_release differs from platform introduced_in" in error for error in errors)


def test_versioning_rejects_missing_adapter_release_row(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    release_doc = root / "docs/RELEASE.md"
    release_doc.write_text(
        release_doc.read_text(encoding="utf-8").replace("| `application` | `0.2.0` | `supported` |\n", ""),
        encoding="utf-8",
    )
    errors = validate_versioning(root)
    assert any("missing adapter row" in error and "application" in error for error in errors)


def test_invalid_schema_returns_controlled_error(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    document = tmp_path / "document.json"
    schema.write_text('{"type": 17}', encoding="utf-8")
    document.write_text("{}", encoding="utf-8")
    errors = validate_json_schema(schema, document, "invalid schema")
    assert any("schema is invalid" in error for error in errors)


def test_schema_dependency_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    document = tmp_path / "document.json"
    schema.write_text("{}", encoding="utf-8")
    document.write_text("{}", encoding="utf-8")
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("simulated missing jsonschema")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    errors = validate_json_schema(schema, document, "test schema")
    assert any("jsonschema dependency unavailable" in error for error in errors)


def _git(path: Path, *argumentos: str) -> None:
    subprocess.run(
        ["git", *argumentos],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _repositorio_com_tag(tmp_path: Path, versao: str = "0.3.1") -> Path:
    """Cria um repositorio minimo com uma release ja publicada e marcada por tag anotada."""
    repositorio = tmp_path / "repositorio"
    repositorio.mkdir()
    _git(repositorio, "init", "-q", "-b", "main")
    _git(repositorio, "config", "user.email", "teste@exemplo.invalid")
    _git(repositorio, "config", "user.name", "Teste")
    (repositorio / "VERSION").write_text(f"{versao}\n", encoding="utf-8")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", f"publica {versao}")
    _git(repositorio, "tag", "-a", f"v{versao}", "-m", f"release v{versao}")
    return repositorio


def _promove_conteudo(repositorio: Path, mensagem: str = "conteudo promovido") -> None:
    (repositorio / "conteudo.txt").write_text("promovido\n", encoding="utf-8")
    _git(repositorio, "add", "conteudo.txt")
    _git(repositorio, "commit", "-q", "-m", mensagem)


def test_release_alignment_rejects_promotion_without_published_version(tmp_path: Path) -> None:
    """Regressao: a main avancou alem da tag sem versao publicada, o estado que originou a issue."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "sem incremento da versao publicada" in erros[0]
    assert "v0.3.1" in erros[0]
    assert "VERSION=0.3.1" in erros[0]


def test_release_alignment_accepts_version_that_identifies_promoted_content(tmp_path: Path) -> None:
    """Cenario conforme: a versao publicada avanca junto com o conteudo promovido."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    (repositorio / "VERSION").write_text("0.3.2\n", encoding="utf-8")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", "publica 0.3.2")
    assert release_alignment_errors(repositorio, ref="main") == []


def test_release_alignment_accepts_release_line_matching_the_tag(tmp_path: Path) -> None:
    """Promocao sem commit novo nao exige versao adicional."""
    repositorio = _repositorio_com_tag(tmp_path)
    assert release_alignment_errors(repositorio, ref="main") == []


def test_release_alignment_ignores_other_lines(tmp_path: Path) -> None:
    """A verificacao vale para a linha de release; develop nao e reprovado por estar a frente."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    assert release_alignment_errors(repositorio, ref="develop") == []
    assert release_alignment_errors(repositorio, ref="refs/heads/develop") == []


def test_release_alignment_normalizes_remote_ref(tmp_path: Path) -> None:
    """origin/main e refs/remotes/origin/main designam a mesma linha de release."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    _git(repositorio, "update-ref", "refs/remotes/origin/main", "main")
    for referencia in ("origin/main", "refs/remotes/origin/main", "refs/heads/main"):
        erros = release_alignment_errors(repositorio, ref=referencia)
        assert len(erros) == 1, referencia
        assert "sem incremento da versao publicada" in erros[0]


def test_release_alignment_is_fail_closed_without_reachable_tag(tmp_path: Path) -> None:
    """Sem tag alcancavel a conformidade nao e presumida."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    _git(repositorio, "tag", "-d", "v0.3.1")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "nenhuma tag alcancavel" in erros[0]


def test_release_alignment_is_fail_closed_on_shallow_clone(tmp_path: Path) -> None:
    """Clone raso nao permite conferir a tag publicada e precisa reprovar, nao passar em silencio."""
    origem = _repositorio_com_tag(tmp_path)
    _promove_conteudo(origem)
    raso = tmp_path / "raso"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-tags", f"file://{origem}", str(raso)],
        check=True,
        capture_output=True,
        text=True,
    )
    erros = release_alignment_errors(raso, ref="main")
    assert len(erros) == 1
    assert "clone raso" in erros[0]


def test_release_alignment_is_fail_closed_outside_a_repository(tmp_path: Path) -> None:
    """Fora de repositorio git a linha de release nao pode ser conferida."""
    erros = release_alignment_errors(tmp_path, ref="main")
    assert len(erros) == 1
    assert "nao esta em repositorio git" in erros[0]


def test_release_alignment_rejects_tag_outside_the_release_line(tmp_path: Path) -> None:
    """Tag que nao e ancestral da linha de release e divergencia, nao conformidade.

    A tag e informada pela costura publica porque `git describe` so devolve tag alcancavel,
    tornando o caminho de defesa inalcancavel apenas com repositorios reais.
    """
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    erros = release_alignment_errors(repositorio, ref="main", tag="v0.9.9")
    assert len(erros) == 1
    assert "nao e ancestral" in erros[0]


def test_release_alignment_is_inert_without_a_determinable_ref(tmp_path: Path) -> None:
    """Sem referencia determinavel a verificacao nao se aplica, em vez de reprovar um alvo desconhecido."""
    assert release_alignment_errors(tmp_path) == []
