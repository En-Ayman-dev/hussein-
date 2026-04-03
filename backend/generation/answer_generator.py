import logging
import sys
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from processing.query_analyzer import QueryIntent, QueryAnalysis
from processing.concept_matcher import ConceptMatch
from processing.relation_expander import RelationExpansionResult, ExpandedRelation

logger = logging.getLogger(__name__)


@dataclass
class GeneratedAnswer:
    """Generated answer with structure and confidence."""
    answer: str
    intent: QueryIntent
    confidence: float
    sources_used: List[str]
    structured_data: Dict[str, Any]
    token_usage: Optional[Dict[str, int]] = None
    method: str = "template"


class AnswerGenerator:
    """Generates structured answers based on query intent and ontology context."""

    def __init__(self):
        """Initialize the answer generator."""
        self.templates = self._load_templates()

    def _clean_values(self, values: Optional[List[str]]) -> List[str]:
        cleaned: List[str] = []
        seen: set[str] = set()
        for value in values or []:
            normalized = (value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)
        return cleaned

    def _primary_label(self, concept_match: ConceptMatch) -> str:
        labels = self._clean_values(concept_match.concept.labels)
        return labels[0] if labels else concept_match.concept.uri

    def _concept_label(self, concept: Any) -> str:
        labels = self._clean_values(getattr(concept, "labels", None))
        return labels[0] if labels else getattr(concept, "uri", "هذا المفهوم")

    def _query_requests_application(self, query: str) -> bool:
        normalized = (query or "").strip()
        return any(
            token in normalized
            for token in ["كيف", "نتبع", "اتباع", "نطبق", "نعمل", "موقف", "واجب", "حل"]
        )

    def _definition_sentence(self, primary_label: str, definition: str) -> str:
        cleaned = (definition or "").strip()
        if not cleaned:
            return ""
        if cleaned.startswith(primary_label):
            return f"• يجب أن نفهم أن {cleaned}"
        if cleaned.startswith(("هو", "هي")):
            return f"• يجب أن نفهم أن {primary_label} {cleaned}"
        return f"• يجب أن نفهم أن {primary_label} هو {cleaned}"

    def _action_sentence(self, action: str) -> str:
        cleaned = (action or "").strip()
        if not cleaned:
            return ""
        if cleaned.startswith(("يجب", "لا يجوز", "ينبغي", "الواجب", "المطلوب")):
            return f"• {cleaned}"
        return f"• المطلوب عملياً: {cleaned}"

    def _quote_section(self, title: str, quotes: List[str]) -> List[str]:
        cleaned_quotes = self._clean_values(quotes)
        if not cleaned_quotes:
            return []
        return [f"**{title}:**", f'"{cleaned_quotes[0]}"', ""]

    def _related_label(self, relation: ExpandedRelation, concept_uri: str) -> str:
        other_concept = (
            relation.target_concept
            if relation.relation.source_uri == concept_uri
            else relation.source_concept
        )
        return self._concept_label(other_concept)

    def _load_templates(self) -> Dict[QueryIntent, str]:
        """Load answer templates for each intent."""
        return {
            QueryIntent.DEFINITION: self._definition_template,
            QueryIntent.CAUSE: self._cause_template,
            QueryIntent.SOLUTION: self._solution_template,
            QueryIntent.COMPARISON: self._comparison_template,
        }

    def _definition_template(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
        query: str
    ) -> str:
        """Generate definition answer template."""
        parts = []
        primary_label = self._primary_label(concept)
        cleaned_quotes = self._clean_values(concept.concept.quote)
        cleaned_definitions = self._clean_values(concept.concept.definition)
        cleaned_actions = self._clean_values(concept.concept.actions)

        parts.append(f"**{primary_label}**")
        parts.append("")
        parts.extend(self._quote_section("النص التأسيسي", cleaned_quotes))

        if cleaned_definitions:
            parts.append("**التعريف:**")
            parts.append(self._definition_sentence(primary_label, cleaned_definitions[0]))
            parts.append("")

        establishes_relations = []
        related_relations = []
        opposing_relations = []
        means_relations = []
        for rel in relations:
            if rel.depth != 0:
                continue
            rel_type = rel.relation.type.value
            if rel_type == "establishes":
                establishes_relations.append(rel)
            elif rel_type == "opposes":
                opposing_relations.append(rel)
            elif rel_type == "isMeansFor":
                means_relations.append(rel)
            elif rel_type == "relatedTo":
                related_relations.append(rel)

        if establishes_relations or related_relations:
            parts.append("**التحليل:**")
            for rel in (establishes_relations[:2] + related_relations[:2]):
                other_label = self._related_label(rel, concept.concept.uri)
                if other_label:
                    parts.append(f"• أليس هذا دليلاً على أن {primary_label} يرتبط بـ {other_label}؟")
            parts.append("")

        if opposing_relations:
            parts.append("**ما الذي يجب الحذر منه؟**")
            for rel in opposing_relations[:3]:
                opposing_label = self._related_label(rel, concept.concept.uri)
                if opposing_label:
                    parts.append(f"• لا يجوز أن نغفل خطر {opposing_label}.")
            parts.append("")

        if self._query_requests_application(query) and (cleaned_actions or means_relations):
            parts.append("**الموقف العملي:**")
            for action in cleaned_actions[:3]:
                action_line = self._action_sentence(action)
                if action_line:
                    parts.append(action_line)

            for rel in means_relations[:3]:
                if rel.relation.target_uri != concept.concept.uri:
                    continue
                related_label = self._related_label(rel, concept.concept.uri)
                if related_label:
                    parts.append(f"• ومن وسائل الالتزام بهذا المفهوم: {related_label}.")
            parts.append("")

        return "\n".join(parts).strip()

    def _cause_template(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
        query: str
    ) -> str:
        """Generate cause answer template."""
        parts = []
        primary_label = self._primary_label(concept)
        parts.append(f"**{primary_label}**")
        parts.append("")
        parts.extend(self._quote_section("النص التأسيسي", concept.concept.quote or []))

        # Direct causes
        causes_relations = [
            rel for rel in relations
            if (
                (rel.relation.type.value == "causes" and rel.relation.target_uri == concept.concept.uri)
                or (rel.relation.type.value == "isCausedBy" and rel.relation.source_uri == concept.concept.uri)
            )
            and rel.depth == 0
        ]

        if causes_relations:
            parts.append("**الأسباب:**")
            for rel in causes_relations[:5]:  # Limit to 5
                cause_concept = (
                    rel.source_concept
                    if rel.relation.type.value == "causes"
                    else rel.target_concept
                )
                cause_label = self._concept_label(cause_concept)
                if cause_label:
                    parts.append(f"• يجب أن نعي أن من أسباب هذا الأمر: {cause_label}.")
                    if cause_concept.definition and len(cause_concept.definition) > 0:
                        # Add brief definition
                        definition = cause_concept.definition[0][:100]
                        if len(cause_concept.definition[0]) > 100:
                            definition += "..."
                        parts.append(f"• توضيح مختصر: {definition}")
            parts.append("")

        # Contributing factors from deeper relations
        deeper_relations = [rel for rel in relations if rel.depth > 0]
        if deeper_relations:
            parts.append("**العوامل المساهمة:**")
            for rel in deeper_relations[:3]:  # Limit to 3
                related_concept = (
                    rel.target_concept
                    if rel.relation.source_uri == concept.concept.uri
                    else rel.source_concept
                )
                related_label = self._concept_label(related_concept)
                if related_label:
                    parts.append(f"• وهناك عامل مرتبط أيضاً: {related_label}.")
            parts.append("")

        opposing_relations = [
            rel for rel in relations
            if rel.relation.type.value == "opposes" and rel.depth == 0
        ]
        if opposing_relations:
            parts.append("**المشكلة المقابلة:**")
            for rel in opposing_relations[:3]:
                parts.append(f"• يتجلى الانحراف في {self._related_label(rel, concept.concept.uri)}.")
            parts.append("")

        if not parts:
            return f"لم يتم العثور على أسباب محددة لـ {concept.concept.labels[0] if concept.concept.labels else 'هذا المفهوم'} في قاعدة البيانات."

        return "\n".join(parts).strip()

    def _solution_template(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
        query: str
    ) -> str:
        """Generate solution answer template."""
        parts = []
        primary_label = self._primary_label(concept)
        parts.append(f"**{primary_label}**")
        parts.append("")
        parts.extend(self._quote_section("النص التأسيسي", concept.concept.quote or []))

        # Direct solutions through isMeansFor
        solution_relations = [
            rel for rel in relations
            if (
                rel.relation.type.value == "isMeansFor"
                and rel.relation.target_uri == concept.concept.uri
                and rel.depth == 0
            )
        ]

        if solution_relations:
            parts.append("**الحلول والطرق:**")
            for rel in solution_relations[:5]:  # Limit to 5
                solution_concept = (
                    rel.source_concept
                )
                solution_label = self._concept_label(solution_concept)
                if solution_label:
                    parts.append(f"• من الحلول العملية: {solution_label}.")
                    if solution_concept.definition and len(solution_concept.definition) > 0:
                        definition = solution_concept.definition[0][:100]
                        if len(solution_concept.definition[0]) > 100:
                            definition += "..."
                        parts.append(f"• توضيح مختصر: {definition}")
            parts.append("")

        # Actions from the concept
        if concept.concept.actions:
            parts.append("**الإجراءات المقترحة:**")
            for action in concept.concept.actions[:3]:  # Limit to 3
                action_line = self._action_sentence(action)
                if action_line:
                    parts.append(action_line)
            parts.append("")

        # Related solutions from deeper relations
        deeper_relations = [rel for rel in relations if rel.depth > 0]
        if deeper_relations:
            parts.append("**حلول إضافية:**")
            for rel in deeper_relations[:3]:  # Limit to 3
                related_concept = (
                    rel.target_concept
                    if rel.relation.source_uri == concept.concept.uri
                    else rel.source_concept
                )
                if related_concept.labels and related_concept.actions:
                    parts.append(f"• ويمكن الاستفادة أيضاً من {self._concept_label(related_concept)}:")
                    for action in related_concept.actions[:2]:
                        action_line = self._action_sentence(action)
                        if action_line:
                            parts.append(action_line)
            parts.append("")

        if not parts:
            return f"لم يتم العثور على حلول محددة لـ {concept.concept.labels[0] if concept.concept.labels else 'هذا المفهوم'} في قاعدة البيانات."

        return "\n".join(parts).strip()

    def _comparison_template(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
        query: str
    ) -> str:
        """Generate comparison answer template."""
        parts = []
        primary_label = self._primary_label(concept)
        parts.append(f"**{primary_label}**")
        parts.append("")
        parts.extend(self._quote_section("النص التأسيسي", concept.concept.quote or []))

        # Opposing concepts
        oppose_relations = [
            rel for rel in relations
            if rel.relation.type.value == "opposes" and rel.depth == 0
        ]

        if oppose_relations:
            parts.append("**المقارنة والاختلافات:**")
            for rel in oppose_relations[:4]:  # Limit to 4
                opposing_concept = (
                    rel.target_concept
                    if rel.relation.source_uri == concept.concept.uri
                    else rel.source_concept
                )
                if opposing_concept.labels:
                    parts.append(f"**مع {self._concept_label(opposing_concept)}:**")

                    # Compare definitions
                    if concept.concept.definition and opposing_concept.definition:
                        parts.append(f"• يجب أن نفهم {primary_label} بوصفه: {concept.concept.definition[0][:150]}...")
                        parts.append(f"• أما {self._concept_label(opposing_concept)} فيظهر بوصفه: {opposing_concept.definition[0][:150]}...")
                        parts.append("")

                    # Compare key differences
                    if concept.concept.importance and opposing_concept.importance:
                        parts.append("**الاختلافات الرئيسية:**")
                        parts.append(f"• أهمية {primary_label}: {', '.join(concept.concept.importance)}")
                        parts.append(f"• أهمية {self._concept_label(opposing_concept)}: {', '.join(opposing_concept.importance)}")
                        parts.append("")
        else:
            parts.append("**المقارنة:**")
            parts.append(f"لا يظهر في السياق مفهوم معارض مباشر لـ {primary_label}.")
            parts.append("")

        # Alternative perspectives from deeper relations
        deeper_relations = [rel for rel in relations if rel.depth > 0 and rel.relation.type.value == "opposes"]
        if deeper_relations:
            parts.append("**منظورات بديلة:**")
            for rel in deeper_relations[:2]:  # Limit to 2
                related_concept = (
                    rel.target_concept
                    if rel.relation.source_uri == concept.concept.uri
                    else rel.source_concept
                )
                if related_concept.labels:
                    parts.append(f"• {related_concept.labels[0]} (من خلال علاقة غير مباشرة)")
            parts.append("")

        return "\n".join(parts).strip()

    def generate_answer(
        self,
        query_analysis: QueryAnalysis,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult]
    ) -> GeneratedAnswer:
        """Generate a structured answer based on query analysis and context.

        Args:
            query_analysis: Analyzed query with intent
            concept_match: Best matching concept
            relation_result: Expanded relations

        Returns:
            Generated answer
        """
        if not concept_match:
            return GeneratedAnswer(
                answer="لم يتم العثور على مفهوم مطابق في قاعدة البيانات.",
                intent=query_analysis.intent,
                confidence=0.0,
                sources_used=[],
                structured_data={}
            )

        # Get the template function
        template_func = self.templates.get(query_analysis.intent)
        if not template_func:
            # Fallback template
            answer = f"تم العثور على المفهوم: {concept_match.concept.labels[0] if concept_match.concept.labels else concept_match.concept.uri}"
        else:
            relations = relation_result.relations if relation_result else []
            answer = template_func(concept_match, relations, query_analysis.query)

        # Collect sources
        sources_used = []
        if concept_match:
            sources_used.append(f"concept:{concept_match.concept.uri}")
        if relation_result and relation_result.relations:
            sources_used.extend([f"relation:{rel.relation.id}" for rel in relation_result.relations])

        # Structured data for API responses
        structured_data = {
            "concept_uri": concept_match.concept.uri,
            "concept_labels": concept_match.concept.labels,
            "match_confidence": concept_match.confidence,
            "match_type": concept_match.match_type,
            "relations_used": len(relation_result.relations) if relation_result else 0,
        }

        return GeneratedAnswer(
            answer=answer,
            intent=query_analysis.intent,
            confidence=min(query_analysis.confidence, concept_match.confidence),
            sources_used=sources_used,
            structured_data=structured_data
        )


