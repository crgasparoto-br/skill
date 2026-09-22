# Registry declarativo de gates

`contracts/gate-registry.json` e a fonte canonica para ativacao dos gates gerais do planner. `plan_execution.py` deve derivar `required_gates` desse registry; nao manter uma segunda lista hardcoded.

Cada gate declara `activate_when`, controles estaveis e os estagios que sua evidencia pode invalidar. Gates especializados ainda podem ter referencias proprias, mas o entrypoint deve apenas reconhecer o sinal e carregar a referencia correspondente.

## Regra de crescimento

Antes de adicionar um novo invariant global ao `SKILL.md`, verificar se a falha pode ser representada por uma risk family/gate existente. Quando puder, adicionar controle, fixture, caso irmao ou regra na referencia/registry existente. Criar nova familia somente quando a classe de risco realmente nao couber nas familias atuais.
