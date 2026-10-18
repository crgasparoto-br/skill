"""Issue 88: every new Keycloak resource requires named, reviewable metadata.

This offline test checks documentation only. It does NOT claim the objects
exist in Keycloak or that their permissions have been validated.
"""
import unittest
from pathlib import Path


DOC = (Path(__file__).resolve().parent / "deploy" / "keycloak" /
       "DELIVERY_SCOPE_HOMOLOGATION.md")


class KeycloakDescriptionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text(encoding="utf-8")

    def test_all_new_resources_have_purpose_and_issue_reference(self):
        for kind, name, phrase in (
            ("Realm Role", "solverit-delivery-operator", "Autoriza operadores aprovados"),
            ("Client Scope", "solverit:deliver", "Escopo OAuth opcional"),
            ("Audience Mapper", "solverit-delivery-mcp-audience", "Inclui a audiência"),
        ):
            with self.subTest(name=name):
                # Match the exact table cell rather than unrelated test-case
                # rows that mention the same role or scope in narrative text.
                prefix = "| " + kind + " | " + chr(96) + name + chr(96) + " |"
                rows = [line for line in self.text.splitlines()
                        if line.startswith(prefix)]
                self.assertEqual(len(rows), 1, rows)
                self.assertIn("Issue #88", rows[0])
                self.assertIn(phrase, rows[0])

    def test_mapper_without_description_field_is_explicitly_documented(self):
        self.assertIn("does not expose a Description field", self.text)
        self.assertIn("mandatory **Name** field", self.text)
        self.assertIn("Included Client", self.text)

    def test_does_not_claim_provisioning_or_bypass_authorization(self):
        self.assertIn("not proof of", self.text)
        self.assertIn("Never put user identifiers", self.text)
        self.assertIn("solverit:read", self.text)
        self.assertIn("auditor permissions remain", self.text)


if __name__ == "__main__":
    unittest.main()
