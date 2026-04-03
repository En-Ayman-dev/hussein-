import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from sqlalchemy import select, text, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from core.models import Concept, ConceptSynonym
from processing.text_normalizer import ArabicNormalizer
from services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class ConceptMatch:
    """Represents a matched concept with confidence score."""
    concept: Concept
    confidence: float
    match_type: str  # "exact_label", "synonym", "full_text", "vector"
    matched_text: str  # The text that matched


@dataclass(frozen=True)
class SearchCandidate:
    """Weighted candidate phrase extracted from the user query."""

    text: str
    priority: float
    words: List[str]


class ConceptMatcher:
    """Matcher for finding concepts using multiple search strategies."""

    def __init__(
        self,
        database_url: str,
        openai_api_key: Optional[str] = None,
        embedding_config: Optional[Any] = None
    ):
        """Initialize the concept matcher.

        Args:
            database_url: PostgreSQL database URL
            openai_api_key: OpenAI API key for embedding generation
            embedding_config: Embedding service configuration
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.text_normalizer = ArabicNormalizer()
        self._token_variant_cache: dict[str, set[str]] = {}
        self._token_signature_cache: dict[str, set[str]] = {}
        self._token_similarity_cache: dict[tuple[str, str], float] = {}
        self._phrase_index_cache: Optional[list[tuple[str, set[str]]]] = None

        # Initialize embedding service if API key provided
        self.embedding_service = None
        if openai_api_key:
            from services.embedding_service import EmbeddingConfig
            config = embedding_config or EmbeddingConfig()
            try:
                self.embedding_service = EmbeddingService(openai_api_key, database_url, config)
            except Exception as exc:
                logger.warning("Embedding service disabled: %s", exc)

    def _normalize_search_term(self, term: str) -> str:
        """Normalize search term for matching."""
        return self.text_normalizer.normalize_text(term)

    def _question_stop_words(self) -> set[str]:
        return {
            "ما",
            "ماذا",
            "هو",
            "هي",
            "في",
            "من",
            "عن",
            "على",
            "الى",
            "إلى",
            "لماذا",
            "كيف",
            "سبب",
            "اسباب",
            "أسباب",
            "هل",
            "ثم",
            "او",
            "أو",
            "و",
            "نحن",
            "انا",
            "أنا",
            "يمكن",
            "نفعل",
            "افعل",
            "أفعل",
            "نعمل",
            "اعمل",
            "أعمل",
            "نطبق",
            "اطبق",
            "أطبق",
        }

    def _strip_question_scaffolding(self, clause: str) -> str:
        cleaned = clause.strip()
        patterns = [
            r"^(?:و\s*)?(?:ماهو|ما هو|ماهي|ما هي|ما معنى|ما المقصود(?:\s+ب| بـ)?|تعريف|شرح|وصف)\s+",
            r"^(?:و\s*)?(?:كيف(?:\s+يمكن)?|كيف(?:\s+نفعل)?|كيف(?:\s+نعمل)?|كيف(?:\s+نتبع(?:ه|ها)?)?)\s+",
            r"^(?:و\s*)?(?:لماذا|لما|ما السبب(?:\s+في)?|ما الاسباب|ما الأسباب)\s+",
            r"^(?:و\s*)?(?:من هو|من هي|هل)\s+",
        ]

        changed = True
        while changed:
            changed = False
            for pattern in patterns:
                updated = re.sub(pattern, "", cleaned).strip()
                if updated != cleaned:
                    cleaned = updated
                    changed = True

        return cleaned

    def _split_query_clauses(self, normalized_query: str) -> List[str]:
        standardized = re.sub(r"[؟?!؛;]+", " ", normalized_query)
        initial_parts = [
            part.strip()
            for part in re.split(r"\s*[،,:]\s*", standardized)
            if part.strip()
        ]

        clauses: List[str] = []
        for part in initial_parts or [standardized]:
            sub_parts = [
                segment.strip()
                for segment in re.split(
                    r"\s+و(?=(?:كيف|ما|ماهو|ماهي|لماذا|لما|هل|ماذا|من|اين|أين|متى)\b)",
                    part,
                )
                if segment.strip()
            ]
            clauses.extend(sub_parts or [part.strip()])

        return [clause for clause in clauses if clause]

    def _build_search_candidates(self, search_term: str) -> List[SearchCandidate]:
        """Build weighted search candidates from a user question."""
        normalized = self._normalize_search_term(search_term)
        stop_words = self._question_stop_words()
        clauses = self._split_query_clauses(normalized)
        seen: set[str] = set()
        candidates: List[SearchCandidate] = []

        def add_candidate(text: str, priority: float) -> None:
            cleaned = re.sub(r"^[،,:؛;؟?!]+|[،,:؛;؟?!]+$", "", (text or "").strip()).strip()
            if not cleaned or cleaned in seen:
                return

            words = [
                word for word in re.findall(r"\w+", cleaned)
                if len(word) > 1 and word not in stop_words
            ]
            if not words and len(cleaned) <= 1:
                return

            seen.add(cleaned)
            candidates.append(
                SearchCandidate(
                    text=cleaned,
                    priority=max(0.35, min(priority, 1.0)),
                    words=words or re.findall(r"\w+", cleaned),
                )
            )

        for index, clause in enumerate(clauses or [normalized]):
            priority = 1.0 - (index * 0.14)
            stripped = self._strip_question_scaffolding(clause)
            compact_words = [
                word for word in re.findall(r"\w+", stripped or clause)
                if len(word) > 1 and word not in stop_words
            ]

            add_candidate(stripped, priority)
            if compact_words:
                compact_phrase = " ".join(compact_words[:5])
                add_candidate(compact_phrase, priority - 0.05)

                if index == 0 and len(compact_words) >= 2:
                    add_candidate(" ".join(compact_words[:2]), priority + 0.02)

                if len(compact_words) == 1:
                    add_candidate(compact_words[0], priority - 0.08)

        add_candidate(self._strip_question_scaffolding(normalized), 0.45)
        add_candidate(normalized, 0.35)

        candidates.sort(key=lambda item: (-item.priority, -len(item.words), -len(item.text)))
        return candidates

    def _phrase_index(self, stop_words: set[str]) -> list[tuple[str, set[str]]]:
        if self._phrase_index_cache is not None:
            return self._phrase_index_cache

        phrases: list[str] = []
        with self.SessionLocal() as db:
            for concept in db.execute(select(Concept).where(Concept.labels.isnot(None))).scalars().all():
                phrases.extend([label for label in (concept.labels or []) if (label or "").strip()])

            phrases.extend(
                synonym.object_value
                for synonym in db.execute(select(ConceptSynonym)).scalars().all()
                if (synonym.object_value or "").strip()
            )

        indexed: list[tuple[str, set[str]]] = []
        seen: set[str] = set()
        for phrase in phrases:
            normalized_phrase = self._normalize_search_term(phrase)
            if not normalized_phrase or normalized_phrase in seen:
                continue

            words = {
                word for word in re.findall(r"\w+", normalized_phrase)
                if len(word) > 1 and word not in stop_words
            }
            if not words or len(words) > 5:
                continue

            seen.add(normalized_phrase)
            indexed.append((phrase, words))

        self._phrase_index_cache = indexed
        return indexed

    def _add_local_phrase_expansions(
        self,
        candidates: List[SearchCandidate],
        add_candidate: Any,
        stop_words: set[str],
    ) -> None:
        phrase_index = self._phrase_index(stop_words)

        for candidate in list(candidates):
            candidate_word_set = set(candidate.words)
            if len(candidate_word_set) < 2:
                continue

            scored_phrases: list[tuple[float, str]] = []
            for phrase, phrase_words in phrase_index:
                overlap = len(candidate_word_set.intersection(phrase_words))
                if overlap == 0:
                    continue

                candidate_ratio = overlap / len(candidate_word_set)
                phrase_ratio = overlap / len(phrase_words)
                if candidate_ratio < 0.5 or phrase_ratio < 0.25:
                    continue

                score = candidate.priority + (candidate_ratio * 0.12) + (phrase_ratio * 0.08)
                scored_phrases.append((score, phrase))

            scored_phrases.sort(key=lambda item: item[0], reverse=True)
            for score, phrase in scored_phrases[:4]:
                add_candidate(phrase, score - 0.22)

    def _with_local_phrase_expansions(self, candidates: List[SearchCandidate]) -> List[SearchCandidate]:
        stop_words = self._question_stop_words()
        seen: set[str] = set()
        expanded: List[SearchCandidate] = []

        def add_candidate(text: str, priority: float) -> None:
            cleaned = re.sub(r"^[،,:؛;؟?!]+|[،,:؛;؟?!]+$", "", (text or "").strip()).strip()
            if not cleaned or cleaned in seen:
                return

            words = [
                word for word in re.findall(r"\w+", cleaned)
                if len(word) > 1 and word not in stop_words
            ]
            if not words and len(cleaned) <= 1:
                return

            seen.add(cleaned)
            expanded.append(
                SearchCandidate(
                    text=cleaned,
                    priority=max(0.35, min(priority, 1.0)),
                    words=words or re.findall(r"\w+", cleaned),
                )
            )

        for candidate in candidates:
            add_candidate(candidate.text, candidate.priority)

        self._add_local_phrase_expansions(expanded, add_candidate, stop_words)
        expanded.sort(key=lambda item: (-item.priority, -len(item.words), -len(item.text)))
        return expanded

    def _build_search_terms(self, search_term: str) -> List[str]:
        """Compatibility helper returning only candidate texts."""
        return [candidate.text for candidate in self._build_search_candidates(search_term)]

    def _score_text_against_candidate(self, text_value: str, candidate: SearchCandidate) -> float:
        normalized_text = self._normalize_search_term(text_value)
        if not normalized_text:
            return 0.0

        candidate_words = set(candidate.words)
        text_words = set(re.findall(r"\w+", normalized_text))
        exact_phrase = normalized_text == candidate.text
        substring = candidate.text in normalized_text or normalized_text in candidate.text
        overlap = len(candidate_words.intersection(text_words))
        fuzzy_overlap = self._fuzzy_overlap_score(candidate_words, text_words)

        if not exact_phrase and not substring and overlap == 0 and fuzzy_overlap == 0.0:
            return 0.0

        if exact_phrase:
            base_score = 1.0
        else:
            weighted_overlap = overlap + (fuzzy_overlap * 0.85)
            coverage = weighted_overlap / len(candidate_words) if candidate_words else 0.0
            density = (overlap + (fuzzy_overlap * 0.7)) / max(len(text_words), len(candidate_words), 1)
            base_score = 0.0
            if substring:
                base_score += 0.68
            base_score += coverage * 0.26
            base_score += density * 0.14
            if overlap >= 2:
                base_score += 0.07
            if fuzzy_overlap > 0.0:
                base_score += min(0.12, fuzzy_overlap * 0.08)
            if candidate_words and coverage == 1.0 and len(candidate_words) >= 2:
                base_score += 0.08

        candidate_word_count = max(len(candidate_words), 1)
        text_word_count = max(len(text_words), 1)
        overflow = text_word_count - candidate_word_count
        if overflow > 0 and normalized_text != candidate.text:
            if candidate_word_count == 1:
                base_score -= min(0.32, overflow * 0.09)
            elif candidate_word_count == 2:
                base_score -= min(0.18, overflow * 0.05)

        return min(base_score, 1.0) * candidate.priority

    def _token_variants(self, token: str) -> set[str]:
        normalized = self._normalize_search_term(token)
        if not normalized:
            return set()
        if normalized in self._token_variant_cache:
            return self._token_variant_cache[normalized]

        variants = {normalized}
        prefixes = ("وال", "بال", "فال", "كال", "لل", "ال")
        suffixes = ("هما", "كما", "كم", "كن", "هم", "هن", "ها", "نا", "ات", "ون", "ين", "ان", "ة", "ه", "ي")

        for prefix in prefixes:
            if normalized.startswith(prefix) and len(normalized) - len(prefix) >= 3:
                variants.add(normalized[len(prefix):])

        current_variants = list(variants)
        for variant in current_variants:
            for suffix in suffixes:
                if variant.endswith(suffix) and len(variant) - len(suffix) >= 3:
                    variants.add(variant[: -len(suffix)])

        current_variants = list(variants)
        for variant in current_variants:
            if variant.startswith("ال"):
                continue
            if variant and variant[0] in "يتنا" and len(variant) > 3 and len(variant[1:]) >= 3:
                variants.add(variant[1:])

        result = {variant for variant in variants if len(variant) >= 3}
        self._token_variant_cache[normalized] = result
        return result

    def _token_similarity(self, candidate_word: str, text_word: str) -> float:
        cache_key = (candidate_word, text_word) if candidate_word <= text_word else (text_word, candidate_word)
        if cache_key in self._token_similarity_cache:
            return self._token_similarity_cache[cache_key]

        if candidate_word == text_word:
            self._token_similarity_cache[cache_key] = 1.0
            return 1.0

        candidate_variants = self._token_variants(candidate_word)
        text_variants = self._token_variants(text_word)
        if not candidate_variants or not text_variants:
            self._token_similarity_cache[cache_key] = 0.0
            return 0.0

        candidate_signatures = self._token_signatures(candidate_word)
        text_signatures = self._token_signatures(text_word)
        if candidate_signatures.intersection(text_signatures):
            self._token_similarity_cache[cache_key] = 0.86
            return 0.86

        for candidate_variant in candidate_variants:
            for text_variant in text_variants:
                if len(candidate_variant) >= 4 and len(text_variant) >= 4:
                    if candidate_variant in text_variant or text_variant in candidate_variant:
                        self._token_similarity_cache[cache_key] = 0.74
                        return 0.74

        self._token_similarity_cache[cache_key] = 0.0
        return 0.0

    def _token_signatures(self, token: str) -> set[str]:
        normalized = self._normalize_search_term(token)
        if not normalized:
            return set()
        if normalized in self._token_signature_cache:
            return self._token_signature_cache[normalized]

        signatures: set[str] = set()
        for variant in self._token_variants(normalized):
            signatures.add(variant)
            skeletal = variant[0] + re.sub(r"[اوي]", "", variant[1:])
            if len(skeletal) >= 3:
                signatures.add(skeletal)

        self._token_signature_cache[normalized] = signatures
        return signatures

    def _fuzzy_overlap_score(self, candidate_words: set[str], text_words: set[str]) -> float:
        if not candidate_words or not text_words:
            return 0.0

        remaining_text_words = set(text_words)
        score = 0.0

        for candidate_word in candidate_words:
            if candidate_word in text_words:
                continue

            if len(candidate_word) < 4:
                continue

            best_text_word = None
            best_similarity = 0.0

            for text_word in remaining_text_words:
                if len(text_word) < 4:
                    continue
                similarity = self._token_similarity(candidate_word, text_word)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_text_word = text_word

            if best_text_word and best_similarity >= 0.82:
                score += best_similarity
                remaining_text_words.discard(best_text_word)

        return score

    def _exact_label_match(self, db: Session, search_candidates: List[SearchCandidate]) -> List[ConceptMatch]:
        """Search for exact label matches.

        Args:
            db: Database session
            search_candidates: Ranked search candidates

        Returns:
            List of concept matches
        """
        matches = []
        seen_uris = set()
        concepts = db.execute(select(Concept).where(Concept.labels.isnot(None))).scalars().all()

        for concept in concepts:
            best_match: Optional[ConceptMatch] = None

            for label in concept.labels or []:
                normalized_label = self._normalize_search_term(label or "")
                if not normalized_label:
                    continue

                for search_candidate in search_candidates:
                    if len(search_candidate.words) < 2 and normalized_label != search_candidate.text:
                        continue

                    match_confidence = self._score_text_against_candidate(label, search_candidate)
                    if match_confidence < 0.58:
                        continue

                    candidate_match = ConceptMatch(
                        concept=concept,
                        confidence=match_confidence,
                        match_type="exact_label",
                        matched_text=label,
                    )
                    if not best_match or candidate_match.confidence > best_match.confidence:
                        best_match = candidate_match

            if best_match and concept.uri not in seen_uris:
                seen_uris.add(concept.uri)
                matches.append(best_match)

        return matches

    def _synonym_match(self, db: Session, search_candidates: List[SearchCandidate]) -> List[ConceptMatch]:
        """Search for synonym matches.

        Args:
            db: Database session
            search_candidates: Ranked search candidates

        Returns:
            List of concept matches
        """
        matches = []
        seen_uris = set()
        synonyms = db.execute(select(ConceptSynonym)).scalars().all()

        for synonym in synonyms:
            normalized_synonym = self._normalize_search_term(synonym.object_value or "")
            if not normalized_synonym:
                continue

            best_confidence = 0.0

            for search_candidate in search_candidates:
                best_confidence = max(
                    best_confidence,
                    self._score_text_against_candidate(synonym.object_value, search_candidate) * 0.92,
                )

            if best_confidence < 0.5:
                continue

            if synonym.concept_id:
                concept = db.get(Concept, synonym.concept_id)
            else:
                stmt = select(Concept).where(Concept.uri == synonym.subject_uri)
                concept = db.execute(stmt).scalar_one_or_none()

            if not concept or concept.uri in seen_uris:
                continue

            seen_uris.add(concept.uri)
            matches.append(ConceptMatch(
                concept=concept,
                confidence=best_confidence,
                match_type="synonym",
                matched_text=synonym.object_value
            ))

        return matches

    def _full_text_search(self, db: Session, search_candidates: List[SearchCandidate]) -> List[ConceptMatch]:
        """Search concepts lexically across labels, definitions, quotes, and actions.

        Args:
            db: Database session
            search_candidates: Ranked search candidates

        Returns:
            List of concept matches
        """
        matches = []
        concepts = db.execute(select(Concept)).scalars().all()
        field_weights = {
            "labels": 1.0,
            "definition": 0.82,
            "quote": 0.78,
            "actions": 0.76,
        }
        match_types = {
            "labels": "lexical_label",
            "definition": "lexical_definition",
            "quote": "lexical_quote",
            "actions": "lexical_action",
        }

        for concept in concepts:
            best_match: Optional[ConceptMatch] = None

            for field_name, field_weight in field_weights.items():
                values = getattr(concept, field_name, None) or []
                for value in values:
                    normalized_value = self._normalize_search_term(value or "")
                    if not normalized_value:
                        continue

                    for search_candidate in search_candidates:
                        match_score = self._score_text_against_candidate(value, search_candidate)
                        if match_score == 0.0:
                            continue

                        weighted_score = match_score * field_weight
                        threshold = 0.54 if field_name == "labels" else 0.46
                        if weighted_score < threshold:
                            continue

                        candidate_match = ConceptMatch(
                            concept=concept,
                            confidence=weighted_score,
                            match_type=match_types[field_name],
                            matched_text=value,
                        )
                        if not best_match or candidate_match.confidence > best_match.confidence:
                            best_match = candidate_match

            if best_match:
                matches.append(best_match)

        return matches

    def _vector_similarity_search(
        self,
        db: Session,
        search_term: str,
        limit: int = 10
    ) -> List[ConceptMatch]:
        """Search using vector similarity.

        Args:
            db: Database session
            search_term: Search term for embedding
            limit: Maximum number of results

        Returns:
            List of concept matches
        """
        if not self.embedding_service:
            logger.warning("No embedding service available for vector search")
            return []

        matches = []

        try:
            # Generate embedding for search term
            query_data = {
                "labels": [search_term],
                "definition": [],
                "quote": []
            }
            query_embedding = self.embedding_service.generate_concept_embedding(query_data)

            if not query_embedding:
                logger.warning("Failed to generate query embedding")
                return []

            # Find similar concepts using cosine distance
            stmt = select(
                Concept,
                (1 - Concept.embedding.cosine_distance(query_embedding)).label('similarity')
            ).where(
                Concept.embedding.isnot(None)
            ).order_by(
                Concept.embedding.cosine_distance(query_embedding)
            ).limit(limit)

            results = db.execute(stmt).all()

            for concept, similarity in results:
                # Convert similarity to confidence (cosine similarity is -1 to 1, we want 0 to 1)
                confidence = max(0, (similarity + 1) / 2) * 0.4  # Vector gets up to 0.4 confidence

                matches.append(ConceptMatch(
                    concept=concept,
                    confidence=confidence,
                    match_type="vector",
                    matched_text=search_term
                ))

        except Exception as e:
            logger.error(f"Vector similarity search failed: {e}")

        return matches

    def _combine_and_rank_matches(self, all_matches: List[ConceptMatch]) -> List[ConceptMatch]:
        """Combine matches from different sources and rank by comprehensive scoring.

        Ranking factors:
        - Match type priority (exact > synonym > full_text > vector)
        - Importance boost for concepts with importance="main"
        - Embedding similarity for vector matches

        Args:
            all_matches: List of all matches

        Returns:
            Ranked matches (returns all for flexibility, but typically use top 1)
        """
        # Remove duplicates based on concept URI, keeping the highest scoring match
        uri_to_best_match = {}

        for match in all_matches:
            uri = match.concept.uri

            # Calculate comprehensive score
            base_score = self._calculate_match_score(match)

            # Apply importance boost
            importance_boost = self._calculate_importance_boost(match.concept)
            specificity_boost = min(len((match.matched_text or "").split()), 5) * 0.02
            label_quality_boost = 0.08 if any((label or "").strip() for label in match.concept.labels or []) else -0.25
            context_richness_boost = 0.05 if (match.concept.definition or match.concept.quote) else 0.0
            final_score = base_score + importance_boost + specificity_boost + label_quality_boost + context_richness_boost

            # Update if this is better than existing match for this URI
            if uri not in uri_to_best_match or final_score > uri_to_best_match[uri].confidence:
                match.confidence = final_score
                uri_to_best_match[uri] = match

        # Convert to list and sort by final score
        ranked_matches = list(uri_to_best_match.values())
        ranked_matches.sort(key=lambda x: x.confidence, reverse=True)

        return ranked_matches

    def _calculate_match_score(self, match: ConceptMatch) -> float:
        """Calculate base score based on match type.

        Args:
            match: Concept match

        Returns:
            Base score (0-1)
        """
        base_scores = {
            "exact_label": 1.0,      # Highest priority
            "synonym": 0.8,          # High priority
            "lexical_label": 0.72,
            "lexical_definition": 0.62,
            "lexical_quote": 0.58,
            "lexical_action": 0.6,
            "full_text": 0.6,        # Medium priority
            "full_text_fallback": 0.5,
            "vector": 0.4            # Lower priority, will be boosted by similarity
        }

        base_score = base_scores.get(match.match_type, 0.3)

        if match.match_type == "vector":
            return match.confidence

        return max(base_score * 0.5, match.confidence)

    def _calculate_importance_boost(self, concept: Concept) -> float:
        """Calculate importance boost for a concept.

        Args:
            concept: Concept to check

        Returns:
            Boost value (0-0.3)
        """
        if not concept.importance:
            return 0.0

        # Check if "main" is in importance list
        importance_values = [imp.lower() for imp in concept.importance]
        if "main" in importance_values or "رئيسي" in importance_values:
            return 0.3  # Significant boost for main concepts

        # Smaller boost for other importance indicators
        if concept.importance:
            return 0.1

        return 0.0

    def find_best_concept(self, search_term: str, use_vector: bool = True) -> Optional[ConceptMatch]:
        """Find the best matching concept for a search term.

        Args:
            search_term: Search term
            use_vector: Whether to include vector similarity search

        Returns:
            Best concept match or None if no matches found
        """
        matches = self.find_concepts(search_term, use_vector)
        return matches[0] if matches else None

    def find_top_concepts(
        self,
        search_term: str,
        use_vector: bool = True,
        max_concepts: int = 3,
    ) -> List[ConceptMatch]:
        """Return the top N ranked concept matches."""
        return self.find_concepts(search_term, use_vector)[:max_concepts]

    def find_concepts(self, search_term: str, use_vector: bool = True) -> List[ConceptMatch]:
        """Find concepts matching the search term using multiple strategies.

        Args:
            search_term: Search term
            use_vector: Whether to include vector similarity search

        Returns:
            List of top concept matches with confidence scores
        """
        if not search_term or not search_term.strip():
            return []

        with self.SessionLocal() as db:
            def run_search(
                search_candidates: List[SearchCandidate],
                include_full_text: bool = True,
            ) -> List[ConceptMatch]:
                all_matches: List[ConceptMatch] = []

                exact_matches = self._exact_label_match(db, search_candidates)
                all_matches.extend(exact_matches)

                synonym_matches = self._synonym_match(db, search_candidates)
                all_matches.extend(synonym_matches)

                if include_full_text:
                    fts_matches = self._full_text_search(db, search_candidates)
                    all_matches.extend(fts_matches)

                if use_vector:
                    vector_matches = self._vector_similarity_search(db, search_term)
                    all_matches.extend(vector_matches)

                return self._combine_and_rank_matches(all_matches)

            search_candidates = self._build_search_candidates(search_term)
            ranked_matches = run_search(search_candidates)

            should_try_phrase_expansion = (
                not ranked_matches
                or ranked_matches[0].confidence < 1.0
            )
            if should_try_phrase_expansion:
                expanded_candidates = self._with_local_phrase_expansions(search_candidates)
                if [candidate.text for candidate in expanded_candidates] != [candidate.text for candidate in search_candidates]:
                    expanded_matches = run_search(expanded_candidates, include_full_text=False)
                    if not expanded_matches:
                        expanded_matches = run_search(expanded_candidates, include_full_text=True)
                    if expanded_matches and (
                        not ranked_matches
                        or expanded_matches[0].confidence > ranked_matches[0].confidence
                    ):
                        ranked_matches = expanded_matches

            logger.info(f"Found {len(ranked_matches)} concept matches for '{search_term}'")
            return ranked_matches


# Convenience functions
def find_concept_matches(
    search_term: str,
    database_url: str,
    openai_api_key: Optional[str] = None,
    use_vector: bool = True
) -> List[ConceptMatch]:
    """Convenience function to find concept matches."""
    matcher = ConceptMatcher(database_url, openai_api_key)
    return matcher.find_concepts(search_term, use_vector)


def find_best_concept(
    search_term: str,
    database_url: str,
    openai_api_key: Optional[str] = None,
    use_vector: bool = True
) -> Optional[ConceptMatch]:
    """Convenience function to find the best concept match."""
    matcher = ConceptMatcher(database_url, openai_api_key)
    return matcher.find_best_concept(search_term, use_vector)


def search_concepts(
    query: str,
    database_url: str,
    openai_api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search concepts and return simplified results."""
    matches = find_concept_matches(query, database_url, openai_api_key)

    results = []
    for match in matches:
        results.append({
            "uri": match.concept.uri,
            "labels": match.concept.labels,
            "definition": match.concept.definition,
            "confidence": match.confidence,
            "match_type": match.match_type,
            "matched_text": match.matched_text
        })

    return results


