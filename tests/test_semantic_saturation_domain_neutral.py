"""Regressao: exemplos de incidentes nao se tornam politica universal."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERIC_PATHS = (
    "auditar-issue/SKILL.md",
    "entregar-issue/SKILL.md",
    "auditar-issue/references/blocker-harvest.md",
    "auditar-issue/references/semantic-mutation-saturation.md",
    "entregar-issue/references/semantic-mutation-saturation.md",
)
CASE_PATH = "docs/case-studies/issue-1300-semantic-saturation.md"
CASE_ONLY = re.compile(r"(?i)\b(?:F41|F42|foodName|controle_calorias)\b|issue\s*#?\s*1300|\baliment(?:o|os|ar|ares)\b")

class SemanticSaturationDomainNeutralTests(unittest.TestCase):
    def test_normative_skills_do_not_require_case_specific_findings(self):
        for path in GENERIC_PATHS:
            with self.subTest(path=path):
                content = (ROOT / path).read_text(encoding="utf-8")
                self.assertIsNone(CASE_ONLY.search(content), path)
                self.assertNotIn(CASE_PATH, content)

    def test_both_skills_have_generic_saturation_contract(self):
        for skill in ("auditar-issue", "entregar-issue"):
            with self.subTest(skill=skill):
                entry = (ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
                reference = (ROOT / skill / "references/semantic-mutation-saturation.md").read_text(encoding="utf-8")
                self.assertIn("references/semantic-mutation-saturation.md", entry)
                self.assertIn("pairwise", entry)
                self.assertIn("controle", reference.lower())
                self.assertIn("escopo", reference.lower())
                self.assertIn("caso", reference.lower())

    def test_historical_case_is_separate_and_explicitly_non_normative(self):
        case = (ROOT / CASE_PATH).read_text(encoding="utf-8")
        for token in ("Issue #1300", "F41/F42", "nao normativo", "Nao carregar"):
            with self.subTest(token=token):
                self.assertIn(token, case)


if __name__ == "__main__":
    unittest.main()
