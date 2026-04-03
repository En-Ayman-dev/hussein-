import logging
from typing import Dict, Any, Optional

from processing.query_analyzer import QueryIntent, QueryAnalysis
from processing.concept_matcher import ConceptMatch
from processing.relation_expander import RelationExpansionResult
from generation.answer_generator import AnswerGenerator, GeneratedAnswer
from services.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


def _clean_text_list(values: Any) -> list[str]:
    if not values:
        return []

    if not isinstance(values, list):
        values = [values]

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)

    return result


class AnswerComposer:
    """Composes final answers by choosing between template and LLM generation."""

    MAX_SUPPORTING_CONCEPTS = 3
    MAX_QUOTES = 4
    MAX_RELATIONS = 6
    MAX_ACTIONS = 3
    MAX_TEXT_LENGTH = 280
    MAX_MATCH_TEXT_LENGTH = 180
    MAX_DEFINITION_LENGTH = 320
    MAX_QUOTE_LENGTH = 420
    MAX_ACTION_LENGTH = 220
    MAX_EVIDENCE_QUOTES = 6
    MAX_EVIDENCE_DEFINITIONS = 6
    MAX_EVIDENCE_ACTIONS = 6

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        template_confidence_threshold: float = 0.7,
        llm_model: str = "gpt-4o-mini",
        llm_max_tokens: int = 1000
    ):
        """Initialize answer composer.

        Args:
            openai_api_key: OpenAI API key for LLM generation
            template_confidence_threshold: Minimum confidence to use templates
            llm_model: OpenAI model for LLM generation
            llm_max_tokens: Maximum tokens for LLM response
        """
        self.template_confidence_threshold = template_confidence_threshold
        self.openai_api_key = openai_api_key

        # Initialize generators
        self.template_generator = AnswerGenerator()

        if openai_api_key:
            try:
                self.llm_generator = OpenAIClient(
                    api_key=openai_api_key,
                    model=llm_model,
                    max_tokens=llm_max_tokens,
                    temperature=0.1  # Low temperature for consistent answers
                )
            except Exception as exc:
                logger.warning("LLM generation disabled: %s", exc)
                self.llm_generator = None
        else:
            self.llm_generator = None
            logger.warning("No OpenAI API key provided, LLM generation disabled")

    def _should_use_template(
        self,
        intent: QueryIntent,
        query_confidence: float,
        concept_confidence: Optional[float] = None,
        context_completeness: float = 0.0
    ) -> bool:
        """Decide whether to use template or LLM generation.

        Args:
            intent: Query intent
            query_confidence: Confidence in intent classification
            concept_confidence: Confidence in concept matching
            context_completeness: How complete the context is (0-1)

        Returns:
            True to use template, False to use LLM
        """
        if not self.llm_generator:
            return True

        if intent == QueryIntent.UNKNOWN:
            return True

        if not concept_confidence or concept_confidence <= 0:
            return True

        if context_completeness < 0.2 and query_confidence < 0.4:
            return True

        return False

    def _calculate_context_completeness(
        self,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult]
    ) -> float:
        """Calculate how complete the context is.

        Args:
            concept_match: Concept match result
            relation_result: Relation expansion result

        Returns:
            Completeness score (0-1)
        """
        completeness = 0.0

        # Concept completeness
        if concept_match:
            concept_score = 0.0
            if concept_match.concept.labels:
                concept_score += 0.3
            if concept_match.concept.definition:
                concept_score += 0.3
            if concept_match.concept.quote:
                concept_score += 0.2
            if concept_match.concept.actions or concept_match.concept.importance:
                concept_score += 0.2
            completeness += concept_score * 0.6  # 60% weight

        # Relations completeness
        if relation_result:
            relations_score = min(len(relation_result.relations) / 5.0, 1.0)  # Up to 5 relations
            completeness += relations_score * 0.4  # 40% weight

        return min(completeness, 1.0)

    def _prepare_llm_context(
        self,
        intent: QueryIntent,
        question: str,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult],
        query_analysis: Optional[QueryAnalysis] = None,
        supporting_matches: Optional[list[ConceptMatch]] = None,
    ) -> Dict[str, Any]:
        """Prepare structured context for LLM generation.

        Args:
            intent: Query intent
            question: Original question
            concept_match: Concept match result
            relation_result: Relation expansion result
            query_analysis: Query analysis result

        Returns:
            Structured context dictionary
        """
        context = {
            "intent": intent.value if intent else "unknown",
            "question": question,
        }

        if query_analysis:
            context["query_analysis"] = {
                "intent": query_analysis.intent.value,
                "confidence": query_analysis.confidence,
                "keywords": query_analysis.keywords[:6],
                "method": query_analysis.method
            }

        if concept_match:
            concept_labels = _clean_text_list(concept_match.concept.labels)
            concept_definitions = self._truncate_text_list(
                _clean_text_list(concept_match.concept.definition),
                limit=2,
                max_length=self.MAX_DEFINITION_LENGTH,
            )
            concept_quotes = self._truncate_text_list(
                _clean_text_list(concept_match.concept.quote),
                limit=self.MAX_QUOTES,
                max_length=self.MAX_QUOTE_LENGTH,
            )
            concept_actions = self._truncate_text_list(
                _clean_text_list(concept_match.concept.actions),
                limit=self.MAX_ACTIONS,
                max_length=self.MAX_ACTION_LENGTH,
            )
            concept_importance = self._truncate_text_list(
                _clean_text_list(concept_match.concept.importance),
                limit=2,
            )
            context["concept"] = {
                "primary_label": concept_labels[0] if concept_labels else None,
                "labels": self._truncate_text_list(concept_labels, limit=4),
                "definition": concept_definitions,
                "foundational_quote": concept_quotes,
                "actions": concept_actions,
                "importance": concept_importance,
                "match_confidence": concept_match.confidence,
                "match_type": concept_match.match_type,
                "matched_text": self._truncate_text(
                    concept_match.matched_text,
                    max_length=self.MAX_MATCH_TEXT_LENGTH,
                ),
            }

        context["context_evidence"] = self._build_context_evidence(
            concept_match,
            supporting_matches,
        )

        if supporting_matches:
            context["supporting_concepts"] = self._prepare_supporting_concepts(
                concept_match,
                supporting_matches,
            )

        if relation_result:
            context["relations"] = []
            grouped_relations = {
                "causes": [],
                "establishes": [],
                "opposes": [],
                "means_for": [],
                "related": [],
            }
            limited_relations = relation_result.relations[: self.MAX_RELATIONS]
            for rel in limited_relations:
                relation_data = {
                    "type": rel.relation.type.value,
                    "source_labels": self._truncate_text_list(
                        _clean_text_list(rel.source_concept.labels),
                        limit=2,
                    ),
                    "target_labels": self._truncate_text_list(
                        _clean_text_list(rel.target_concept.labels),
                        limit=2,
                    ),
                    "depth": rel.depth,
                    "relevance_score": rel.relevance_score
                }
                context["relations"].append(relation_data)

                relation_type = rel.relation.type.value
                if relation_type == "causes":
                    grouped_relations["causes"].append(relation_data)
                elif relation_type == "establishes":
                    grouped_relations["establishes"].append(relation_data)
                elif relation_type == "opposes":
                    grouped_relations["opposes"].append(relation_data)
                elif relation_type == "isMeansFor":
                    grouped_relations["means_for"].append(relation_data)
                else:
                    grouped_relations["related"].append(relation_data)

            context["relation_summary"] = {
                "total_found": relation_result.total_relations_found,
                "returned": len(limited_relations),
                "max_depth_reached": relation_result.max_depth_reached
            }
            context["grouped_relations"] = grouped_relations

        return context

    def _truncate_text(self, value: Optional[str], max_length: Optional[int] = None) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        effective_max_length = max_length if max_length is not None else self.MAX_TEXT_LENGTH
        if len(cleaned) <= effective_max_length:
            return cleaned
        return cleaned[:effective_max_length].rstrip() + "..."

    def _truncate_text_list(
        self,
        values: list[str],
        limit: int,
        max_length: Optional[int] = None,
    ) -> list[str]:
        truncated: list[str] = []
        for value in values[:limit]:
            cleaned = self._truncate_text(value, max_length=max_length)
            if cleaned:
                truncated.append(cleaned)
        return truncated

    def _clean_primary_label(self, match: ConceptMatch) -> Optional[str]:
        labels = _clean_text_list(match.concept.labels)
        return labels[0] if labels else None

    def _infer_supporting_role(self, match: ConceptMatch) -> str:
        support_text = " ".join(
            _clean_text_list(match.concept.labels)
            + _clean_text_list(match.concept.definition)
            + _clean_text_list(match.concept.actions)
        )

        if any(token in support_text for token in ["التضليل", "اليهود", "العدو", "خبث", "المنافق"]):
            return "يوضح جهة التضليل أو العدو في السؤال"
        if any(token in support_text for token in ["آيات", "الهدى", "الهداية", "البصيرة", "الوعي", "القرآن"]):
            return "يوضح وسيلة البناء والهداية في السؤال"
        if any(token in support_text for token in ["الأمة", "الناس", "المجتمع"]):
            return "يوضح ساحة المسؤولية الجماعية"
        return "مفهوم مساند يوضح جزءاً من الجواب"

    def _build_context_evidence(
        self,
        concept_match: Optional[ConceptMatch],
        supporting_matches: Optional[list[ConceptMatch]],
    ) -> Dict[str, list[Dict[str, str]]]:
        evidence = {
            "quotes": [],
            "definitions": [],
            "actions": [],
        }

        def add_items(bucket: str, label: Optional[str], values: list[str], limit: int) -> None:
            if not label:
                return
            max_length = {
                "quotes": self.MAX_QUOTE_LENGTH,
                "definitions": self.MAX_DEFINITION_LENGTH,
                "actions": self.MAX_ACTION_LENGTH,
            }.get(bucket, self.MAX_TEXT_LENGTH)

            for value in self._truncate_text_list(
                _clean_text_list(values),
                limit=limit,
                max_length=max_length,
            ):
                evidence[bucket].append({"label": label, "text": value})

        if concept_match:
            primary_label = self._clean_primary_label(concept_match)
            add_items("quotes", primary_label, concept_match.concept.quote or [], limit=2)
            add_items("definitions", primary_label, concept_match.concept.definition or [], limit=2)
            add_items("actions", primary_label, concept_match.concept.actions or [], limit=2)

        for match in supporting_matches or []:
            label = self._clean_primary_label(match)
            add_items("quotes", label, match.concept.quote or [], limit=2)
            add_items("definitions", label, match.concept.definition or [], limit=2)
            add_items("actions", label, match.concept.actions or [], limit=2)

        evidence["quotes"] = evidence["quotes"][: self.MAX_EVIDENCE_QUOTES]
        evidence["definitions"] = evidence["definitions"][: self.MAX_EVIDENCE_DEFINITIONS]
        evidence["actions"] = evidence["actions"][: self.MAX_EVIDENCE_ACTIONS]
        return evidence

    def _prepare_supporting_concepts(
        self,
        primary_match: Optional[ConceptMatch],
        supporting_matches: list[ConceptMatch],
    ) -> list[Dict[str, Any]]:
        primary_uri = getattr(getattr(primary_match, "concept", None), "uri", None)
        payload: list[Dict[str, Any]] = []

        for match in supporting_matches:
            if len(payload) >= self.MAX_SUPPORTING_CONCEPTS:
                break

            if match.concept.uri == primary_uri:
                continue

            labels = self._truncate_text_list(_clean_text_list(match.concept.labels), limit=3)
            if not labels:
                continue

            payload.append(
                {
                    "primary_label": labels[0],
                    "labels": labels,
                    "definition": self._truncate_text_list(
                        _clean_text_list(match.concept.definition),
                        limit=2,
                        max_length=self.MAX_DEFINITION_LENGTH,
                    ),
                    "foundational_quote": self._truncate_text_list(
                        _clean_text_list(match.concept.quote),
                        limit=2,
                        max_length=self.MAX_QUOTE_LENGTH,
                    ),
                    "actions": self._truncate_text_list(
                        _clean_text_list(match.concept.actions),
                        limit=2,
                        max_length=self.MAX_ACTION_LENGTH,
                    ),
                    "importance": self._truncate_text_list(
                        _clean_text_list(match.concept.importance),
                        limit=2,
                    ),
                    "match_confidence": match.confidence,
                    "match_type": match.match_type,
                    "role_hint": self._infer_supporting_role(match),
                }
            )

        return payload

    def compose_answer(
        self,
        intent: QueryIntent,
        question: str,
        concept_match: Optional[ConceptMatch] = None,
        relation_result: Optional[RelationExpansionResult] = None,
        query_analysis: Optional[QueryAnalysis] = None,
        supporting_matches: Optional[list[ConceptMatch]] = None,
    ) -> GeneratedAnswer:
        """Compose final answer by choosing between template and LLM generation.

        Args:
            intent: Query intent
            question: Original question
            concept_match: Best concept match
            relation_result: Relation expansion result
            query_analysis: Query analysis result

        Returns:
            Generated answer
        """
        if query_analysis is None:
            query_analysis = QueryAnalysis(
                intent=intent,
                confidence=0.5,
                keywords=[],
                method="fallback",
                query=question,
            )

        # Calculate context completeness
        context_completeness = self._calculate_context_completeness(concept_match, relation_result)

        # Get confidence scores
        query_confidence = query_analysis.confidence if query_analysis else 0.5
        concept_confidence = concept_match.confidence if concept_match else 0.0

        # Decide generation method
        use_template = self._should_use_template(
            intent, query_confidence, concept_confidence, context_completeness
        )

        logger.info(
            f"Composing answer: intent={intent.value}, "
            f"query_conf={query_confidence:.2f}, concept_conf={concept_confidence:.2f}, "
            f"context_comp={context_completeness:.2f}, use_template={use_template}"
        )

        if use_template:
            # Use template generation
            answer = self.template_generator.generate_answer(
                query_analysis,
                concept_match,
                relation_result,
                supporting_matches=supporting_matches,
            )
            answer.method = "template"
            logger.info("Used template generation")
            return answer

        elif self.llm_generator:
            # Use LLM generation
            context = self._prepare_llm_context(
                intent,
                question,
                concept_match,
                relation_result,
                query_analysis,
                supporting_matches,
            )
            logger.info(
                "LLM context budget prepared: supporting=%s relations=%s evidence_quotes=%s evidence_definitions=%s evidence_actions=%s",
                len(context.get("supporting_concepts", [])),
                len(context.get("relations", [])),
                len(context.get("context_evidence", {}).get("quotes", [])),
                len(context.get("context_evidence", {}).get("definitions", [])),
                len(context.get("context_evidence", {}).get("actions", [])),
            )
            fallback_answer = self.template_generator.generate_answer(
                query_analysis,
                concept_match,
                relation_result,
                supporting_matches=supporting_matches,
            )
            llm_result = self.llm_generator.generate_answer_with_fallback(
                context,
                question,
                fallback_answer=fallback_answer.answer,
            )

            # Create GeneratedAnswer object
            sources_used = []
            if concept_match:
                sources_used.append(f"concept:{concept_match.concept.uri}")
            if relation_result and relation_result.relations:
                sources_used.extend([f"relation:{rel.relation.id}" for rel in relation_result.relations])

            structured_data = {
                "generation_method": "llm",
                "context_completeness": context_completeness,
                "query_confidence": query_confidence,
                "concept_confidence": concept_confidence,
                "fallback_used": llm_result.content == fallback_answer.answer,
            }

            answer = GeneratedAnswer(
                answer=llm_result.content,
                intent=intent,
                confidence=min(query_confidence, concept_confidence) if concept_confidence > 0 else query_confidence,
                sources_used=sources_used,
                structured_data=structured_data,
                token_usage=llm_result.token_usage,
                method="template_fallback" if llm_result.content == fallback_answer.answer else "llm",
            )
            logger.info("Used %s generation", answer.method)
            return answer

        else:
            # Fallback to template if no LLM available
            logger.warning("No LLM available, falling back to template")
            answer = self.template_generator.generate_answer(
                query_analysis,
                concept_match,
                relation_result,
                supporting_matches=supporting_matches,
            )
            answer.method = "template_fallback"
            return answer


