import logging
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Concept, ConceptRelation, RelationType
from processing.query_analyzer import QueryIntent

logger = logging.getLogger(__name__)


@dataclass
class ExpandedRelation:
    """Represents an expanded relation with context."""
    relation: ConceptRelation
    source_concept: Concept
    target_concept: Concept
    depth: int
    relevance_score: float


@dataclass
class RelationExpansionResult:
    """Result of relation expansion."""
    concept: Concept
    quote: Optional[List[str]]
    relations: List[ExpandedRelation]
    total_relations_found: int
    max_depth_reached: bool


class RelationExpander:
    """Expands relations for a concept based on query intent."""

    # Intent to relation type mapping
    INTENT_RELATION_MAPPING = {
        QueryIntent.CAUSE: [RelationType.CAUSES, RelationType.IS_CAUSED_BY],
        QueryIntent.SOLUTION: [RelationType.IS_MEANS_FOR],
        QueryIntent.COMPARISON: [RelationType.OPPOSES],
        QueryIntent.DEFINITION: [
            RelationType.ESTABLISHES,
            RelationType.RELATED_TO,
            RelationType.NEGATES,
            RelationType.CAUSES,
            RelationType.IS_MEANS_FOR,
        ],
        QueryIntent.UNKNOWN: list(RelationType),
    }

    def __init__(self, database_url: str, max_relations: int = 8, max_depth: int = 2):
        """Initialize the relation expander.

        Args:
            database_url: PostgreSQL database URL
            max_relations: Maximum number of relations to return
            max_depth: Maximum depth for relation traversal
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.max_relations = max_relations
        self.max_depth = max_depth

    def _get_concept_by_uri(self, db: Session, uri: str) -> Optional[Concept]:
        """Get concept by URI.

        Args:
            db: Database session
            uri: Concept URI

        Returns:
            Concept or None
        """
        stmt = select(Concept).where(Concept.uri == uri)
        return db.execute(stmt).scalar_one_or_none()

    def _get_direct_relations(
        self,
        db: Session,
        concept_uri: str,
        relation_types: List[RelationType],
        direction: str = "both"
    ) -> List[ConceptRelation]:
        """Get direct relations for a concept.

        Args:
            db: Database session
            concept_uri: Concept URI
            relation_types: Types of relations to find
            direction: "outgoing", "incoming", or "both"

        Returns:
            List of relations
        """
        relations = []

        if direction in ["outgoing", "both"]:
            # Outgoing relations (concept is source)
            stmt = select(ConceptRelation).where(
                ConceptRelation.source_uri == concept_uri,
                ConceptRelation.type.in_(relation_types)
            )
            relations.extend(db.execute(stmt).scalars().all())

        if direction in ["incoming", "both"]:
            # Incoming relations (concept is target)
            stmt = select(ConceptRelation).where(
                ConceptRelation.target_uri == concept_uri,
                ConceptRelation.type.in_(relation_types)
            )
            relations.extend(db.execute(stmt).scalars().all())

        return relations

    def _expand_relations_recursive(
        self,
        db: Session,
        concept_uri: str,
        relation_types: List[RelationType],
        current_depth: int = 0,
        visited: Optional[Set[str]] = None,
        max_to_collect: Optional[int] = None
    ) -> List[ExpandedRelation]:
        """Recursively expand relations up to max_depth.

        Args:
            db: Database session
            concept_uri: Starting concept URI
            relation_types: Types of relations to follow
            current_depth: Current traversal depth
            visited: Set of visited concept URIs
            max_to_collect: Maximum relations to collect

        Returns:
            List of expanded relations
        """
        if visited is None:
            visited = set()

        if concept_uri in visited or current_depth >= self.max_depth:
            return []

        visited.add(concept_uri)

        expanded_relations = []
        direct_relations = self._get_direct_relations(db, concept_uri, relation_types)

        for relation in direct_relations:
            if max_to_collect and len(expanded_relations) >= max_to_collect:
                break

            # Get related concepts
            source_concept = self._get_concept_by_uri(db, relation.source_uri)
            target_concept = self._get_concept_by_uri(db, relation.target_uri)

            if not source_concept or not target_concept:
                continue

            # Calculate relevance score (higher for closer relations)
            relevance_score = 1.0 / (current_depth + 1)

            expanded_relations.append(ExpandedRelation(
                relation=relation,
                source_concept=source_concept,
                target_concept=target_concept,
                depth=current_depth,
                relevance_score=relevance_score
            ))

            # Recursively expand from the related concept
            if current_depth < self.max_depth - 1:
                next_concept_uri = (
                    relation.target_uri
                    if relation.source_uri == concept_uri
                    else relation.source_uri
                )

                sub_relations = self._expand_relations_recursive(
                    db, next_concept_uri, relation_types,
                    current_depth + 1, visited.copy(),
                    max_to_collect - len(expanded_relations) if max_to_collect else None
                )
                expanded_relations.extend(sub_relations)

        return expanded_relations

    def _filter_and_rank_relations(
        self,
        relations: List[ExpandedRelation]
    ) -> List[ExpandedRelation]:
        """Filter and rank relations by relevance.

        Args:
            relations: List of expanded relations

        Returns:
            Filtered and ranked relations
        """
        # Remove duplicates based on relation ID
        best_by_id = {}

        for rel in relations:
            existing = best_by_id.get(rel.relation.id)
            if not existing:
                best_by_id[rel.relation.id] = rel
                continue

            if rel.relevance_score > existing.relevance_score:
                best_by_id[rel.relation.id] = rel
            elif rel.relevance_score == existing.relevance_score and rel.depth < existing.depth:
                best_by_id[rel.relation.id] = rel

        unique_relations = list(best_by_id.values())

        # Sort by relevance score (highest first), then by depth (lowest first)
        unique_relations.sort(key=lambda x: (-x.relevance_score, x.depth))

        # Limit to max_relations
        return unique_relations[:self.max_relations]

    def expand_relations(
        self,
        concept: Concept,
        intent: QueryIntent
    ) -> RelationExpansionResult:
        """Expand relations for a concept based on query intent.

        Args:
            concept: Concept to expand relations for
            intent: Query intent

        Returns:
            RelationExpansionResult with quote and relevant relations
        """
        with self.SessionLocal() as db:
            # Get relevant relation types for this intent
            relation_types = self.INTENT_RELATION_MAPPING.get(intent, [])

            if not relation_types:
                # Fallback to all relation types if intent not mapped
                relation_types = list(RelationType)

            # Expand relations recursively
            expanded_relations = self._expand_relations_recursive(
                db, concept.uri, relation_types, max_to_collect=self.max_relations * 2  # Collect more for filtering
            )

            # Filter and rank
            filtered_relations = self._filter_and_rank_relations(expanded_relations)

            # Check if max depth was reached
            max_depth_reached = any(rel.depth >= self.max_depth - 1 for rel in expanded_relations)

            return RelationExpansionResult(
                concept=concept,
                quote=concept.quote,
                relations=filtered_relations,
                total_relations_found=len(expanded_relations),
                max_depth_reached=max_depth_reached
            )

    def expand_relations_by_uri(
        self,
        concept_uri: str,
        intent: QueryIntent
    ) -> Optional[RelationExpansionResult]:
        """Expand relations for a concept URI.

        Args:
            concept_uri: Concept URI
            intent: Query intent

        Returns:
            RelationExpansionResult or None if concept not found
        """
        with self.SessionLocal() as db:
            concept = self._get_concept_by_uri(db, concept_uri)
            if not concept:
                return None

            return self.expand_relations(concept, intent)


# Convenience functions
def expand_concept_relations(
    concept: Concept,
    intent: QueryIntent,
    database_url: str,
    max_relations: int = 8,
    max_depth: int = 2
) -> RelationExpansionResult:
    """Convenience function to expand relations for a concept."""
    expander = RelationExpander(database_url, max_relations, max_depth)
    return expander.expand_relations(concept, intent)


def expand_concept_relations_by_uri(
    concept_uri: str,
    intent: QueryIntent,
    database_url: str,
    max_relations: int = 8,
    max_depth: int = 2
) -> Optional[RelationExpansionResult]:
    """Convenience function to expand relations for a concept URI."""
    expander = RelationExpander(database_url, max_relations, max_depth)
    return expander.expand_relations_by_uri(concept_uri, intent)


def get_relation_summary(result: RelationExpansionResult) -> Dict[str, Any]:
    """Get a summary of relation expansion results."""
    relations_summary = []
    for rel in result.relations:
        relations_summary.append({
            "type": rel.relation.type.value,
            "source_uri": rel.relation.source_uri,
            "source_labels": rel.source_concept.labels,
            "target_uri": rel.relation.target_uri,
            "target_labels": rel.target_concept.labels,
            "depth": rel.depth,
            "relevance_score": round(rel.relevance_score, 3)
        })

    return {
        "concept_uri": result.concept.uri,
        "concept_labels": result.concept.labels,
        "quote": result.quote,
        "relations": relations_summary,
        "total_relations_found": result.total_relations_found,
        "relations_returned": len(result.relations),
        "max_depth_reached": result.max_depth_reached
    }


if __name__ == "__main__":
    import argparse
    import json

    from query_analyzer import QueryIntent

    parser = argparse.ArgumentParser(description="Expand relations for ontology concepts")
    parser.add_argument("concept_uri", help="Concept URI to expand")
    parser.add_argument("intent", choices=["definition", "cause", "solution", "comparison", "unknown"],
                       help="Query intent")
    parser.add_argument("--database-url", required=True, help="PostgreSQL database URL")
    parser.add_argument("--max-relations", type=int, default=8, help="Maximum relations to return")
    parser.add_argument("--max-depth", type=int, default=2, help="Maximum traversal depth")

    args = parser.parse_args()

    # Convert string intent to enum
    intent_map = {
        "definition": QueryIntent.DEFINITION,
        "cause": QueryIntent.CAUSE,
        "solution": QueryIntent.SOLUTION,
        "comparison": QueryIntent.COMPARISON,
        "unknown": QueryIntent.UNKNOWN
    }

    intent = intent_map[args.intent]

    result = expand_concept_relations_by_uri(
        args.concept_uri,
        intent,
        args.database_url,
        args.max_relations,
        args.max_depth
    )

    if result:
        summary = get_relation_summary(result)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": "Concept not found"}, ensure_ascii=False))
