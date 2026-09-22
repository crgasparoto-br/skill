from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / 'SKILL.md').read_text(encoding='utf-8')


class ControllerSeparationContractTests(unittest.TestCase):
    def test_delegated_ci_never_reenters_delivery_controller(self):
        self.assertIn('nunca invocar `entregar-issue` recursivamente', SKILL.lower())
        self.assertIn('nunca invocar `entregar-issue` ou `orquestrador` para executar a remediacao', SKILL.lower())

    def test_ci_skill_never_dispatches_delivery_v2(self):
        self.assertIn('nunca invocar `orquestrador` nem criar dispatch delivery v2', SKILL.lower())

    def test_standalone_mode_does_not_synthesize_direct_controller(self):
        self.assertIn('nao sintetizar `return_control_to=entregar-issue` sem caller delegado', SKILL.lower())


if __name__ == '__main__':
    unittest.main()
