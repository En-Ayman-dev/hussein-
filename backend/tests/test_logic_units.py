import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from generation.answer_validator import AnswerValidator
from generation.answer_composer import AnswerComposer
from processing.concept_matcher import ConceptMatch
from processing.query_analyzer import QueryIntent, QueryAnalysis
from processing.relation_expander import ExpandedRelation, RelationExpander


def build_concept(
    uri: str,
    labels: list[str],
    definition: list[str] | None = None,
    quote: list[str] | None = None,
    actions: list[str] | None = None,
    importance: list[str] | None = None,
):
    return SimpleNamespace(
        uri=uri,
        labels=labels,
        definition=definition or [],
        quote=quote or [],
        actions=actions or [],
        importance=importance or [],
    )


class RelationExpansionUnitTests(unittest.TestCase):
    def test_recursive_expansion_respects_direction_and_depth(self) -> None:
        expander = RelationExpander("sqlite://", max_relations=8, max_depth=2)

        concept_a = build_concept("A", ["أ"])
        concept_b = build_concept("B", ["ب"])
        concept_c = build_concept("C", ["ج"])
        concepts = {"A": concept_a, "B": concept_b, "C": concept_c}

        relation_ab = SimpleNamespace(id=1, source_uri="A", target_uri="B", type=SimpleNamespace(value="causes"))
        relation_bc = SimpleNamespace(id=2, source_uri="B", target_uri="C", type=SimpleNamespace(value="causes"))
        relation_map = {
            "A": [relation_ab],
            "B": [relation_bc],
            "C": [],
        }

        with patch.object(
            expander,
            "_get_direct_relations",
            side_effect=lambda db, uri, relation_types, direction="both": relation_map.get(uri, []),
        ), patch.object(
            expander,
            "_get_concept_by_uri",
            side_effect=lambda db, uri: concepts.get(uri),
        ):
            result = expander._expand_relations_recursive(None, "A", [])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].relation.id, 1)
        self.assertEqual(result[0].depth, 0)
        self.assertEqual(result[1].relation.id, 2)
        self.assertEqual(result[1].depth, 1)
        self.assertEqual(result[0].target_concept.uri, "B")

    def test_filter_and_rank_relations_removes_duplicates_and_honors_limit(self) -> None:
        expander = RelationExpander("sqlite://", max_relations=2, max_depth=2)
        concept = build_concept("A", ["أ"])

        relations = [
            ExpandedRelation(
                relation=SimpleNamespace(id=10, source_uri="A", target_uri="B", type=SimpleNamespace(value="relatedTo")),
                source_concept=concept,
                target_concept=build_concept("B", ["ب"]),
                depth=1,
                relevance_score=0.4,
            ),
            ExpandedRelation(
                relation=SimpleNamespace(id=10, source_uri="A", target_uri="B", type=SimpleNamespace(value="relatedTo")),
                source_concept=concept,
                target_concept=build_concept("B", ["ب"]),
                depth=0,
                relevance_score=0.9,
            ),
            ExpandedRelation(
                relation=SimpleNamespace(id=11, source_uri="A", target_uri="C", type=SimpleNamespace(value="relatedTo")),
                source_concept=concept,
                target_concept=build_concept("C", ["ج"]),
                depth=0,
                relevance_score=0.8,
            ),
        ]

        filtered = expander._filter_and_rank_relations(relations)

        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0].relation.id, 10)
        self.assertEqual(filtered[1].relation.id, 11)


class AnswerValidationUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = AnswerValidator()
        self.concept = build_concept(
            "concept:quran",
            ["القرآن"],
            definition=["كتاب الله المنزل على نبيه محمد"],
            quote=["كتاب الله المنزل"],
            actions=["يجب التمسك به"],
        )
        self.concept_match = ConceptMatch(
            concept=self.concept,
            confidence=0.95,
            match_type="exact_label",
            matched_text="القرآن",
        )

    def test_validator_flags_unsupported_definition_claim(self) -> None:
        validation = self.validator.validate_answer(
            answer="القرآن هو فلسفة بشرية محضة.",
            intent=QueryIntent.DEFINITION,
            concept_match=self.concept_match,
            relation_result=None,
        )

        self.assertFalse(validation.is_valid)
        self.assertGreater(len(validation.invalid_claims), 0)

    def test_validator_marks_very_short_answers_with_issue(self) -> None:
        validation = self.validator.validate_answer(
            answer="القرآن فقط",
            intent=QueryIntent.DEFINITION,
            concept_match=self.concept_match,
            relation_result=None,
        )

        self.assertIn("الإجابة قصيرة جداً", validation.issues)

    def test_validator_can_regenerate_when_answer_is_invalid(self) -> None:
        composer = Mock()
        composer.compose_answer.return_value = SimpleNamespace(answer="القرآن هو كتاب الله المنزل على نبيه محمد.")

        final_answer, validation = self.validator.validate_and_regenerate(
            answer="القرآن هو فلسفة بشرية محضة.",
            intent=QueryIntent.DEFINITION,
            question="ما هو القرآن؟",
            concept_match=self.concept_match,
            relation_result=None,
            answer_composer=composer,
        )

        self.assertEqual(final_answer, "القرآن هو كتاب الله المنزل على نبيه محمد.")
        self.assertTrue(validation.is_valid)
        composer.compose_answer.assert_called()

    def test_validator_skips_regeneration_when_attempts_disabled(self) -> None:
        validator = AnswerValidator(max_regeneration_attempts=0)
        composer = Mock()

        final_answer, validation = validator.validate_and_regenerate(
            answer="القرآن هو فلسفة بشرية محضة.",
            intent=QueryIntent.DEFINITION,
            question="ما هو القرآن؟",
            concept_match=self.concept_match,
            relation_result=None,
            answer_composer=composer,
        )

        self.assertEqual(final_answer, "القرآن هو فلسفة بشرية محضة.")
        self.assertFalse(validation.is_valid)
        composer.compose_answer.assert_not_called()


class AnswerComposerUnitTests(unittest.TestCase):
    def test_prepare_llm_context_includes_rich_supporting_evidence(self) -> None:
        composer = AnswerComposer(openai_api_key=None)
        primary = ConceptMatch(
            concept=build_concept(
                "concept:quran",
                ["القرآن"],
                definition=["كتاب الله المنزل على نبيه محمد."],
                quote=["كتاب الله المنزل على نبيه محمد."],
                actions=["الرجوع إليه في بناء الوعي."],
                importance=["رئيسي"],
            ),
            confidence=0.95,
            match_type="exact_label",
            matched_text="القرآن",
        )
        supporting = [
            ConceptMatch(
                concept=build_concept(
                    "concept:ayat",
                    ["آيات الله"],
                    definition=["حقائق إلهية هادية في مختلف مجالات الحياة."],
                    quote=["هي أعلام على حقائق من الهدى."],
                    actions=["التعامل معها كمصدر للمعرفة والهداية."],
                    importance=["رئيسي"],
                ),
                confidence=0.88,
                match_type="synonym",
                matched_text="آيات الله",
            ),
            ConceptMatch(
                concept=build_concept(
                    "concept:tadlil",
                    ["التضليل"],
                    definition=["إخفاء الحقائق وتزييفها لصرف الأمة عن أهدافها."],
                    quote=["من التضليل الشديد الذي يجيده اليهود."],
                    actions=["كشفه وفضحه وعدم التسليم له."],
                    importance=["رئيسي"],
                ),
                confidence=0.84,
                match_type="exact_label",
                matched_text="التضليل",
            ),
        ]

        context = composer._prepare_llm_context(
            QueryIntent.SOLUTION,
            "كيف يبني القرآن وعي الأمة في مواجهة التضليل؟",
            primary,
            None,
            QueryAnalysis(
                intent=QueryIntent.SOLUTION,
                confidence=1.0,
                keywords=["كيف", "القرآن", "وعي", "الأمة", "التضليل"],
                method="rules",
                query="كيف يبني القرآن وعي الأمة في مواجهة التضليل؟",
            ),
            supporting_matches=supporting,
        )

        self.assertIn("context_evidence", context)
        self.assertGreaterEqual(len(context["context_evidence"]["quotes"]), 3)
        self.assertGreaterEqual(len(context["context_evidence"]["definitions"]), 3)
        self.assertGreaterEqual(len(context["context_evidence"]["actions"]), 3)
        self.assertEqual(len(context["supporting_concepts"]), 2)
        self.assertIn("role_hint", context["supporting_concepts"][0])
        self.assertIn("foundational_quote", context["supporting_concepts"][0])
        self.assertIn("actions", context["supporting_concepts"][0])


if __name__ == "__main__":
    unittest.main()
