from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
SKILL=(ROOT/'SKILL.md').read_text(encoding='utf-8')
REFERENCE=(ROOT/'references/handoff-recertification.md').read_text(encoding='utf-8')
class HandoffBoundaryContractTest(unittest.TestCase):
 def test_delegated_ci_returns_to_finalize_after_ci(self):
  self.assertIn('next_phase=finalize-after-ci', SKILL)
  self.assertIn('ci_owner_closed=true', SKILL)
  self.assertIn('nao invoca `entregar-issue`', REFERENCE.lower())
 def test_skill_never_owns_delivery_artifacts(self):
  self.assertIn('Nunca editar, copiar, corrigir ou regenerar diretamente `.audit/entregar-issue/*`', SKILL)
  self.assertIn('nao publica `.audit/entregar-issue/*`', REFERENCE.lower())
 def test_no_recursive_controller_ping_pong(self):
  self.assertIn('entregar [nivel 0] -> corrigir [subrotina] -> entregar.finalize-after-ci [terminal]', REFERENCE)
  self.assertNotIn('Executar imediatamente `entregar-issue` na mesma invocacao', SKILL)
 def test_no_repository_or_issue_specific_coupling(self):
  combined=(SKILL+'\n'+REFERENCE).lower();self.assertNotIn('solverfin',combined);self.assertNotRegex(combined,r'issue\s+#?\d+');self.assertNotRegex(combined,r'pr\s+#?\d+')
if __name__=='__main__':unittest.main()
