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
        "README.md",
        "CHANGELOG.md",
        "docs/ROADMAP.md",
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
    assert "nenhuma tag de release vMAJOR.MINOR.PATCH alcancavel" in erros[0]


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
    """Tag anotada de um ramo divergente nao identifica a linha de release.

    A tag e informada pela costura publica porque `git describe` so devolve tag alcancavel,
    tornando o caminho de defesa inalcancavel apenas com repositorios reais.
    """
    repositorio = _repositorio_com_tag(tmp_path)
    _git(repositorio, "checkout", "-q", "-b", "divergente")
    _promove_conteudo(repositorio, "ramo divergente")
    _git(repositorio, "tag", "-a", "v0.9.9", "-m", "release v0.9.9")
    _git(repositorio, "checkout", "-q", "main")
    _promove_conteudo(repositorio)
    erros = release_alignment_errors(repositorio, ref="main", tag="v0.9.9")
    assert len(erros) == 1
    assert "nao e ancestral" in erros[0]


def test_release_alignment_ignores_branches_whose_last_component_is_main(tmp_path: Path) -> None:
    """`feature/main` e `release/main` nao sao a linha de release e nao podem ser reprovadas."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    for ramo in ("feature/main", "release/main", "main-2"):
        _git(repositorio, "branch", ramo)
        assert release_alignment_errors(repositorio, ref=ramo) == [], ramo
        assert release_alignment_errors(repositorio, ref=f"refs/heads/{ramo}") == [], ramo


def test_release_alignment_requires_annotated_tag(tmp_path: Path) -> None:
    """Tag leve nao registra a versao publicada e precisa reprovar."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    _git(repositorio, "tag", "-d", "v0.3.1")
    _git(repositorio, "tag", "v0.3.1")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "precisa ser anotada" in erros[0]


def test_release_alignment_requires_the_documented_tag_format(tmp_path: Path) -> None:
    """A tag publicada precisa seguir vMAJOR.MINOR.PATCH, como a documentacao de release exige."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    _git(repositorio, "tag", "-d", "v0.3.1")
    _git(repositorio, "tag", "-a", "0.3.1", "-m", "release sem prefixo")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "vMAJOR.MINOR.PATCH" in erros[0]


def test_release_alignment_rejects_tag_ahead_of_the_published_version(tmp_path: Path) -> None:
    """Sem commits novos, uma tag a frente do VERSION tambem e divergencia."""
    repositorio = _repositorio_com_tag(tmp_path)
    _git(repositorio, "tag", "-d", "v0.3.1")
    _git(repositorio, "tag", "-a", "v0.3.3", "-m", "release v0.3.3")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "diverge da tag" in erros[0]


def test_release_alignment_rejects_unknown_informed_tag(tmp_path: Path) -> None:
    """A costura publica nao pode servir de atalho para uma tag que nao existe."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    for valor in ("HEAD", "main", "refs/heads/main"):
        erros = release_alignment_errors(repositorio, ref="main", tag=valor)
        assert len(erros) == 1, valor
        assert "vMAJOR.MINOR.PATCH" in erros[0], valor
    erros = release_alignment_errors(repositorio, ref="main", tag="v9.9.9")
    assert len(erros) == 1
    assert "nao existe em refs/tags" in erros[0]
    erros = release_alignment_errors(repositorio, ref="main", tag="v0.3.1:VERSION")
    assert len(erros) == 1
    assert "nome lexical valido" in erros[0]


def test_release_alignment_rejects_uppercase_tag_prefix(tmp_path: Path) -> None:
    """O contrato exige `v` minusculo; `V0.3.1` nao e tag de release reconhecida."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    _git(repositorio, "tag", "-d", "v0.3.1")
    _git(repositorio, "tag", "-a", "V0.3.1", "-m", "release com prefixo maiusculo")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "nenhuma tag de release" in erros[0]


def test_release_alignment_picks_the_highest_release_tag(tmp_path: Path) -> None:
    """Duas tags de release no mesmo commit nao podem fazer o resultado depender do git describe."""
    repositorio = _repositorio_com_tag(tmp_path)
    (repositorio / "VERSION").write_text("0.3.2\n", encoding="utf-8")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", "publica 0.3.2")
    _git(repositorio, "tag", "-a", "v0.3.2", "-m", "release v0.3.2")
    _git(repositorio, "tag", "-a", "v0.3.1", "-m", "release v0.3.1 concorrente", "--force")
    assert release_alignment_errors(repositorio, ref="main") == []
    (repositorio / "VERSION").write_text("0.3.1\n", encoding="utf-8")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", "volta para 0.3.1")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "sem incremento da versao publicada" in erros[0]
    assert "v0.3.2" in erros[0]


def test_release_alignment_rejects_crlf_in_version(tmp_path: Path) -> None:
    """CRLF nao e a forma canonica declarada para VERSION."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    (repositorio / "VERSION").write_bytes(b"0.3.2\r\n")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", "publica com crlf")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "quebra de linha final" in erros[0]


