#!/usr/bin/env python3
"""Converte o relatório de higiene em work items na forma canônica de issue.

Um work item por classe com achado, e não um por achado: a varredura de um repositório legado pode
encontrar dezenas de ocorrências da mesma dívida, e transformar cada ocorrência em issue afogaria o
rastreador sem melhorar a decisão. A classe é a unidade de decisão — corrigir, aceitar com
justificativa ou rebaixar o limiar — e a lista de achados é a evidência dentro dela.

O gerador produz o artefato e para. Ele não abre, não edita e não fecha issue: abrir issue é ação
externa com efeito para terceiros, e a autoridade para isso é de quem opera o ciclo, não da
varredura. O corpo sai na forma canônica lida pelos extratores de requisito, com uma linha por item
nas seções normativas, para que o work item possa virar issue sem reescrita.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# O gerador não escreve na árvore analisada, e bytecode de módulo importado é escrita: sem isto, a
# própria execução deixaria `__pycache__` dentro da raiz que ele afirma não alterar.
sys.dont_write_bytecode = True

try:
    from .hygiene_scan import HygieneError, build_report, load_policy, write_target
    from .validate_hygiene import coverage_errors, policy_errors, schema_errors
except ImportError:  # pragma: no cover - execucao direta do script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_scan import HygieneError, build_report, load_policy, write_target
    from validate_hygiene import coverage_errors, policy_errors, schema_errors

CLASS_TEXT = {
    "duplication": {
        "title": "Higiene: duplicação de corpo de função na árvore",
        "objective": "Eliminar a duplicação apontada pela varredura, ou registrar a cópia compartilhada no mecanismo declarado do repositório.",
        "context": "Corpos de função normalizados idênticos aparecem em arquivos diferentes. Cópia declarada em config/shared-files.json é exclusão legítima; o resto é dívida, porque duas cópias divergem na primeira alteração.",
        "scope": "Consolidar o corpo em uma única fonte, ou declarar a cópia compartilhada em config/shared-files.json quando o empacotamento independente exigir a réplica.",
        "functional": "Cada corpo listado passa a ter uma única fonte editável, com a outra ponta resolvida por importação ou por cópia declarada e sincronizada.",
        "nonfunctional": "A consolidação não pode introduzir dependência nova nem alterar o comportamento observável dos chamadores.",
        "invariants": "A correção não pode aumentar a contagem de duplicação; a cópia declarada precisa continuar idêntica à fonte canônica.",
        "acceptance": "A varredura não reporta mais o corpo como duplicação aberta, e a contagem de duplicação não cresce em relação à linha medida antes da correção.",
        "edge": "Cópia declarada que diverge da canônica reprova em scripts/sync_contracts.py e precisa ser regenerada, não editada à mão.",
        "tests": "Teste que falha quando o corpo volta a divergir; execução de scripts/validate_contract_sync.py para as cópias declaradas.",
        "docs": "config/shared-files.json quando a decisão for declarar a cópia; config/hygiene-policy.json quando a exceção mudar de estado.",
        "risks": "Consolidar sem declarar o empacotamento pode quebrar a skill que precisa da cópia isolada.",
    },
    "dead-module": {
        "title": "Higiene: módulo sem importador e sem invocação declarada",
        "objective": "Remover o módulo morto ou torná-lo alcançável por importação ou por invocação declarada.",
        "context": "O arquivo não é importado por nenhum módulo da árvore e não é citado por nenhuma invocação declarada. Instrução que não é alcançada nunca é carregada e diverge em silêncio.",
        "scope": "Remover o arquivo, ou declarar a invocação que o alcança na documentação operacional da skill.",
        "functional": "Todo módulo operacional passa a ser importado por outro módulo ou citado por uma invocação declarada.",
        "nonfunctional": "A remoção não pode deixar referência pendente em documentação, schema ou teste.",
        "invariants": "A varredura não pode voltar a reportar o mesmo caminho depois da correção.",
        "acceptance": "A varredura não reporta mais o módulo, e a suíte de testes continua aprovando.",
        "edge": "Módulo carregado por convenção de diretório, e não por import, precisa entrar na lista declarada de pontos de entrada da política.",
        "tests": "Teste de detecção em árvore temporária e conferência de que o módulo removido não é citado em nenhum arquivo.",
        "docs": "Documentação operacional da skill quando a decisão for declarar a invocação.",
        "risks": "Remover módulo alcançado por carga dinâmica fora da árvore quebra o fluxo que o usa.",
    },
    "dead-symbol": {
        "title": "Higiene: símbolo de nível de módulo sem referência",
        "objective": "Remover o símbolo morto ou restabelecer a referência que o justifica.",
        "context": "O nome do símbolo aparece apenas na própria definição em toda a árvore: nenhum chamador, nenhum teste e nenhuma documentação o alcançam.",
        "scope": "Remover o símbolo, ou registrar o uso dinâmico que o mantém, com a justificativa na política.",
        "functional": "Todo símbolo de nível de módulo passa a ter ao menos uma referência na árvore ou justificativa declarada.",
        "nonfunctional": "A remoção não pode deixar import, constante ou auxiliar órfão no mesmo arquivo.",
        "invariants": "A suíte de testes precisa continuar aprovando depois da remoção, sem teste novo que apenas cubra o símbolo removido.",
        "acceptance": "A varredura não reporta mais o símbolo e o gate de lint não acusa import órfão.",
        "edge": "Símbolo usado por getattr, por nome montado ou por framework precisa entrar na lista de nomes ignorados, com justificativa escrita.",
        "tests": "Teste de detecção em árvore temporária e execução da suíte completa após a remoção.",
        "docs": "config/hygiene-policy.json quando a decisão for declarar o nome ignorado.",
        "risks": "Uso dinâmico não visível ao analisador estático transforma remoção em quebra de comportamento.",
    },
    "unused-dependency": {
        "title": "Higiene: dependência declarada e nunca importada",
        "objective": "Alinhar o manifest ao que o código realmente importa.",
        "context": "A dependência está declarada em manifest de requisito e nenhum módulo daquele escopo a importa. Declaração sem uso amplia a superfície de risco e o tempo de instalação sem contrapartida.",
        "scope": "Remover a declaração do manifest, ou declarar a dependência como ferramenta executada na política quando ela for executada e não importada.",
        "functional": "Todo requisito declarado corresponde a um import efetivo no escopo do manifest ou a uma ferramenta declarada.",
        "nonfunctional": "A remoção exige regenerar o lockfile do manifest pela ferramenta do repositório, e não por edição manual.",
        "invariants": "O lockfile precisa continuar em paridade com o manifest, verificado por scripts/validate_dependency_locks.py.",
        "acceptance": "A varredura não reporta mais a dependência e o lockfile regenerado continua aprovando no validador de dependências.",
        "edge": "Nome de distribuição diferente do nome de import precisa estar no mapa declarado da política; ausência no mapa não pode virar aprovação silenciosa.",
        "tests": "Teste de detecção em manifest temporário e execução de scripts/validate_dependency_locks.py --root .",
        "docs": "config/hygiene-policy.json para a classe de ferramenta; manifest e lockfile do escopo afetado.",
        "risks": "Dependência importada por caminho indireto ou em execução condicional pode parecer sem uso.",
    },
    "complexity": {
        "title": "Higiene: complexidade acima do teto declarado",
        "objective": "Reduzir a complexidade das funções acima do teto, começando pelas de maior valor.",
        "context": "A varredura mede complexidade ciclomática por função e compara com o teto declarado na política. A classe é reportada com linha de base: a dívida pré-existente é medida e visível, e a linha de base só pode diminuir.",
        "scope": "Extrair decisões para funções nomeadas, tabelas de despacho ou validadores menores, sem alterar o contrato observável de cada função.",
        "functional": "Cada função listada passa a ficar no teto declarado, ou a linha de base é reduzida na medida do que for corrigido.",
        "nonfunctional": "A extração não pode criar dependência circular nem aumentar a contagem de duplicação.",
        "invariants": "A linha de base não pode crescer; função nova acima do teto não pode ser absorvida por rebaixamento silencioso do limiar.",
        "acceptance": "A contagem aberta da classe é menor ou igual à linha de base declarada, e a política registra a nova linha de base na mesma entrega.",
        "edge": "Função que concentra despacho por tabela pode justificar teto próprio declarado na política, com o motivo escrito.",
        "tests": "Teste que fixa a linha de base e falha quando ela cresce; suíte completa para garantir comportamento preservado.",
        "docs": "config/hygiene-policy.json com a linha de base atualizada na mesma entrega.",
        "risks": "Refatoração ampla sem cobertura suficiente troca dívida de complexidade por regressão funcional.",
    },
}

FORA_DE_ESCOPO = "Implementar a correção dentro da própria varredura de higiene: o perfil relata e propõe, quem implementa é o controlador de entrega."


def work_item_id(class_name: str, finding_ids: list[str]) -> str:
    digest = hashlib.sha256("\u0000".join(sorted(finding_ids)).encode("utf-8")).hexdigest()[:16]
    return f"hygiene-{class_name}-{digest}"


def render_body(root_label: str, class_name: str, entry: dict, findings: list[dict]) -> str:
    text = CLASS_TEXT[class_name]
    scope_lines = []
    for finding in findings:
        state = "aberto" if finding["state"] == "open" else "aceito por excecao declarada"
        scope_lines.append(f"- `{finding['location']}` ({state}) — {finding['detail']}")
    lines = [
        "## Objetivo",
        "",
        text["objective"],
        "",
        "## Contexto",
        "",
        text["context"],
        "",
        f"A varredura em `{root_label}` encontrou {len(findings)} achado(s) nesta classe, com teto e "
        f"limites declarados em `config/hygiene-policy.json`.",
        "",
        "## Escopo",
        "",
        *scope_lines,
        "",
        "## Fora de escopo",
        "",
        f"- {FORA_DE_ESCOPO}",
        "",
        "## Requisitos funcionais",
        "",
        f"1. {text['functional']}",
        "2. A política de higiene é atualizada na mesma entrega quando a decisão mudar o estado da classe.",
        "",
        "## Requisitos não funcionais",
        "",
        f"- {text['nonfunctional']}",
        "- A varredura continua determinística e offline depois da correção.",
        "",
        "## Invariantes",
        "",
        f"- {text['invariants']}",
        "- Nenhum limiar pode ser afrouxado para absorver achado novo.",
        "",
        "## Critérios de aceite",
        "",
        f"- {text['acceptance']}",
        "- `python higienizar-repositorio/scripts/validate_hygiene.py --root .` aprova com a política atualizada.",
        "- A suíte completa de testes continua aprovando.",
        "",
        "## Cenários e casos extremos",
        "",
        f"- {text['edge']}",
        "- Achado que deixa de existir sem atualização da política reprova o validador, porque exceção órfã esconde dívida que já não existe.",
        "",
        "## Considerações de testes",
        "",
        f"- {text['tests']}",
        "- Teste de regressão da classe, com fixture que reproduz o achado e confirma a detecção.",
        "",
        "## Impacto na documentação",
        "",
        f"- {text['docs']}",
        "",
        "## Riscos e dependências",
        "",
        f"- {text['risks']}",
        "- Evidência da varredura: `python higienizar-repositorio/scripts/hygiene_scan.py --root . --report <arquivo>`.",
    ]
    return "\n".join(lines) + "\n"


def build_work_items(root: Path, report: dict) -> list[dict]:
    items: list[dict] = []
    for entry in report["classes"]:
        findings = entry["findings"]
        if not findings:
            continue
        class_name = entry["name"]
        finding_ids = [finding["id"] for finding in findings]
        items.append(
            {
                "schema_version": 1,
                "system": "hygiene-work-item",
                "class": class_name,
                "id": work_item_id(class_name, finding_ids),
                "title": CLASS_TEXT[class_name]["title"],
                "finding_ids": finding_ids,
                "body_markdown": render_body(".", class_name, entry, findings),
            }
        )
    return items


def work_item_schema_errors(items: list[dict]) -> list[str]:
    """Contrato do próprio work item, conferido em memória antes de qualquer escrita."""
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "hygiene-work-item.schema.json"
    if not schema_path.is_file():
        return ["schema do work item ausente"]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        from jsonschema import Draft202012Validator
    except (OSError, json.JSONDecodeError, ImportError) as error:
        return [f"schema do work item indisponivel ({error.__class__.__name__})"]
    validator = Draft202012Validator(schema)
    return [
        f"work item {item.get('id')}: {list(error.path)}: {error.message}"
        for item in items
        for error in validator.iter_errors(item)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera work items a partir do relatorio de higiene")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None, help="relatorio existente")
    parser.add_argument("--out-dir", type=Path, default=None, help="diretorio de saida dos work items")
    parser.add_argument("--json", action="store_true", help="imprime os work items no stdout")
    args = parser.parse_args(argv)
    root = (args.root or Path()).resolve()
    try:
        if args.out_dir is not None:
            # Work item é evidência sobre a árvore: gravado dentro dela entra no corpus de citação e pode
            # apagar a dívida que ele mesmo descreve, como já vale para o relatório.
            write_target(args.out_dir, root, "--out-dir")
            # `exists()` segue link e mente para link quebrado: o destino é conferido pelo que existe
            # de fato no sistema de arquivos, e nao pelo que o link aponta.
            if (args.out_dir.is_symlink() or args.out_dir.exists()) and not args.out_dir.is_dir():
                print(f"ERRO: {args.out_dir} existe e nao e diretorio", file=sys.stderr)
                return 2
            if args.out_dir.is_dir() and any(args.out_dir.iterdir()):
                # Reutilizar o diretório conservaria work item de execução anterior, e dívida já
                # corrigida continuaria publicada como se fosse atual.
                print(
                    f"ERRO: {args.out_dir} ja tem conteudo; use diretorio novo para nao conservar work item obsoleto",
                    file=sys.stderr,
                )
                return 2
        # O contrato do relatório vem primeiro: relatório de outra ferramenta reprova antes de qualquer
        # leitura de conteúdo, e sem depender da política da árvore.
        report = None
        if args.report is not None:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            problems = schema_errors(report)
            if problems:
                print("ERRO: relatorio nao atende ao contrato:", file=sys.stderr)
                for problem in problems[:5]:
                    print(f"- {problem}", file=sys.stderr)
                return 2
        # Work item é evidência sobre a árvore: publicá-lo a partir de política que o gate reprova, de
        # relatório que não corresponde à árvore e à política atuais, ou de varredura com buraco de
        # cobertura produziria artefato que ninguém pode aceitar. O relatório externo entra pela mesma
        # porta, e não por uma porta mais fraca.
        policy = load_policy(root)
        errors = policy_errors(policy)
        if errors:
            print("ERRO: politica invalida:", file=sys.stderr)
            for error in errors[:5]:
                print(f"- {error}", file=sys.stderr)
            return 2
        current, problems = build_report(root, policy)
        if problems:
            print("ERRO: varredura com problema:", file=sys.stderr)
            for problem in problems[:5]:
                print(f"- {problem}", file=sys.stderr)
            return 2
        if report is not None and report != current:
            # Relatorio de outra arvore, de outra politica ou de outra execucao descreveria uma arvore
            # que nao e a atual, e o work item publicaria divida que ja nao existe ou que nunca existiu.
            print(
                "ERRO: relatorio nao corresponde a arvore e a politica atuais; gere-o de novo",
                file=sys.stderr,
            )
            return 2
        problems = schema_errors(current)
        if problems:
            print("ERRO: relatorio reconstruido nao atende ao contrato:", file=sys.stderr)
            for problem in problems[:5]:
                print(f"- {problem}", file=sys.stderr)
            return 2
        report = current
    except (HygieneError, json.JSONDecodeError, OSError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 2
    items = build_work_items(root, report)
    # O work item tambem passa pelo proprio contrato antes de sair: relatorio valido pode carregar
    # combinacao que o contrato do work item recusa, e o artefato nao pode nascer invalido.
    problems = work_item_schema_errors(items)
    if problems:
        print("ERRO: work item nao atende ao contrato:", file=sys.stderr)
        for problem in problems[:5]:
            print(f"- {problem}", file=sys.stderr)
        return 2
    # Por ultimo, o relatorio precisa ser aceito pela politica e pela arvore atuais: relatorio antigo,
    # de outra arvore ou com buraco de cobertura nao pode virar work item.
    problems = coverage_errors(root, report, policy)
    if problems:
        print("ERRO: relatorio reprovado pela politica e pela arvore atuais:", file=sys.stderr)
        for problem in problems[:5]:
            print(f"- {problem}", file=sys.stderr)
        return 2
    if args.json or args.out_dir is None:
        sys.stdout.write(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
        return 0
    try:
        args.out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        # Falha de criação da saída não pode sair como exceção crua: o diretório é artefato, e artefato
        # que não nasce por inteiro não pode parecer publicado.
        print(f"ERRO: falha ao criar {args.out_dir}: {error}", file=sys.stderr)
        return 1
    for item in items:
        (args.out_dir / f"{item['id']}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.out_dir / f"{item['id']}.md").write_text(item["body_markdown"], encoding="utf-8")
    print(f"{len(items)} work item(s) escritos em {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