def get_best_concept(
    query: str,
    database_url: str,
    openai_api_key: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get the best matching concept as a simplified dict."""
    match = find_best_concept(query, database_url, openai_api_key)

    if not match:
        return None

    return {
        "uri": match.concept.uri,
        "labels": match.concept.labels,
        "definition": match.concept.definition,
        "quote": match.concept.quote,
        "actions": match.concept.actions,
        "importance": match.concept.importance,
        "confidence": match.confidence,
        "match_type": match.match_type,
        "matched_text": match.matched_text
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Search for concepts in ontology database")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--database-url", required=True, help="PostgreSQL database URL")
    parser.add_argument("--openai-key", help="OpenAI API key for vector search")
    parser.add_argument("--no-vector", action="store_true", help="Disable vector similarity search")
    parser.add_argument("--best-only", action="store_true", help="Return only the best matching concept")

    args = parser.parse_args()

    use_vector = not args.no_vector and bool(args.openai_key)

    if args.best_only:
        # Get best concept
        match = find_best_concept(
            args.query,
            args.database_url,
            args.openai_key,
            use_vector
        )

        if match:
            result = {
                "uri": match.concept.uri,
                "labels": match.concept.labels,
                "definition": match.concept.definition,
                "quote": match.concept.quote,
                "actions": match.concept.actions,
                "importance": match.concept.importance,
                "confidence": round(match.confidence, 3),
                "match_type": match.match_type,
                "matched_text": match.matched_text
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"error": "No matching concept found"}, ensure_ascii=False))
    else:
        # Get all ranked matches
        matches = find_concept_matches(
            args.query,
            args.database_url,
            args.openai_key,
            use_vector
        )

        results = []
        for match in matches:
            results.append({
                "uri": match.concept.uri,
                "labels": match.concept.labels,
                "confidence": round(match.confidence, 3),
                "match_type": match.match_type,
                "matched_text": match.matched_text
            })

        print(json.dumps(results, ensure_ascii=False, indent=2))