def test_release_alignment_rejects_unreadable_version_bytes(tmp_path: Path) -> None:
    """VERSION com bytes invalidos precisa de recusa controlada, sem excecao."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    (repositorio / "VERSION").write_bytes(b"0.3.2\xff\n")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", "publica com bytes invalidos")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "nao e UTF-8 valido" in erros[0]


def test_release_alignment_rejects_tree_diverging_from_the_target_revision(tmp_path: Path) -> None:
    """Arvore e revisao alvo precisam declarar a mesma versao quando sao o mesmo commit."""
    repositorio = _repositorio_com_tag(tmp_path)
    (repositorio / "VERSION").write_text("0.3.2\n", encoding="utf-8")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "declaram VERSION diferentes" in erros[0]


def test_versioning_rejects_extra_line_in_version(tmp_path: Path) -> None:
    """Linha extra no VERSION precisa reprovar de forma controlada, sem traceback."""
    root = _versioning_fixture(tmp_path)
    (root / "VERSION").write_text("0.3.2\nignorado\n", encoding="utf-8")
    erros = validate_versioning(root)
    assert any("single trailing newline" in erro for erro in erros)
    assert not any("TypeError" in erro for erro in erros)


def test_versioning_requires_dated_release_heading(tmp_path: Path) -> None:
    """O changelog precisa do titulo de release com data, nao de mencao textual."""
    root = _versioning_fixture(tmp_path)
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace("## [0.3.2] - 2026-10-09", "## [0.3.2]"),
        encoding="utf-8",
    )
    erros = validate_versioning(root)
    assert any("lacks release heading" in erro for erro in erros)


def test_release_alignment_reads_the_version_of_the_target_revision(tmp_path: Path) -> None:
    """A versao conferida e a da revisao alvo, nao a da arvore de trabalho."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    (repositorio / "VERSION").write_text("0.3.2\n", encoding="utf-8")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", "publica 0.3.2")
    _git(repositorio, "update-ref", "refs/remotes/origin/main", "main")
    _git(repositorio, "checkout", "-q", "--detach", "v0.3.1")
    assert (repositorio / "VERSION").read_text(encoding="utf-8") == "0.3.1\n"
    assert release_alignment_errors(repositorio, ref="origin/main") == []


def test_release_alignment_is_inert_without_a_determinable_ref(tmp_path: Path) -> None:
    """Sem referencia determinavel a verificacao nao se aplica, em vez de reprovar um alvo desconhecido."""
    assert release_alignment_errors(tmp_path) == []


def test_versioning_reports_invalid_utf8_without_traceback(tmp_path: Path) -> None:
    """O entrypoint agregado precisa recusar VERSION com bytes invalidos sem excecao."""
    root = _versioning_fixture(tmp_path)
    (root / "VERSION").write_bytes(b"0.3.2\xff\n")
    erros = validate_versioning(root)
    assert erros == ["VERSION must be valid UTF-8"]


def test_versioning_rejects_bom_and_missing_newline(tmp_path: Path) -> None:
    """BOM e ausencia de quebra de linha final nao sao a forma canonica de VERSION."""
    for conteudo in (b"\xef\xbb\xbf0.3.2\n", b"0.3.2", b""):
        root = _versioning_fixture(tmp_path / conteudo.hex())
        (root / "VERSION").write_bytes(conteudo)
        erros = validate_versioning(root)
        assert any("single trailing newline" in erro for erro in erros), conteudo


def test_versioning_rejects_impossible_release_date(tmp_path: Path) -> None:
    """Data impossivel no titulo do changelog precisa reprovar."""
    root = _versioning_fixture(tmp_path)
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace("## [0.3.2] - 2026-10-09", "## [0.3.2] - 2026-13-99"),
        encoding="utf-8",
    )
    erros = validate_versioning(root)
    assert any("invalid date" in erro for erro in erros)


def test_versioning_requires_the_changelog(tmp_path: Path) -> None:
    """Sem changelog o contrato de release nao pode ser satisfeito."""
    root = _versioning_fixture(tmp_path)
    (root / "CHANGELOG.md").unlink()
    assert "CHANGELOG.md is missing" in validate_versioning(root)


