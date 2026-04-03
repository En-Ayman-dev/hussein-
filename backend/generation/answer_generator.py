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

    RELATION_TYPE_LABELS = {
        "belongsToCollection": "يندرج ضمن سلسلة",
        "belongsToGroup": "يندرج تحت",
        "belongsToLesson": "ينتمي إلى درس",
        "causes": "يسبب",
        "establishes": "يرسخ",
        "isCausedBy": "ينتج عن",
        "isConditionFor": "شرط لـ",
        "isMeansFor": "يمهد إلى",
        "negates": "ينفي",
        "opposes": "يعارض",
        "precedes": "يسبق",
        "relatedTo": "يرتبط بـ",
    }

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

    def _related_label(self, relation: ExpandedRelation, concept_uri: str) -> str:
        other_concept = (
            relation.target_concept
            if relation.relation.source_uri == concept_uri
            else relation.source_concept
        )
        return self._concept_label(other_concept)

    def _relation_type_label(self, relation_type: str) -> str:
        return self.RELATION_TYPE_LABELS.get(relation_type, "يرتبط بـ")

    def _section(self, title: str, lines: List[str]) -> List[str]:
        cleaned_lines = [line for line in lines if line and line.strip()]
        if not cleaned_lines:
            return []
        return [f"**{title}**", *cleaned_lines, ""]

    def _labeled_bullets(self, entries: List[tuple[str, str]]) -> List[str]:
        return [f"• **{label}:** {text}" for label, text in entries if label and text]

    def _quote_lines(self, entries: List[tuple[str, str]]) -> List[str]:
        lines: List[str] = []
        for label, text in entries:
            if not label or not text:
                continue
            lines.append(f"> **{label}:** {text}")
            lines.append("")
        if lines and not lines[-1].strip():
            lines.pop()
        return lines

    def _supporting_matches(
        self,
        concept: ConceptMatch,
        supporting_matches: Optional[List[ConceptMatch]],
    ) -> List[ConceptMatch]:
        if not supporting_matches:
            return []

        primary_uri = concept.concept.uri
        unique_matches: List[ConceptMatch] = []
        seen_uris: set[str] = {primary_uri}

        for match in supporting_matches:
            uri = getattr(match.concept, "uri", None)
            if not uri or uri in seen_uris:
                continue
            seen_uris.add(uri)
            unique_matches.append(match)

        return unique_matches

    def _collect_match_field_entries(
        self,
        concept: ConceptMatch,
        supporting_matches: Optional[List[ConceptMatch]],
        field_name: str,
    ) -> List[tuple[str, str]]:
        entries: List[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add_from_match(match: ConceptMatch) -> None:
            label = self._primary_label(match)
            values = self._clean_values(getattr(match.concept, field_name, None))
            for value in values:
                signature = (label, value)
                if signature in seen:
                    continue
                seen.add(signature)
                entries.append(signature)

        add_from_match(concept)
        for match in self._supporting_matches(concept, supporting_matches):
            add_from_match(match)

        return entries

    def _relation_statement(self, relation: ExpandedRelation, concept_uri: str) -> str:
        source_label = self._concept_label(relation.source_concept)
        target_label = self._concept_label(relation.target_concept)
        relation_label = self._relation_type_label(relation.relation.type.value)

        if relation.relation.source_uri == concept_uri:
            return f"• **{source_label}** {relation_label} **{target_label}**."
        if relation.relation.target_uri == concept_uri:
            return f"• **{source_label}** {relation_label} **{target_label}**."
        return f"• **{source_label}** {relation_label} **{target_label}**."

    def _group_relation_lines(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
    ) -> Dict[str, List[str]]:
        grouped = {
            "causes": [],
            "means_for": [],
            "opposes": [],
            "establishes": [],
            "related": [],
            "structural": [],
        }

        for relation in relations:
            statement = self._relation_statement(relation, concept.concept.uri)
            relation_type = relation.relation.type.value

            if relation_type in {"causes", "isCausedBy"}:
                grouped["causes"].append(statement)
            elif relation_type == "isMeansFor":
                grouped["means_for"].append(statement)
            elif relation_type == "opposes":
                grouped["opposes"].append(statement)
            elif relation_type == "establishes":
                grouped["establishes"].append(statement)
            elif relation_type in {"belongsToCollection", "belongsToGroup", "belongsToLesson", "precedes"}:
                grouped["structural"].append(statement)
            else:
                grouped["related"].append(statement)

        return grouped

    def _supporting_summary_lines(self, concept: ConceptMatch, supporting_matches: Optional[List[ConceptMatch]]) -> List[str]:
        lines: List[str] = []

        for match in self._supporting_matches(concept, supporting_matches):
            label = self._primary_label(match)
            definitions = self._clean_values(match.concept.definition)
            actions = self._clean_values(match.concept.actions)
            if definitions:
                lines.append(f"• **{label}:** {definitions[0]}")
            elif actions:
                lines.append(f"• **{label}:** {actions[0]}")
            else:
                lines.append(f"• **{label}**")

        return lines

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
        query: str,
        supporting_matches: Optional[List[ConceptMatch]] = None,
    ) -> str:
        """Generate definition answer template."""
        del query
        parts = []
        primary_label = self._primary_label(concept)
        parts.append(f"**{primary_label}**")
        parts.append("")

        quote_entries = self._collect_match_field_entries(concept, supporting_matches, "quote")
        definition_entries = self._collect_match_field_entries(concept, supporting_matches, "definition")
        action_entries = self._collect_match_field_entries(concept, supporting_matches, "actions")
        importance_entries = self._collect_match_field_entries(concept, supporting_matches, "importance")
        relation_groups = self._group_relation_lines(concept, relations)

        parts.extend(self._section("النصوص المؤسسة", self._quote_lines(quote_entries)))
        parts.extend(self._section("التعريفات المباشرة", self._labeled_bullets(definition_entries)))
        parts.extend(self._section("أهمية المفاهيم في هذا السياق", self._labeled_bullets(importance_entries)))
        parts.extend(self._section("مفاهيم مساندة من نفس السياق", self._supporting_summary_lines(concept, supporting_matches)))
        parts.extend(self._section("علاقات تؤسس المعنى", relation_groups["establishes"]))
        parts.extend(self._section("روابط مرتبطة بالسؤال", relation_groups["related"]))
        parts.extend(self._section("ما يجب الحذر منه", relation_groups["opposes"]))
        parts.extend(self._section("المطلوب عملياً", self._labeled_bullets(action_entries)))
        parts.extend(self._section("وسائل مرتبطة بالمفهوم", relation_groups["means_for"]))

        return "\n".join(parts).strip()

    def _cause_template(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
        query: str,
        supporting_matches: Optional[List[ConceptMatch]] = None,
    ) -> str:
        """Generate cause answer template."""
        del query
        parts = []
        primary_label = self._primary_label(concept)
        parts.append(f"**{primary_label}**")
        parts.append("")
        quote_entries = self._collect_match_field_entries(concept, supporting_matches, "quote")
        definition_entries = self._collect_match_field_entries(concept, supporting_matches, "definition")
        action_entries = self._collect_match_field_entries(concept, supporting_matches, "actions")
        relation_groups = self._group_relation_lines(concept, relations)

        parts.extend(self._section("النصوص المؤسسة", self._quote_lines(quote_entries)))
        parts.extend(self._section("تعريفات مرتبطة بسبب السؤال", self._labeled_bullets(definition_entries)))
        parts.extend(self._section("الأسباب والعوامل المباشرة", relation_groups["causes"]))
        parts.extend(self._section("العلاقات المرتبطة بالسياق", relation_groups["related"]))
        parts.extend(self._section("المشكلة أو الانحراف المقابل", relation_groups["opposes"]))
        parts.extend(self._section("المفاهيم المساندة", self._supporting_summary_lines(concept, supporting_matches)))
        parts.extend(self._section("ما ينبغي فعله", self._labeled_bullets(action_entries)))

        return "\n".join(parts).strip()

    def _solution_template(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
        query: str,
        supporting_matches: Optional[List[ConceptMatch]] = None,
    ) -> str:
        """Generate solution answer template."""
        del query
        parts = []
        primary_label = self._primary_label(concept)
        parts.append(f"**{primary_label}**")
        parts.append("")
        quote_entries = self._collect_match_field_entries(concept, supporting_matches, "quote")
        definition_entries = self._collect_match_field_entries(concept, supporting_matches, "definition")
        action_entries = self._collect_match_field_entries(concept, supporting_matches, "actions")
        relation_groups = self._group_relation_lines(concept, relations)

        parts.extend(self._section("النصوص المؤسسة", self._quote_lines(quote_entries)))
        parts.extend(self._section("ما يوضح المعنى في سياق السؤال", self._labeled_bullets(definition_entries)))
        parts.extend(self._section("الوسائل والعلاقات العملية", relation_groups["means_for"]))
        parts.extend(self._section("المطلوب عملياً", self._labeled_bullets(action_entries)))
        parts.extend(self._section("المفاهيم المساندة", self._supporting_summary_lines(concept, supporting_matches)))
        parts.extend(self._section("علاقات مرتبطة بالموقف", relation_groups["related"] + relation_groups["establishes"]))
        parts.extend(self._section("ما يجب الحذر منه", relation_groups["opposes"]))

        return "\n".join(parts).strip()

    def _comparison_template(
        self,
        concept: ConceptMatch,
        relations: List[ExpandedRelation],
        query: str,
        supporting_matches: Optional[List[ConceptMatch]] = None,
    ) -> str:
        """Generate comparison answer template."""
        del query
        parts = []
        primary_label = self._primary_label(concept)
        parts.append(f"**{primary_label}**")
        parts.append("")
        quote_entries = self._collect_match_field_entries(concept, supporting_matches, "quote")
        definition_entries = self._collect_match_field_entries(concept, supporting_matches, "definition")
        relation_groups = self._group_relation_lines(concept, relations)

        parts.extend(self._section("النصوص المؤسسة", self._quote_lines(quote_entries)))
        parts.extend(self._section("تعريفات مرتبطة بالمقارنة", self._labeled_bullets(definition_entries)))
        parts.extend(self._section("المفاهيم المعارضة أو المقابلة", relation_groups["opposes"]))
        parts.extend(self._section("روابط أخرى في السياق", relation_groups["related"] + relation_groups["establishes"]))
        parts.extend(self._section("المفاهيم المساندة", self._supporting_summary_lines(concept, supporting_matches)))

        return "\n".join(parts).strip()

    def generate_answer(
        self,
        query_analysis: QueryAnalysis,
        concept_match: Optional[ConceptMatch],
        relation_result: Optional[RelationExpansionResult],
        supporting_matches: Optional[List[ConceptMatch]] = None,
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
            answer = template_func(concept_match, relations, query_analysis.query, supporting_matches)

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
    relation_result: Optional[RelationExpansionResult],
    supporting_matches: Optional[List[ConceptMatch]] = None,
) -> GeneratedAnswer:
    """Convenience function to generate ontology answer."""
    generator = AnswerGenerator()
    return generator.generate_answer(query_analysis, concept_match, relation_result, supporting_matches)


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
