# Usando as skills com diferentes IAs

## Princípio comum

Cada skill é uma pasta autocontida. O arquivo `SKILL.md` contém o gatilho e o fluxo principal; as referências, schemas e scripts complementam a execução. A plataforma deve carregar primeiro o `SKILL.md` e somente depois as referências que ele indicar.

Não é necessário transformar a skill em um prompt monolítico. A separação reduz contexto desperdiçado e mantém contratos verificáveis próximos dos utilitários que os validam.

## Prompt genérico

O seguinte padrão funciona em qualquer assistente que aceite arquivos ou instruções de projeto:

```text
Você tem acesso à skill localizada em ./<nome-da-skill>.
Leia ./<nome-da-skill>/SKILL.md antes de executar a tarefa.
Respeite os modos, gates, invariantes e limites de escrita definidos pela skill.
Carregue referências, schemas e scripts somente quando o SKILL.md solicitar.
Não trate snapshots ou alegações do implementador como auditoria independente.
```

Substitua `<nome-da-skill>` por uma das pastas do catálogo.

## Integração por tipo de produto

| Ambiente | Como integrar | O que não é obrigatório |
| --- | --- | --- |
| ChatGPT/Codex/API | Anexar a pasta como skill, instruções de projeto ou contexto de agente. | `agents/openai.yaml`, quando a interface não o reconhecer |
| Claude | Adicionar `SKILL.md` às instruções do projeto e manter as referências no mesmo diretório. | Formatos específicos da OpenAI |
| Gemini | Fornecer `SKILL.md` como instrução do Gems/agente e anexar referências conforme o modo. | `agents/openai.yaml` |
| Cursor/Cline/IDE | Converter o conteúdo em regra do projeto ou incluir o caminho da pasta nas regras do agente. | Carregar todos os testes no contexto a cada solicitação |
| Aplicação própria | Armazenar metadados, selecionar a skill pelo `description` e montar contexto progressivo. | Acoplar o runtime ao formato de uma plataforma específica |

## Seleção por descrição

O `description` do frontmatter é o mecanismo primário de seleção. Um integrador pode indexar cada `SKILL.md` por esse campo e selecionar a skill quando a solicitação combinar com o domínio e os gatilhos descritos.

A seleção não deve ser feita apenas pelo nome da pasta. Por exemplo, `entregar-issue` é o controlador de entrega, enquanto `auditar-issue` é uma etapa somente leitura e independente; escolher a segunda apenas porque a solicitação menciona uma issue produziria um fluxo incorreto.

## Referências e caminhos

Ao copiar uma skill para outro projeto, copie a pasta inteira. Os links para `references/`, `schemas/`, `contracts/` e `scripts/` são relativos à raiz da skill. Não mova arquivos individuais sem ajustar os caminhos e sem executar a validação.

Os arquivos `agents/openai.yaml` são adaptadores opcionais. Eles podem conter nomes de produtos ou convenções específicas da OpenAI, mas o comportamento normativo deve permanecer em `SKILL.md` e nos artefatos agnósticos.

## Testes

Os testes não são instruções para o modelo; são evidência executável para quem mantém a skill. Execute-os no repositório clonado e use os resultados para detectar regressões após alterar contratos ou referências.

```bash
python scripts/validate_repository.py
pytest -q <nome-da-skill>/tests
```

Para skills sem `tests/`, a validação mínima é a existência de `SKILL.md`, frontmatter válido e referências presentes.