# Convenience functions
def generate_ontology_answer(
    query_analysis: QueryAnalysis,
    concept_match: Optional[ConceptMatch],
    relation_result: Optional[RelationExpansionResult]
) -> GeneratedAnswer:
    """Convenience function to generate ontology answer."""
    generator = AnswerGenerator()
    return generator.generate_answer(query_analysis, concept_match, relation_result)


def create_answer_summary(answer: GeneratedAnswer) -> Dict[str, Any]:
    """Create a summary dict of the generated answer."""
    return {
        "answer": answer.answer,
        "intent": answer.intent.value,
        "confidence": round(answer.confidence, 3),
        "sources_used": answer.sources_used,
        "structured_data": answer.structured_data
    }


if __name__ == "__main__":
    import argparse
    import json

    # This would need actual data to work, so just show usage
    parser = argparse.ArgumentParser(description="Generate ontology answers")
    parser.add_argument("--help", action="store_true", help="Show usage information")

    if len(sys.argv) == 1 or "--help" in sys.argv:
        print("""
Ontology Answer Generator

This module generates structured answers for Arabic ontology queries.

Usage in code:

from answer_generator import generate_ontology_answer
from query_analyzer import analyze_arabic_query
from concept_matcher import find_best_concept
from relation_expander import expand_concept_relations

# Analyze query
analysis = analyze_arabic_query("ما هو تعريف العدالة؟")

# Find concept
concept = find_best_concept(analysis.query, "postgresql://...")

# Expand relations
relations = expand_concept_relations(concept, analysis.intent, "postgresql://...")

# Generate answer
answer = generate_ontology_answer(analysis, concept, relations)
print(answer.answer)
        """)
        sys.exit(0)

    args = parser.parse_args()
