from __future__ import annotations

import unittest

from context_framework import USE_CASES, USE_CASE_INDEX, validate_use_case_catalog


class TriProviderUseCaseCatalogTests(unittest.TestCase):
    def test_catalog_has_expected_size(self) -> None:
        self.assertGreaterEqual(len(USE_CASES), 14)
        self.assertEqual(len(USE_CASES), len(USE_CASE_INDEX))

    def test_catalog_validation_passes(self) -> None:
        validate_use_case_catalog(USE_CASES)

    def test_each_spec_has_required_quality_fields(self) -> None:
        for spec in USE_CASES:
            self.assertTrue(spec.use_case_id.strip())
            self.assertTrue(spec.title.strip())
            self.assertTrue(spec.objective.strip())
            self.assertTrue(spec.system_prompt.strip())

            self.assertTrue(spec.openai.model.strip())
            self.assertTrue(spec.openai.prompt.strip())
            self.assertTrue(spec.openai.json_schema_name.strip())
            self.assertEqual(spec.openai.json_schema.get("type"), "object")
            self.assertTrue(spec.openai.json_schema.get("required"))

            self.assertTrue(spec.anthropic.model.strip())
            self.assertTrue(spec.anthropic.prompt.strip())
            self.assertGreater(spec.anthropic.max_tokens, 0)

            self.assertTrue(spec.cerebras.model.strip())
            self.assertTrue(spec.cerebras.prompt.strip())
            self.assertGreater(spec.cerebras.max_completion_tokens, 0)


if __name__ == "__main__":
    unittest.main()
