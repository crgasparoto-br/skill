import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class InputParserSkillContractTests(unittest.TestCase):
    def test_reference_is_hardened(self):
        text=(ROOT/"references"/"input-parser-gate.md").read_text(encoding="utf-8")
        for token in ("consumed_fields","mode_field_scope_matrix","scalar-container","limit-plus-one","valid-plus-external-padding-over-limit","IP-SCOPE-001","all-consumed-fields-covered"): self.assertIn(token,text)
if __name__=="__main__": unittest.main()