def test_versioning_rejects_stale_public_surfaces(tmp_path: Path) -> None:
    """README e roadmap declaram a release corrente e nao podem divergir de VERSION."""
    root = _versioning_fixture(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace("`0.3.2`](./VERSION)", "`0.3.1`](./VERSION)"),
        encoding="utf-8",
    )
    roadmap = root / "docs/ROADMAP.md"
    roadmap.write_text(
        roadmap.read_text(encoding="utf-8").replace("> **Release atual:** `v0.3.2`", "> **Release atual:** `v0.3.1`"),
        encoding="utf-8",
    )
    erros = validate_versioning(root)
    assert any("README.md is stale" in erro for erro in erros)
    assert any("docs/ROADMAP.md is stale" in erro for erro in erros)


def test_release_alignment_rejects_explicit_uppercase_tag(tmp_path: Path) -> None:
    """Mesmo informada explicitamente, a tag com prefixo maiusculo precisa reprovar."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    _git(repositorio, "tag", "-a", "V0.3.1", "-m", "release com prefixo maiusculo")
    erros = release_alignment_errors(repositorio, ref="main", tag="V0.3.1")
    assert len(erros) == 1
    assert "vMAJOR.MINOR.PATCH" in erros[0]


def test_release_alignment_rejects_tag_with_surrounding_space(tmp_path: Path) -> None:
    """Espaco no nome informado nao pode ser tratado como tag valida."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    erros = release_alignment_errors(repositorio, ref="main", tag=" v0.3.1 ")
    assert len(erros) == 1
    assert "nome lexical valido" in erros[0]


def test_versioning_rejects_release_date_diverging_from_the_heading(tmp_path: Path) -> None:
    """O titulo do changelog e release_date sao a mesma data canonica."""
    root = _versioning_fixture(tmp_path)
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace(
            "## [0.3.2] - 2026-10-09", "## [0.3.2] - 2026-10-08"
        ),
        encoding="utf-8",
    )
    assert any("differs from compatibility release_date" in erro for erro in validate_versioning(root))


def test_versioning_rejects_duplicated_release_declarations(tmp_path: Path) -> None:
    """Declaracao contraditoria nao pode passar por existir uma ocorrencia correta."""
    root = _versioning_fixture(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\n**Release do catálogo:** [`0.3.1`](./VERSION)\n",
        encoding="utf-8",
    )
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8") + "\n## [0.3.2] - 2026-10-09\n",
        encoding="utf-8",
    )
    erros = validate_versioning(root)
    assert any("README.md declares the release more than once" in erro for erro in erros)
    assert any("declares the release [0.3.2] more than once" in erro for erro in erros)


def test_versioning_accepts_roadmap_without_backticks(tmp_path: Path) -> None:
    """A declaracao do roadmap e semantica, nao uma forma Markdown exata."""
    root = _versioning_fixture(tmp_path)
    roadmap = root / "docs/ROADMAP.md"
    roadmap.write_text(
        roadmap.read_text(encoding="utf-8").replace(
            "> **Release atual:** `v0.3.2`", "> **Release atual:** v0.3.2"
        ),
        encoding="utf-8",
    )
    assert validate_versioning(root) == []


def test_versioning_requires_public_surfaces(tmp_path: Path) -> None:
    """README e roadmap ausentes nao podem passar silenciosamente."""
    for relativo in ("README.md", "docs/ROADMAP.md"):
        root = _versioning_fixture(tmp_path / relativo.replace("/", "-"))
        (root / relativo).unlink()
        erros = validate_versioning(root)
        assert any("is missing" in erro and relativo in erro for erro in erros), relativo


def test_semver_parser_is_controlled_for_extreme_numbers() -> None:
    """SemVer nao fixa teto, mas a conversao precisa recusar sem excecao."""
    assert parse_semver("999999.0.0") == (999999, 0, 0)
    assert parse_semver("9" * 4301 + ".0.0") is None


def test_release_alignment_fails_closed_in_ci_without_determinable_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detached HEAD no CI nao pode desativar em silencio a barreira de alinhamento."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    _git(repositorio, "checkout", "-q", "--detach")
    erros = release_alignment_errors(repositorio)
    assert len(erros) == 1
    assert "nao pode ser determinada no CI" in erros[0]


def test_release_alignment_rejects_isolated_carriage_return(tmp_path: Path) -> None:
    """Retorno de carro isolado nao e a forma canonica de VERSION."""
    repositorio = _repositorio_com_tag(tmp_path)
    _promove_conteudo(repositorio)
    (repositorio / "VERSION").write_bytes(b"0.3.2\r\n")
    _git(repositorio, "add", "VERSION")
    _git(repositorio, "commit", "-q", "-m", "publica com retorno de carro")
    erros = release_alignment_errors(repositorio, ref="main")
    assert len(erros) == 1
    assert "quebra de linha final" in erros[0]