# Convenience functions
def compose_ontology_answer(
    intent: QueryIntent,
    question: str,
    concept_match: Optional[ConceptMatch] = None,
    relation_result: Optional[RelationExpansionResult] = None,
    query_analysis: Optional[QueryAnalysis] = None,
    openai_api_key: Optional[str] = None
) -> GeneratedAnswer:
    """Convenience function to compose ontology answer."""
    composer = AnswerComposer(openai_api_key=openai_api_key)
    return composer.compose_answer(intent, question, concept_match, relation_result, query_analysis)


def create_answer_response(answer: GeneratedAnswer) -> Dict[str, Any]:
    """Create API response from generated answer."""
    return {
        "answer": answer.answer,
        "intent": answer.intent.value,
        "confidence": round(answer.confidence, 3),
        "method": getattr(answer, 'method', 'unknown'),
        "sources_used": answer.sources_used,
        "structured_data": answer.structured_data
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Compose answers for ontology queries")
    parser.add_argument("question", help="User question")
    parser.add_argument("intent", choices=["definition", "cause", "solution", "comparison", "unknown"],
                       help="Query intent")
    parser.add_argument("--openai-key", help="OpenAI API key for LLM generation")
    parser.add_argument("--template-threshold", type=float, default=0.7,
                       help="Confidence threshold for template use")
    parser.add_argument("--concept-file", help="JSON file with concept match data")
    parser.add_argument("--relations-file", help="JSON file with relation expansion data")

    args = parser.parse_args()

    # Convert intent
    intent_map = {
        "definition": QueryIntent.DEFINITION,
        "cause": QueryIntent.CAUSE,
        "solution": QueryIntent.SOLUTION,
        "comparison": QueryIntent.COMPARISON,
        "unknown": QueryIntent.UNKNOWN
    }
    intent = intent_map[args.intent]

    # Load optional data
    concept_match = None
    relation_result = None

    if args.concept_file:
        with open(args.concept_file, 'r', encoding='utf-8') as f:
            concept_data = json.load(f)
            # This would need proper deserialization in real usage
            concept_match = None  # Placeholder

    if args.relations_file:
        with open(args.relations_file, 'r', encoding='utf-8') as f:
            relations_data = json.load(f)
            # This would need proper deserialization in real usage
            relation_result = None  # Placeholder

    composer = AnswerComposer(
        openai_api_key=args.openai_key,
        template_confidence_threshold=args.template_threshold
    )

    answer = composer.compose_answer(intent, args.question, concept_match, relation_result)

    response = create_answer_response(answer)
    print(json.dumps(response, ensure_ascii=False, indent=2))
