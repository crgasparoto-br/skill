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

    def test_conclusion_block_is_visible_right_after_result(self):
        text = (ROOT / "references" / "report-template.md").read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith("# RESULTADO:"), lines[0])
        block = lines[1:4]
        self.assertEqual(3, len(block), block)
        for linha, marcador in zip(block, ("**Conclusao:**", "**Motivo determinante:**", "**Libera merge/release:**"), strict=True):
            self.assertTrue(linha.startswith("> " + marcador), linha)
        cruas = text.splitlines()
        fim = cruas.index("> **Libera merge/release:** [SIM | NAO]")
        self.assertEqual("", cruas[fim + 1], "o bloco de conclusao precisa terminar em linha propria")
        self.assertTrue(cruas[fim + 2].startswith("**Validade:**"), cruas[fim + 2])

    def test_skill_conclusion_block_ends_before_metadata(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        linhas = [linha.strip() for linha in text.splitlines()]
        indice = linhas.index("> **Libera merge/release:** [SIM | NAO]")
        self.assertEqual("", linhas[indice + 1], "o bloco precisa terminar antes dos metadados")
        self.assertTrue(linhas[indice + 2].startswith("**Validade:**"), linhas[indice + 2])

    def test_skill_requires_conclusion_block_before_other_metadata(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("bloco de conclusao em destaque", text)
        self.assertIn("> **Conclusao:**", text)
        self.assertIn("> **Motivo determinante:**", text)
        self.assertIn("divergencia entre eles e defeito do parecer", text)

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
