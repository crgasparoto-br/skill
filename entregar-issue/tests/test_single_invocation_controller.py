import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SingleInvocationControllerTests(unittest.TestCase):
    def test_skill_declares_neutral_audit_handoff(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("pacote neutro", text)
        self.assertIn("auditar-issue", text)
        self.assertIn("delivery-single-invocation", text)
        self.assertNotIn("Invocar `orquestrador`", text)

    def test_controller_reference_forbids_new_prompt(self):
        text = (ROOT / "references" / "controller-single-invocation.md").read_text(encoding="utf-8")
        self.assertIn("nao pedir nova conversa", text)


if __name__ == "__main__":
    unittest.main()
