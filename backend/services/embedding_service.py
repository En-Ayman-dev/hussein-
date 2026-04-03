import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Type

from openai import APIError, OpenAI, RateLimitError
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from core.models import Concept, ConceptRelation, ConceptSynonym, Document, EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

RELATION_TYPE_LABELS = {
    "BELONGS_TO_COLLECTION": "يندرج ضمن سلسلة",
    "BELONGS_TO_GROUP": "يندرج تحت",
    "BELONGS_TO_LESSON": "ينتمي إلى درس",
    "CAUSES": "يسبب",
    "ESTABLISHES": "يرسخ",
    "IS_CAUSED_BY": "ينتج عن",
    "IS_CONDITION_FOR": "شرط لـ",
    "IS_MEANS_FOR": "يمهد إلى",
    "NEGATES": "ينفي",
    "OPPOSES": "يعارض",
    "PRECEDES": "يسبق",
    "RELATED_TO": "يرتبط بـ",
}

PREDICATE_LABELS = {
    "hassynonym": "مرادف",
    "altlabel": "تسمية بديلة",
    "hiddenlabel": "تسمية خفية",
    "sameas": "مكافئ",
}


@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""

    model: str = "text-embedding-3-small"
    max_tokens: int = 8000
    batch_size: int = 100
    dimensions: int = EMBEDDING_DIMENSIONS
    max_retries: int = 3
    retry_delay: float = 1.0
    max_retry_delay: float = 60.0


