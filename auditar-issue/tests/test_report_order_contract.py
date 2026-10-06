import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReportOrderContractTests(unittest.TestCase):
    def test_report_starts_with_result(self):
        text = (ROOT / "references" / "report-template.md").read_text(encoding="utf-8")
        first = next(line.strip() for line in text.splitlines() if line.strip())
        self.assertTrue(first.startswith("# RESULTADO:"), first)

    def test_skill_requires_result_before_any_preamble(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("A primeira informacao visivel deve ser o resultado", text)
        self.assertIn("# RESULTADO: APROVADA", text)
        self.assertIn("# RESULTADO: INCONCLUSIVA", text)
        self.assertIn("# RESULTADO: REPROVADA", text)
        self.assertIn("**Libera merge/release:** [SIM | NAO]", text)

    def test_internal_approval_never_releases(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Para `APROVADA INTERNAMENTE`, `INCONCLUSIVA` e `REPROVADA`, usar sempre `NAO`", text)

    def test_rejected_report_preserves_delivery_origin(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        report = (ROOT / "references" / "report-template.md").read_text(encoding="utf-8")
        direct = "@Entregar Issue implementar pendencias desta auditoria"
        self.assertIn(direct, skill)
        self.assertIn(direct, report)
        self.assertIn("delivery_origin=standalone-unknown", report)
        self.assertNotIn("Orquestrador", skill + report)
        self.assertIn("Nao exibir opcao em `APROVADA`", skill)
        self.assertIn("Omitir toda esta secao em `APROVADA`", report)


if __name__ == "__main__":
    unittest.main()
