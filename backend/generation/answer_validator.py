import re
import logging
from typing import Dict, List, Set, Any, Optional, Tuple

from processing.query_analyzer import QueryIntent
from processing.concept_matcher import ConceptMatch
from processing.relation_expander import RelationExpansionResult, ExpandedRelation
from processing.text_normalizer import ArabicNormalizer

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of answer validation."""

    def __init__(
        self,
        is_valid: bool,
        score: float,
        issues: List[str],
        missing_concepts: List[str],
        invalid_claims: List[str],
        suggestions: List[str]
    ):
        """Initialize validation result.

        Args:
            is_valid: Whether the answer is valid
            score: Validation score (0-1)
            issues: List of validation issues
            missing_concepts: Concepts mentioned but not in context
            invalid_claims: Claims that don't match context
            suggestions: Suggestions for improvement
        """
        self.is_valid = is_valid
        self.score = score
        self.issues = issues
        self.missing_concepts = missing_concepts
        self.invalid_claims = invalid_claims
        self.suggestions = suggestions

    def __repr__(self) -> str:
        return f"ValidationResult(valid={self.is_valid}, score={self.score:.2f}, issues={len(self.issues)})"


class AnswerValidator:
    """Validates generated answers against provided context."""

    def __init__(self, max_regeneration_attempts: int = 2):
        """Initialize answer validator.

        Args:
            max_regeneration_attempts: Maximum regeneration attempts for invalid answers
        """
        self.text_normalizer = ArabicNormalizer()
        self.max_regeneration_attempts = max_regeneration_attempts

    def _extract_concepts_from_text(self, text: str) -> Set[str]:
        """Extract potential concept mentions from text.

        Args:
            text: Text to analyze

        Returns:
            Set of potential concept names
        """
        if not text:
            return set()

        # Normalize text
        normalized = self.text_normalizer.normalize_text(text)

        # Extract words that could be concepts (3+ characters, not common words)
        words = re.findall(r'\b\w{3,}\b', normalized)

        # Filter out common Arabic words and stop words
        common_words = {
            'الذي', 'التي', 'الذين', 'اللاتي', 'اللذان', 'اللتان', 'اللذين', 'اللواتي',
            'كان', 'كانت', 'كانوا', 'كانت', 'صار', 'صارت', 'صاروا', 'صارت',
            'أصبح', 'أصبحت', 'أصبحوا', 'أصبحت', 'ظل', 'ظلت', 'ظلوا', 'ظلت',
            'ليس', 'ليست', 'ليسوا', 'ليسن', 'ما', 'ماذا', 'كيف', 'أين', 'متى',
            'هذا', 'هذه', 'هؤلاء', 'ذاك', 'تكون', 'يكون', 'تكون', 'يصبح', 'تصبح',
            'أن', 'إن', 'لو', 'إذا', 'مع', 'عند', 'من', 'إلى', 'على', 'في', 'عن',
            'أو', 'و', 'لكن', 'بل', 'ثم', 'حتى', 'أيضا', 'كذلك', 'أي', 'كل', 'بعض'
        }

        concepts = set()
        for word in words:
            if word not in common_words and not word.isdigit():
                concepts.add(word)

        return concepts

    def _get_context_concepts(
        self,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult]
    ) -> Set[str]:
        """Extract all concepts available in context.

        Args:
            concept_match: Concept match result
            relation_result: Relation expansion result

        Returns:
            Set of concept names/labels in context
        """
        context_concepts = set()

        # Add main concept labels
        if concept_match and concept_match.concept.labels:
            for label in concept_match.concept.labels:
                normalized = self.text_normalizer.normalize_text(label)
                context_concepts.add(normalized)
                # Also add individual words from labels
                words = self._extract_concepts_from_text(label)
                context_concepts.update(words)

            for field_name in ("definition", "quote", "actions"):
                for value in getattr(concept_match.concept, field_name, None) or []:
                    normalized = self.text_normalizer.normalize_text(value)
                    context_concepts.add(normalized)
                    context_concepts.update(self._extract_concepts_from_text(value))

        # Add related concept labels
        if relation_result:
            for rel in relation_result.relations:
                for concept in (rel.source_concept, rel.target_concept):
                    if concept.labels:
                        for label in concept.labels:
                            normalized = self.text_normalizer.normalize_text(label)
                            context_concepts.add(normalized)
                            words = self._extract_concepts_from_text(label)
                            context_concepts.update(words)

                    for field_name in ("definition", "quote", "actions"):
                        for value in getattr(concept, field_name, None) or []:
                            normalized = self.text_normalizer.normalize_text(value)
                            context_concepts.add(normalized)
                            context_concepts.update(self._extract_concepts_from_text(value))

        return context_concepts

    def _check_concept_coverage(
        self,
        answer_concepts: Set[str],
        context_concepts: Set[str]
    ) -> Tuple[List[str], float]:
        """Check if answer concepts are covered by context.

        Args:
            answer_concepts: Concepts mentioned in answer
            context_concepts: Concepts available in context

        Returns:
            Tuple of (missing_concepts, coverage_score)
        """
        missing_concepts = []
        covered_count = 0

        for concept in answer_concepts:
            # Check if concept or its parts are in context
            concept_covered = False

            # Direct match
            if concept in context_concepts:
                concept_covered = True
            else:
                # Check if any word in concept is in context
                concept_words = concept.split()
                if any(word in context_concepts for word in concept_words):
                    concept_covered = True

            if concept_covered:
                covered_count += 1
            else:
                missing_concepts.append(concept)

        coverage_score = covered_count / len(answer_concepts) if answer_concepts else 1.0
        return missing_concepts, coverage_score

    def _validate_claims_against_context(
        self,
        answer: str,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult]
    ) -> List[str]:
        """Validate specific claims in answer against context.

        Args:
            answer: Generated answer
            concept_match: Concept match result
            relation_result: Relation expansion result

        Returns:
            List of invalid claims
        """
        invalid_claims = []

        if not concept_match:
            return invalid_claims

        # Check definition claims
        if concept_match.concept.definition:
            context_definitions = " ".join(concept_match.concept.definition)
            # Look for definition-like statements that don't match context
            definition_patterns = [
                r'هو\s+([^.،]+)',
                r'هي\s+([^.،]+)',
                r'يعني\s+([^.،]+)',
                r'تشير\s+إلى\s+([^.،]+)',
                r'المقصود\s+ب([^.،]+)',
            ]

            for pattern in definition_patterns:
                matches = re.findall(pattern, answer)
                for match in matches:
                    if match.strip() and match.strip() not in context_definitions:
                        # Check if it's a reasonable paraphrase
                        if not self._is_reasonable_paraphrase(match.strip(), context_definitions):
                            invalid_claims.append(f"تعريف غير موجود في السياق: '{match.strip()}'")

        # Check relation claims
        if relation_result:
            for rel in relation_result.relations:
                rel_type = rel.relation.type.value
                source_labels = " ".join(rel.source_concept.labels or [])
                target_labels = " ".join(rel.target_concept.labels or [])

                # Check for causal claims
                if rel_type == "causes":
                    cause_patterns = [
                        fr'{re.escape(source_labels)}\s+يسبب\s+{re.escape(target_labels)}',
                        fr'{re.escape(target_labels)}\s+بسبب\s+{re.escape(source_labels)}',
                    ]
                    for pattern in cause_patterns:
                        if re.search(pattern, answer):
                            break
                    else:
                        invalid_claims.append(f"علاقة سببية غير موجودة: {source_labels} ← {target_labels}")

        return invalid_claims

    def _is_reasonable_paraphrase(self, claim: str, context: str) -> bool:
        """Check if a claim is a reasonable paraphrase of context.

        Args:
            claim: Claim to check
            context: Context text

        Returns:
            True if reasonable paraphrase
        """
        # Simple heuristic: check for significant word overlap
        claim_words = set(self._extract_concepts_from_text(claim))
        context_words = set(self._extract_concepts_from_text(context))

        if not claim_words:
            return True

        overlap = len(claim_words.intersection(context_words))
        overlap_ratio = overlap / len(claim_words)

        return overlap_ratio >= 0.5  # At least 50% word overlap

    def validate_answer(
        self,
        answer: str,
        intent: QueryIntent,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult]
    ) -> ValidationResult:
        """Validate an answer against provided context.

        Args:
            answer: Generated answer to validate
            intent: Query intent
            concept_match: Concept match result
            relation_result: Relation expansion result

        Returns:
            Validation result
        """
        issues = []
        missing_concepts = []
        invalid_claims = []
        suggestions = []

        # Extract concepts from answer
        answer_concepts = self._extract_concepts_from_text(answer)

        # Get context concepts
        context_concepts = self._get_context_concepts(concept_match, relation_result)

        # Check concept coverage
        missing_concepts, coverage_score = self._check_concept_coverage(
            answer_concepts, context_concepts
        )

        if missing_concepts:
            issues.append(f"الإجابة تحتوي على {len(missing_concepts)} مفهوم غير موجود في السياق")
            suggestions.append("أعد صياغة الإجابة لتستخدم فقط المفاهيم المتاحة في السياق")

        # Validate specific claims
        invalid_claims = self._validate_claims_against_context(
            answer, concept_match, relation_result
        )

        if invalid_claims:
            issues.extend(invalid_claims)
            suggestions.append("تحقق من دقة المعلومات المقدمة في السياق")

        # Calculate overall score
        base_score = coverage_score
        if invalid_claims:
            base_score *= 0.5  # Penalize invalid claims

        # Length appropriateness
        if len(answer.split()) < 3:
            base_score *= 0.8
            issues.append("الإجابة قصيرة جداً")
            suggestions.append("قدم إجابة أكثر تفصيلاً")

        if len(answer.split()) > 200:
            base_score *= 0.9
            issues.append("الإجابة طويلة جداً")
            suggestions.append("اختصر الإجابة مع الحفاظ على المعلومات المهمة")

        # Determine validity
        is_valid = len(missing_concepts) == 0 and len(invalid_claims) == 0 and base_score >= 0.7

        return ValidationResult(
            is_valid=is_valid,
            score=base_score,
            issues=issues,
            missing_concepts=missing_concepts,
            invalid_claims=invalid_claims,
            suggestions=suggestions
        )

    def validate_and_regenerate(
        self,
        answer: str,
        intent: QueryIntent,
        question: str,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult],
        answer_composer: Optional[Any] = None
    ) -> Tuple[str, ValidationResult]:
        """Validate answer and regenerate if invalid.

        Args:
            answer: Initial answer
            intent: Query intent
            question: Original question
            concept_match: Concept match result
            relation_result: Relation expansion result
            answer_composer: Answer composer for regeneration

        Returns:
            Tuple of (final_answer, validation_result)
        """
        final_answer = answer
        validation = self.validate_answer(answer, intent, concept_match, relation_result)

        if validation.is_valid:
            logger.info(f"Answer validation passed (score: {validation.score:.2f})")
            return final_answer, validation

        logger.warning(f"Answer validation failed (score: {validation.score:.2f}): {validation.issues}")

        # Attempt regeneration if composer available
        attempted_regeneration = False
        if answer_composer and validation.invalid_claims and validation.score < 0.7:
            attempted_regeneration = True
            for attempt in range(self.max_regeneration_attempts):
                logger.info(f"Regeneration attempt {attempt + 1}/{self.max_regeneration_attempts}")

                try:
                    new_answer = answer_composer.compose_answer(
                        intent, question, concept_match, relation_result
                    )

                    new_validation = self.validate_answer(
                        new_answer.answer, intent, concept_match, relation_result
                    )

                    if new_validation.is_valid or new_validation.score > validation.score:
                        logger.info(f"Regeneration successful (score: {new_validation.score:.2f})")
                        return new_answer.answer, new_validation

                except Exception as e:
                    logger.error(f"Regeneration attempt {attempt + 1} failed: {e}")
                    continue

        if attempted_regeneration:
            logger.warning("All regeneration attempts failed")
        return final_answer, validation


# Convenience functions
def validate_ontology_answer(
    answer: str,
    intent: QueryIntent,
    concept_match: Optional[ConceptMatch] = None,
    relation_result: Optional[RelationExpansionResult] = None
) -> ValidationResult:
    """Convenience function to validate ontology answer."""
    validator = AnswerValidator()
    return validator.validate_answer(answer, intent, concept_match, relation_result)


def validate_and_regenerate_answer(
    answer: str,
    intent: QueryIntent,
    question: str,
    concept_match: Optional[ConceptMatch] = None,
    relation_result: Optional[RelationExpansionResult] = None,
    answer_composer: Optional[Any] = None
) -> Tuple[str, ValidationResult]:
    """Convenience function to validate and regenerate answer."""
    validator = AnswerValidator()
    return validator.validate_and_regenerate(
        answer, intent, question, concept_match, relation_result, answer_composer
    )


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Validate ontology answers")
    parser.add_argument("answer", help="Answer to validate")
    parser.add_argument("intent", choices=["definition", "cause", "solution", "comparison", "unknown"],
                       help="Query intent")
    parser.add_argument("--question", help="Original question")
    parser.add_argument("--regenerate", action="store_true", help="Attempt regeneration if invalid")

    args = parser.parse_args()

    # Convert intent
    from processing.query_analyzer import QueryIntent
    intent_map = {
        "definition": QueryIntent.DEFINITION,
        "cause": QueryIntent.CAUSE,
        "solution": QueryIntent.SOLUTION,
        "comparison": QueryIntent.COMPARISON,
        "unknown": QueryIntent.UNKNOWN
    }
    intent = intent_map[args.intent]

    validator = AnswerValidator()

    if args.regenerate and args.question:
        # This would need proper context in real usage
        final_answer, validation = validator.validate_and_regenerate(
            args.answer, intent, args.question, None, None, None
        )
    else:
        validation = validator.validate_answer(args.answer, intent, None, None)

    result = {
        "is_valid": validation.is_valid,
        "score": round(validation.score, 3),
        "issues": validation.issues,
        "missing_concepts": validation.missing_concepts,
        "invalid_claims": validation.invalid_claims,
        "suggestions": validation.suggestions
    }

    if args.regenerate:
        result["final_answer"] = final_answer

    print(json.dumps(result, ensure_ascii=False, indent=2))