class EmbeddingService:
    """Service for generating and storing OpenAI embeddings."""

    def __init__(
        self,
        openai_api_key: str,
        database_url: str,
        config: Optional[EmbeddingConfig] = None,
    ):
        self.config = config or EmbeddingConfig()
        self.client = OpenAI(api_key=openai_api_key)
        self.engine = create_engine(database_url)

        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def _truncate_text(self, value: str) -> str:
        max_chars = self.config.max_tokens * 4
        return value[:max_chars]

    def _normalize_text_piece(self, value: Any) -> str:
        return str(value or "").strip()

    def _deduplicate_texts(self, values: Sequence[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for value in values:
            normalized = self._normalize_text_piece(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _join_text_parts(self, parts: Sequence[Any]) -> str:
        normalized = self._deduplicate_texts([self._normalize_text_piece(part) for part in parts])
        if not normalized:
            return ""
        return self._truncate_text(" ".join(normalized))

    def _uri_suffix_to_text(self, uri: Optional[str]) -> str:
        if not uri:
            return ""

        suffix = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        suffix = re.sub(r"([a-z])([A-Z])", r"\1 \2", suffix)
        suffix = re.sub(r"[_-]+", " ", suffix)
        return suffix.strip()

    def _first_label(self, labels: Any, fallback_uri: Optional[str] = None) -> str:
        if isinstance(labels, list):
            for label in labels:
                cleaned = self._normalize_text_piece(label)
                if cleaned:
                    return cleaned
        elif labels:
            cleaned = self._normalize_text_piece(labels)
            if cleaned:
                return cleaned

        return self._uri_suffix_to_text(fallback_uri)

    def _humanize_relation_type(self, relation_type: Any) -> str:
        raw_value = getattr(relation_type, "value", relation_type) or ""
        normalized_key = re.sub(
            r"[\s-]+",
            "_",
            re.sub(r"([a-z])([A-Z])", r"\1_\2", str(raw_value).strip()),
        ).upper()
        return RELATION_TYPE_LABELS.get(normalized_key, self._uri_suffix_to_text(str(raw_value)))

    def _humanize_predicate(self, predicate: Optional[str]) -> str:
        fragment = self._uri_suffix_to_text(predicate).replace(" ", "")
        if not fragment:
            return "مرادف"

        mapped = PREDICATE_LABELS.get(fragment.lower())
        if mapped:
            return mapped

        return self._uri_suffix_to_text(predicate)

    def _prepare_concept_text(self, concept_data: Dict[str, Any]) -> str:
        texts: List[str] = []

        for field_name in ("labels", "definition", "quote"):
            field_value = concept_data.get(field_name)
            if not field_value:
                continue
            if isinstance(field_value, list):
                texts.extend(str(item) for item in field_value if item)
            else:
                texts.append(str(field_value))

        return self._join_text_parts(texts)

    def _prepare_synonym_text(self, synonym_data: Dict[str, Any]) -> str:
        concept_label = self._first_label(
            synonym_data.get("concept_labels", []),
            synonym_data.get("subject_uri"),
        )
        predicate_label = self._humanize_predicate(synonym_data.get("predicate"))
        synonym_value = self._normalize_text_piece(synonym_data.get("object_value"))
        return self._join_text_parts([concept_label, predicate_label, synonym_value])

    def _prepare_relation_text(self, relation_data: Dict[str, Any]) -> str:
        source_label = self._first_label(
            relation_data.get("source_labels", []),
            relation_data.get("source_uri"),
        )
        relation_label = self._humanize_relation_type(relation_data.get("type"))
        target_label = self._first_label(
            relation_data.get("target_labels", []),
            relation_data.get("target_uri"),
        )
        return self._join_text_parts([source_label, relation_label, target_label])

    def _chunk_texts(self, texts: List[str]) -> List[List[str]]:
        return [
            texts[index : index + self.config.batch_size]
            for index in range(0, len(texts), self.config.batch_size)
        ]

    def _generate_embeddings_with_retry(self, texts: List[str]) -> List[List[float]]:
        delay = self.config.retry_delay

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.client.embeddings.create(
                    model=self.config.model,
                    input=texts,
                )
                embeddings = [list(item.embedding) for item in response.data]
                for embedding in embeddings:
                    if len(embedding) != self.config.dimensions:
                        raise ValueError(
                            f"Embedding dimension mismatch: expected {self.config.dimensions}, got {len(embedding)}"
                        )
                return embeddings
            except RateLimitError as exc:
                if attempt == self.config.max_retries:
                    raise
                logger.warning("Embedding rate limit, retrying in %.1fs: %s", delay, exc)
                time.sleep(delay)
                delay = min(delay * 2, self.config.max_retry_delay)
            except APIError as exc:
                if attempt == self.config.max_retries:
                    raise
                logger.warning("Embedding API error, retrying in %.1fs: %s", delay, exc)
                time.sleep(delay)
                delay = min(delay * 2, self.config.max_retry_delay)
            except Exception as exc:
                if attempt == self.config.max_retries:
                    raise
                logger.warning("Embedding generation error, retrying in %.1fs: %s", delay, exc)
                time.sleep(delay)
                delay = min(delay * 2, self.config.max_retry_delay)

        raise RuntimeError("Embedding retries exhausted")

    def _generate_text_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        all_embeddings: List[List[float]] = []
        for chunk_index, chunk in enumerate(self._chunk_texts(texts), start=1):
            logger.info(
                "Generating embedding chunk %s containing %s texts",
                chunk_index,
                len(chunk),
            )
            all_embeddings.extend(self._generate_embeddings_with_retry(chunk))
        return all_embeddings

    def generate_concept_embedding(self, concept_data: Dict[str, Any]) -> List[float]:
        prepared_text = self._prepare_concept_text(concept_data)
        if not prepared_text:
            logger.warning("No text available for concept embedding")
            return []

        result = self._generate_embeddings_with_retry([prepared_text])
        return result[0] if result else []

    def generate_embeddings_batch(
        self,
        concept_data_list: List[Dict[str, Any]],
    ) -> List[List[float]]:
        if not concept_data_list:
            return []

        texts = [
            prepared_text
            for prepared_text in (
                self._prepare_concept_text(concept_data) for concept_data in concept_data_list
            )
            if prepared_text
        ]
        return self._generate_text_embeddings_batch(texts)

    def _store_embeddings_batch(
        self,
        model: Type[Any],
        record_ids: List[int],
        embeddings: List[List[float]],
    ) -> int:
        if len(record_ids) != len(embeddings):
            logger.error("Mismatch between record count and embedding count for %s", model.__name__)
            return 0

        if not record_ids:
            return 0

        stored_count = 0
        try:
            with Session(self.engine) as session:
                rows = session.execute(
                    select(model).where(model.id.in_(record_ids))
                ).scalars().all()
                rows_by_id = {row.id: row for row in rows}

                for record_id, embedding in zip(record_ids, embeddings):
                    row = rows_by_id.get(record_id)
                    if not row or not embedding:
                        continue
                    row.embedding = embedding
                    stored_count += 1

                session.commit()
        except SQLAlchemyError as exc:
            logger.error("Failed to store embeddings batch for %s: %s", model.__name__, exc)
            return 0

        return stored_count

    def store_concept_embedding(self, concept_uri: str, embedding: List[float]) -> bool:
        if not embedding:
            return False

        try:
            with Session(self.engine) as session:
                concept = session.execute(
                    select(Concept).where(Concept.uri == concept_uri)
                ).scalar_one_or_none()
                if not concept:
                    return False

                concept.embedding = embedding
                session.commit()
                return True
        except SQLAlchemyError as exc:
            logger.error("Failed to store concept embedding for %s: %s", concept_uri, exc)
            return False

    def store_concept_embeddings_batch(
        self,
        concept_data_list: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> int:
        concept_uris = [concept_data.get("uri") for concept_data in concept_data_list if concept_data.get("uri")]
        if len(concept_uris) != len(embeddings):
            logger.error("Mismatch between concept count and embedding count")
            return 0

        stored_count = 0
        try:
            with Session(self.engine) as session:
                concepts = session.execute(
                    select(Concept).where(Concept.uri.in_(concept_uris))
                ).scalars().all()
                concepts_by_uri = {concept.uri: concept for concept in concepts}

                for concept_uri, embedding in zip(concept_uris, embeddings):
                    concept = concepts_by_uri.get(concept_uri)
                    if not concept or not embedding:
                        continue

                    concept.embedding = embedding
                    stored_count += 1

                session.commit()
        except SQLAlchemyError as exc:
            logger.error("Failed to store concept embeddings batch: %s", exc)
            return 0

        return stored_count

    def _process_payload_embeddings(
        self,
        payloads: List[Dict[str, Any]],
        text_builder: Any,
        model: Type[Any],
        total_key: str,
        batch_size: Optional[int] = None,
    ) -> Dict[str, int]:
        original_batch_size = self.config.batch_size
        if batch_size:
            self.config.batch_size = batch_size

        try:
            valid_payloads: List[Dict[str, Any]] = []
            texts: List[str] = []

            for payload in payloads:
                prepared_text = text_builder(payload)
                if not prepared_text:
                    continue
                valid_payloads.append(payload)
                texts.append(prepared_text)

            embeddings = self._generate_text_embeddings_batch(texts)
            stored_count = self._store_embeddings_batch(
                model,
                [payload["id"] for payload in valid_payloads],
                embeddings,
            )

            return {
                total_key: len(payloads),
                "generated_embeddings": len(embeddings),
                "stored_embeddings": stored_count,
                "skipped_embeddings": len(payloads) - len(valid_payloads),
            }
        finally:
            self.config.batch_size = original_batch_size

    def _load_synonym_payloads(self, synonym_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(ConceptSynonym).options(joinedload(ConceptSynonym.concept))
            if synonym_ids is not None:
                if not synonym_ids:
                    return []
                stmt = stmt.where(ConceptSynonym.id.in_(synonym_ids))

            synonyms = session.execute(stmt).scalars().all()

        return [
            {
                "id": synonym.id,
                "subject_uri": synonym.subject_uri,
                "predicate": synonym.predicate,
                "object_value": synonym.object_value,
                "concept_labels": synonym.concept.labels if synonym.concept else [],
            }
            for synonym in synonyms
        ]

    def _load_relation_payloads(self, relation_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(ConceptRelation).options(
                joinedload(ConceptRelation.source_concept),
                joinedload(ConceptRelation.target_concept),
            )
            if relation_ids is not None:
                if not relation_ids:
                    return []
                stmt = stmt.where(ConceptRelation.id.in_(relation_ids))

            relations = session.execute(stmt).scalars().all()

        return [
            {
                "id": relation.id,
                "type": relation.type,
                "source_uri": relation.source_uri,
                "target_uri": relation.target_uri,
                "source_labels": relation.source_concept.labels if relation.source_concept else [],
                "target_labels": relation.target_concept.labels if relation.target_concept else [],
            }
            for relation in relations
        ]

    def process_concepts_with_embeddings(
        self,
        concept_data_list: List[Dict[str, Any]],
        batch_size: Optional[int] = None,
    ) -> Dict[str, int]:
        original_batch_size = self.config.batch_size
        if batch_size:
            self.config.batch_size = batch_size

        try:
            valid_concepts = [
                concept_data
                for concept_data in concept_data_list
                if self._prepare_concept_text(concept_data)
            ]
            embeddings = self.generate_embeddings_batch(valid_concepts)
            stored_count = self.store_concept_embeddings_batch(valid_concepts, embeddings)
            return {
                "total_concepts": len(concept_data_list),
                "generated_embeddings": len(embeddings),
                "stored_embeddings": stored_count,
                "skipped_embeddings": len(concept_data_list) - len(valid_concepts),
            }
        finally:
            self.config.batch_size = original_batch_size

    def process_synonyms_with_embeddings(
        self,
        synonym_ids: Optional[List[int]] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, int]:
        payloads = self._load_synonym_payloads(synonym_ids)
        return self._process_payload_embeddings(
            payloads,
            self._prepare_synonym_text,
            ConceptSynonym,
            "total_synonyms",
            batch_size=batch_size,
        )

    def process_relations_with_embeddings(
        self,
        relation_ids: Optional[List[int]] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, int]:
        payloads = self._load_relation_payloads(relation_ids)
        return self._process_payload_embeddings(
            payloads,
            self._prepare_relation_text,
            ConceptRelation,
            "total_relations",
            batch_size=batch_size,
        )

    def process_documents_with_embeddings(
        self,
        document_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        if document_ids is not None:
            total_documents = len(document_ids)
        else:
            with Session(self.engine) as session:
                total_documents = session.query(Document).count()

        return {
            "total_documents": total_documents,
            "generated_embeddings": 0,
            "stored_embeddings": 0,
            "skipped_embeddings": total_documents,
            "status": "not_ingested_from_current_ttl",
        }


def create_embedding_service(
    openai_api_key: str,
    database_url: str,
    config: Optional[EmbeddingConfig] = None,
) -> EmbeddingService:
    return EmbeddingService(openai_api_key, database_url, config)


def generate_and_store_concept_embedding(
    concept_data: Dict[str, Any],
    openai_api_key: str,
    database_url: str,
) -> bool:
    service = EmbeddingService(openai_api_key, database_url)
    embedding = service.generate_concept_embedding(concept_data)
    concept_uri = concept_data.get("uri")
    return bool(concept_uri and embedding and service.store_concept_embedding(concept_uri, embedding))
