import hashlib
import json
import logging
import os
import re
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import redis
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core.models import (
    Base,
    Concept,
    ConceptRelation,
    ConceptSynonym,
    Document,
    EMBEDDING_DIMENSIONS,
    RelationType,
)
from generation.answer_composer import AnswerComposer
from generation.answer_validator import AnswerValidator, validate_and_regenerate_answer
from app.security import (
    RateLimitExceeded,
    RateLimitRule,
    RequestSecurityManager,
    SanitizationError,
    decode_utf8_payload,
    sanitize_question,
)
from processing.concept_matcher import ConceptMatcher
from processing.query_analyzer import QueryAnalyzer
from processing.relation_expander import RelationExpander
from processing.ttl_parser import parse_ttl
from services.embedding_service import EmbeddingConfig, EmbeddingService

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/ontology_db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL_SECONDS = 3600
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
MAX_QUESTION_LENGTH = 500
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
EMBEDDING_TABLES = (
    ("concepts", "embedding"),
    ("concept_synonyms", "embedding"),
    ("concept_relations", "embedding"),
    ("documents", "embedding"),
)
RATE_LIMIT_RULES = {
    "chat_query": RateLimitRule(limit=30, window_seconds=60, label="المحادثة"),
    "chat_query_without_ai": RateLimitRule(limit=30, window_seconds=60, label="المحادثة بدون AI"),
    "ontology_upload": RateLimitRule(limit=3, window_seconds=600, label="رفع ملفات الأنطولوجيا"),
    "ontology_reindex": RateLimitRule(limit=2, window_seconds=1800, label="إعادة الفهرسة"),
    "stats": RateLimitRule(limit=60, window_seconds=60, label="الإحصائيات"),
    "database_audit": RateLimitRule(limit=60, window_seconds=60, label="فحص قاعدة البيانات"),
}

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
database_schema_warnings: list[str] = []


def _create_redis_client() -> Optional[redis.Redis]:
    try:
        client = redis.from_url(REDIS_URL)
        client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis cache disabled: %s", exc)
        return None


redis_client = _create_redis_client()
request_security = RequestSecurityManager(redis_client=redis_client)
query_analyzer = QueryAnalyzer(openai_api_key=OPENAI_API_KEY)
query_analyzer_without_ai = QueryAnalyzer(openai_api_key=None)
concept_matcher = ConceptMatcher(DATABASE_URL, OPENAI_API_KEY)
concept_matcher_without_ai = ConceptMatcher(DATABASE_URL, openai_api_key=None)
answer_composer = AnswerComposer(openai_api_key=OPENAI_API_KEY)
answer_composer_without_ai = AnswerComposer(openai_api_key=None)
answer_validator = AnswerValidator()
embedding_service = None

if OPENAI_API_KEY:
    try:
        embedding_service = EmbeddingService(
            OPENAI_API_KEY,
            DATABASE_URL,
            EmbeddingConfig(batch_size=50),
        )
    except Exception as exc:
        logger.warning("Embedding service disabled at startup: %s", exc)


class QueryRequest(BaseModel):
    """Incoming request for the chat query endpoint."""

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    use_embeddings: bool = False
    max_relations: int = Field(default=8, ge=1, le=25)
    max_depth: int = Field(default=2, ge=1, le=5)


class QueryResponse(BaseModel):
    """Normalized API response for the chat endpoint."""

    answer: str
    confidence: float
    intent: str
    mode: str
    sources: list[str] = Field(default_factory=list)
    token_usage: Optional[Dict[str, Any]] = None
    processing_time: float
    validation_score: float
    method: str
    matched_concept: Optional[str] = None
    top_concepts: list[Dict[str, Any]] = Field(default_factory=list)
    top_quotes: list[str] = Field(default_factory=list)
    quote: Optional[str] = None
    relations: list[str] = Field(default_factory=list)
    relation_details: list[Dict[str, Any]] = Field(default_factory=list)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_cache_key(request: QueryRequest, mode: str) -> str:
    cache_data = {
        "question": request.question.strip().lower(),
        "use_embeddings": request.use_embeddings,
        "max_relations": request.max_relations,
        "max_depth": request.max_depth,
        "mode": mode,
    }
    cache_string = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(cache_string.encode("utf-8")).hexdigest()
    return f"ontology_query:{digest}"


def get_cached_response(cache_key: str) -> Optional[Dict[str, Any]]:
    if not redis_client:
        return None

    try:
        cached_data = redis_client.get(cache_key)
        return json.loads(cached_data) if cached_data else None
    except Exception as exc:
        logger.warning("Failed to read cached response: %s", exc)
        return None


def cache_response(cache_key: str, response_data: Dict[str, Any]) -> None:
    if not redis_client:
        return

    try:
        redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(response_data, ensure_ascii=False))
    except Exception as exc:
        logger.warning("Failed to cache response: %s", exc)


def clear_query_cache() -> None:
    if not redis_client:
        return

    try:
        keys = redis_client.keys("ontology_query:*")
        if keys:
            redis_client.delete(*keys)
    except Exception as exc:
        logger.warning("Failed to clear query cache: %s", exc)


def _truncate_text(text_value: str, max_length: int = 250) -> str:
    cleaned = (text_value or "").strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rstrip() + "..."


def _deduplicate_strings(strings: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for string_value in strings:
        normalized = (string_value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_relation_key(raw_value: str) -> str:
    return re.sub(r"[\s-]+", "_", re.sub(r"([a-z])([A-Z])", r"\1_\2", raw_value.strip())).upper()


def _humanize_relation_type(raw_value: str) -> str:
    return RELATION_TYPE_LABELS.get(_normalize_relation_key(raw_value), "يرتبط بـ")


def _clean_display_value(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip().strip('"')
    if not cleaned:
        return None

    if cleaned.startswith(("http://", "https://")) or "#" in cleaned:
        return None

    if re.match(r"^(?:[A-Z]\d+[_-][A-Z0-9_-]+|F\d+[_-][A-Z0-9_-]+)$", cleaned, re.IGNORECASE):
        return None

    return cleaned


def _concept_display_label(concept: Any) -> Optional[str]:
    labels = getattr(concept, "labels", None) or []
    for label in labels:
        cleaned = _clean_display_value(label)
        if cleaned:
            return cleaned
    return None


def _clean_text_list(values: Any) -> list[str]:
    if not values:
        return []

    if not isinstance(values, list):
        values = [values]

    cleaned_values: list[str] = []
    seen: set[str] = set()

    for item in values:
        cleaned = (item or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        cleaned_values.append(cleaned)

    return cleaned_values


def _prepare_top_quotes(concept_match: Any, relation_result: Any) -> list[str]:
    quotes: list[str] = []

    if concept_match and concept_match.concept:
        concept_quotes = getattr(concept_match.concept, "quote", []) or []
        quotes.extend(concept_quotes if isinstance(concept_quotes, list) else [concept_quotes])

    if relation_result and getattr(relation_result, "relations", None):
        for relation in relation_result.relations:
            source_quotes = getattr(relation.source_concept, "quote", []) or []
            target_quotes = getattr(relation.target_concept, "quote", []) or []
            quotes.extend(source_quotes if isinstance(source_quotes, list) else [source_quotes])
            quotes.extend(target_quotes if isinstance(target_quotes, list) else [target_quotes])

    return [_truncate_text(item) for item in _deduplicate_strings(quotes)[:4]]


def _prepare_relation_details(relation_result: Any) -> list[Dict[str, Any]]:
    details: list[Dict[str, Any]] = []
    seen: set[tuple[str, Optional[str], Optional[str]]] = set()

    if not relation_result:
        return details

    for relation in relation_result.relations:
        relation_type = relation.relation.type.value
        relation_label = _humanize_relation_type(relation_type)
        source_label = _concept_display_label(relation.source_concept)
        target_label = _concept_display_label(relation.target_concept)
        signature = (relation_type, source_label, target_label)

        if signature in seen or (not source_label and not target_label):
            continue

        seen.add(signature)

        if source_label and target_label:
            summary = f"{source_label} {relation_label} {target_label}"
        elif target_label:
            summary = f"{relation_label} {target_label}"
        else:
            summary = f"{source_label} {relation_label}"

        details.append(
            {
                "type": relation_type,
                "type_label": relation_label,
                "source_label": source_label,
                "target_label": target_label,
                "summary": summary,
            }
        )

    return details


def _prepare_relation_summaries(relation_result: Any) -> list[str]:
    return [detail["summary"] for detail in _prepare_relation_details(relation_result)]


def _build_no_match_response(intent: str, start_time: float, mode: str) -> Dict[str, Any]:
    return {
        "answer": "عذراً، لم أتمكن من العثور على مفهوم مطابق لسؤالك في قاعدة البيانات.",
        "confidence": 0.0,
        "intent": intent,
        "mode": mode,
        "sources": [],
        "token_usage": None,
        "processing_time": round(time.time() - start_time, 2),
        "validation_score": 0.0,
        "method": "no_match",
        "matched_concept": None,
        "top_concepts": [],
        "top_quotes": [],
        "quote": None,
        "relations": [],
        "relation_details": [],
    }


def validate_ttl_file(file: UploadFile) -> None:
    if not file.filename or not file.filename.lower().endswith(".ttl"):
        raise HTTPException(status_code=400, detail="File must have a .ttl extension")

    if file.content_type and not file.content_type.startswith("text/"):
        raise HTTPException(status_code=400, detail="File must be a text file")

    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    if size == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    if size > MAX_UPLOAD_SIZE_BYTES:
        max_size_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {max_size_mb}MB")


def upsert_concept(db: Session, concept_data: Dict[str, Any]) -> tuple[Concept, bool]:
    concept = db.execute(
        select(Concept).where(Concept.uri == concept_data["uri"])
    ).scalar_one_or_none()

    created = concept is None
    if not concept:
        concept = Concept(uri=concept_data["uri"])
        db.add(concept)

    concept.labels = concept_data.get("labels", [])
    concept.definition = concept_data.get("definition", [])
    concept.quote = concept_data.get("quote", [])
    concept.actions = concept_data.get("actions", [])
    concept.importance = concept_data.get("importance", [])

    return concept, created


def upsert_synonym(
    db: Session,
    synonym_data: Dict[str, Any],
    concept_id_by_uri: Dict[str, int],
) -> tuple[ConceptSynonym, bool]:
    synonym = db.execute(
        select(ConceptSynonym).where(
            ConceptSynonym.subject_uri == synonym_data["subject"],
            ConceptSynonym.predicate == synonym_data["predicate"],
            ConceptSynonym.object_value == synonym_data["object"],
        )
    ).scalar_one_or_none()

    created = synonym is None
    if not synonym:
        synonym = ConceptSynonym(
            subject_uri=synonym_data["subject"],
            predicate=synonym_data["predicate"],
            object_value=synonym_data["object"],
        )
        db.add(synonym)

    synonym.concept_id = concept_id_by_uri.get(synonym.subject_uri)
    return synonym, created


def upsert_relation(
    db: Session,
    relation_data: Dict[str, Any],
    concept_id_by_uri: Dict[str, int],
) -> tuple[Optional[ConceptRelation], bool]:
    try:
        relation_type = RelationType(relation_data["type"])
    except ValueError:
        logger.warning("Skipping unsupported relation type: %s", relation_data["type"])
        return None, False

    relation = db.execute(
        select(ConceptRelation).where(
            ConceptRelation.type == relation_type,
            ConceptRelation.source_uri == relation_data["source"],
            ConceptRelation.target_uri == relation_data["target"],
        )
    ).scalar_one_or_none()

    created = relation is None
    if not relation:
        relation = ConceptRelation(
            type=relation_type,
            source_uri=relation_data["source"],
            target_uri=relation_data["target"],
        )
        db.add(relation)

    relation.source_concept_id = concept_id_by_uri.get(relation.source_uri)
    relation.target_concept_id = concept_id_by_uri.get(relation.target_uri)
    return relation, created


def _safe_database_fingerprint() -> Dict[str, Any]:
    database_url = make_url(DATABASE_URL)
    return {
        "driver": database_url.drivername,
        "host": database_url.host,
        "port": database_url.port,
        "database": database_url.database,
    }


def _get_vector_column_type(table_name: str, column_name: str) -> Optional[str]:
    with engine.connect() as connection:
        return connection.execute(
            text(
                """
                SELECT format_type(attribute.atttypid, attribute.atttypmod) AS column_type
                FROM pg_attribute AS attribute
                JOIN pg_class AS class ON attribute.attrelid = class.oid
                JOIN pg_namespace AS namespace ON class.relnamespace = namespace.oid
                WHERE class.relname = :table_name
                  AND attribute.attname = :column_name
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND namespace.nspname = ANY(current_schemas(false))
                LIMIT 1
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar_one_or_none()


def _refresh_schema_warnings() -> None:
    database_schema_warnings.clear()
    expected_type = f"vector({EMBEDDING_DIMENSIONS})"

    for table_name, column_name in EMBEDDING_TABLES:
        try:
            current_type = _get_vector_column_type(table_name, column_name)
            if current_type != expected_type:
                database_schema_warnings.append(
                    f"Column {table_name}.{column_name} is {current_type or 'missing'}, expected {expected_type}"
                )
        except Exception as exc:
            database_schema_warnings.append(
                f"Could not inspect {table_name}.{column_name}: {exc}"
            )


def _ensure_database_ready() -> None:
    with engine.connect() as connection:
        try:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            connection.commit()
        except Exception as exc:
            logger.warning("Could not enable pgvector extension: %s", exc)

    Base.metadata.create_all(bind=engine)

    with engine.connect() as connection:
        for relation_type in RelationType:
            try:
                connection.execute(
                    text(f"ALTER TYPE relationtype ADD VALUE IF NOT EXISTS '{relation_type.name}'")
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                logger.warning("Could not synchronize relation enum value %s: %s", relation_type.name, exc)

    _refresh_schema_warnings()
    for warning in database_schema_warnings:
        logger.warning("Database schema warning: %s", warning)


def _service_status() -> Dict[str, str]:
    database_status = "down"
    redis_status = "disabled"

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_status = "up"
    except Exception:
        database_status = "down"

    if redis_client:
        try:
            redis_client.ping()
            redis_status = "up"
        except Exception:
            redis_status = "down"

    return {
        "database": database_status,
        "redis": redis_status,
        "openai": "configured" if OPENAI_API_KEY else "not_configured",
        "embeddings": "configured" if embedding_service else "disabled",
        "schema": "warning" if database_schema_warnings else "ok",
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    _ensure_database_ready()
    yield


app = FastAPI(
    title="Arabic Ontology Chat API",
    description="API for querying Arabic ontology with intelligent answer generation",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit_exceeded(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": exc.detail,
            "retry_after": exc.retry_after,
        },
        headers={"Retry-After": str(exc.retry_after)},
    )


def _enforce_rate_limit(request: Request, scope: str) -> None:
    rule = RATE_LIMIT_RULES[scope]
    request_security.enforce_rate_limit(request, scope, rule)


def _build_concept_payloads(concepts: list[Concept]) -> list[Dict[str, Any]]:
    return [
        {
            "uri": concept.uri,
            "labels": concept.labels or [],
            "definition": concept.definition or [],
            "quote": concept.quote or [],
        }
        for concept in concepts
    ]


def _run_embedding_jobs(
    concept_payload: list[Dict[str, Any]],
    synonym_ids: Optional[list[int]] = None,
    relation_ids: Optional[list[int]] = None,
    document_ids: Optional[list[int]] = None,
) -> Dict[str, Any]:
    if not embedding_service:
        raise RuntimeError("Embedding service not configured")

    concept_stats = embedding_service.process_concepts_with_embeddings(concept_payload)
    synonym_stats = embedding_service.process_synonyms_with_embeddings(synonym_ids)
    relation_stats = embedding_service.process_relations_with_embeddings(relation_ids)
    document_stats = embedding_service.process_documents_with_embeddings(document_ids)

    totals = {
        "processed_records": (
            concept_stats.get("total_concepts", 0)
            + synonym_stats.get("total_synonyms", 0)
            + relation_stats.get("total_relations", 0)
            + document_stats.get("total_documents", 0)
        ),
        "generated_embeddings": (
            concept_stats.get("generated_embeddings", 0)
            + synonym_stats.get("generated_embeddings", 0)
            + relation_stats.get("generated_embeddings", 0)
            + document_stats.get("generated_embeddings", 0)
        ),
        "stored_embeddings": (
            concept_stats.get("stored_embeddings", 0)
            + synonym_stats.get("stored_embeddings", 0)
            + relation_stats.get("stored_embeddings", 0)
            + document_stats.get("stored_embeddings", 0)
        ),
        "skipped_embeddings": (
            concept_stats.get("skipped_embeddings", 0)
            + synonym_stats.get("skipped_embeddings", 0)
            + relation_stats.get("skipped_embeddings", 0)
            + document_stats.get("skipped_embeddings", 0)
        ),
    }

    return {
        "concepts": concept_stats,
        "synonyms": synonym_stats,
        "relations": relation_stats,
        "documents": document_stats,
        "totals": totals,
    }


def _count_non_empty_jsonb_array(db: Session, table_name: str, column_name: str) -> int:
    return db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE jsonb_typeof({column_name}) = 'array'
              AND jsonb_array_length({column_name}) > 0
            """
        )
    ).scalar_one()


def _relation_missing_fk_summary(db: Session, relation_ids: Optional[list[int]] = None) -> Dict[str, int]:
    query = db.query(ConceptRelation)
    if relation_ids is not None:
        if not relation_ids:
            return {
                "rows_with_missing_fk": 0,
                "rows_with_missing_source_fk": 0,
                "rows_with_missing_target_fk": 0,
                "distinct_missing_source_uris": 0,
                "distinct_missing_target_uris": 0,
                "distinct_missing_uris": 0,
            }
        query = query.filter(ConceptRelation.id.in_(relation_ids))

    relations = query.all()
    missing_source_uris = {
        relation.source_uri
        for relation in relations
        if relation.source_concept_id is None and relation.source_uri
    }
    missing_target_uris = {
        relation.target_uri
        for relation in relations
        if relation.target_concept_id is None and relation.target_uri
    }

    return {
        "rows_with_missing_fk": sum(
            1
            for relation in relations
            if relation.source_concept_id is None or relation.target_concept_id is None
        ),
        "rows_with_missing_source_fk": sum(
            1 for relation in relations if relation.source_concept_id is None
        ),
        "rows_with_missing_target_fk": sum(
            1 for relation in relations if relation.target_concept_id is None
        ),
        "distinct_missing_source_uris": len(missing_source_uris),
        "distinct_missing_target_uris": len(missing_target_uris),
        "distinct_missing_uris": len(missing_source_uris.union(missing_target_uris)),
    }


def _database_audit(db: Session) -> Dict[str, Any]:
    row_counts = {
        "concepts": db.query(Concept).count(),
        "concept_relations": db.query(ConceptRelation).count(),
        "concept_synonyms": db.query(ConceptSynonym).count(),
        "documents": db.query(Document).count(),
    }

    concept_coverage = {
        "with_labels": _count_non_empty_jsonb_array(db, "concepts", "labels"),
        "with_definition": _count_non_empty_jsonb_array(db, "concepts", "definition"),
        "with_quote": _count_non_empty_jsonb_array(db, "concepts", "quote"),
        "with_actions": _count_non_empty_jsonb_array(db, "concepts", "actions"),
        "with_importance": _count_non_empty_jsonb_array(db, "concepts", "importance"),
    }
    concept_coverage.update(
        {
            "empty_labels": row_counts["concepts"] - concept_coverage["with_labels"],
            "empty_definition": row_counts["concepts"] - concept_coverage["with_definition"],
            "empty_quote": row_counts["concepts"] - concept_coverage["with_quote"],
            "empty_actions": row_counts["concepts"] - concept_coverage["with_actions"],
            "empty_importance": row_counts["concepts"] - concept_coverage["with_importance"],
        }
    )

    embedding_coverage = {
        "concepts": db.query(Concept).filter(Concept.embedding.isnot(None)).count(),
        "concept_synonyms": db.query(ConceptSynonym).filter(ConceptSynonym.embedding.isnot(None)).count(),
        "concept_relations": db.query(ConceptRelation).filter(ConceptRelation.embedding.isnot(None)).count(),
        "documents": db.query(Document).filter(Document.embedding.isnot(None)).count(),
    }

    return {
        "database": {
            "fingerprint": _safe_database_fingerprint(),
            "schema_warnings": list(database_schema_warnings),
        },
        "row_counts": row_counts,
        "concept_coverage": concept_coverage,
        "embedding_coverage": embedding_coverage,
        "unresolved_relation_endpoints": _relation_missing_fk_summary(db),
        "documents": {
            "row_count": row_counts["documents"],
            "status": "not_ingested_from_current_ttl",
        },
    }


async def _process_chat_query(request: QueryRequest, use_ai: bool) -> Dict[str, Any]:
    start_time = time.time()
    mode = "ai" if use_ai else "without_ai"
    try:
        sanitized_question = sanitize_question(request.question, max_length=MAX_QUESTION_LENGTH)
    except SanitizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_request = request.model_copy(update={"question": sanitized_question})
    cache_key = generate_cache_key(normalized_request, mode)

    cached_response = get_cached_response(cache_key)
    if cached_response:
        cached_response.setdefault("mode", mode)
        cached_response["processing_time"] = round(time.time() - start_time, 2)
        return cached_response

    try:
        selected_query_analyzer = query_analyzer if use_ai else query_analyzer_without_ai
        selected_concept_matcher = concept_matcher if use_ai else concept_matcher_without_ai
        selected_answer_composer = answer_composer if use_ai else answer_composer_without_ai
        use_vector_search = normalized_request.use_embeddings if use_ai else False

        query_analysis = selected_query_analyzer.analyze_query(normalized_request.question)
        top_concepts = selected_concept_matcher.find_top_concepts(
            normalized_request.question,
            use_vector=use_vector_search,
            max_concepts=3,
        )

        if not top_concepts:
            response_data = _build_no_match_response(query_analysis.intent.value, start_time, mode)
            cache_response(cache_key, response_data)
            return response_data

        unique_concepts = []
        seen_uris: set[str] = set()
        for candidate in top_concepts:
            candidate_uri = getattr(candidate.concept, "uri", None)
            if not candidate_uri or candidate_uri in seen_uris:
                continue
            seen_uris.add(candidate_uri)
            unique_concepts.append(candidate)

        selected_concept = unique_concepts[0]
        relation_result = RelationExpander(
            DATABASE_URL,
            max_relations=normalized_request.max_relations,
            max_depth=normalized_request.max_depth,
        ).expand_relations(selected_concept.concept, query_analysis.intent)

        composed_answer = selected_answer_composer.compose_answer(
            query_analysis.intent,
            normalized_request.question,
            selected_concept,
            relation_result,
            query_analysis,
            supporting_matches=unique_concepts[1:4],
        )
        regeneration_composer = selected_answer_composer if (use_ai and composed_answer.method == "llm") else None

        final_answer, validation = validate_and_regenerate_answer(
            composed_answer.answer,
            query_analysis.intent,
            normalized_request.question,
            selected_concept,
            relation_result,
            regeneration_composer,
        )

        formatted_top_concepts = [
            {
                "uri": match.concept.uri,
                "labels": _clean_text_list(match.concept.labels),
                "definition": _clean_text_list(match.concept.definition),
                "quote": _clean_text_list(match.concept.quote),
                "actions": _clean_text_list(match.concept.actions),
                "importance": _clean_text_list(match.concept.importance),
                "confidence": round(match.confidence, 3),
            }
            for match in unique_concepts
        ]

        top_quotes = _prepare_top_quotes(selected_concept, relation_result)
        relation_details = _prepare_relation_details(relation_result)
        response_data = {
            "answer": final_answer,
            "confidence": round(composed_answer.confidence, 3),
            "intent": query_analysis.intent.value,
            "mode": mode,
            "sources": composed_answer.sources_used,
            "token_usage": composed_answer.token_usage,
            "processing_time": round(time.time() - start_time, 2),
            "validation_score": round(validation.score, 3),
            "method": composed_answer.method,
            "matched_concept": selected_concept.concept.uri,
            "top_concepts": formatted_top_concepts,
            "top_quotes": top_quotes,
            "quote": top_quotes[0] if top_quotes else None,
            "relations": [detail["summary"] for detail in relation_details],
            "relation_details": relation_details,
        }

        logger.info(
            "Processed query mode=%s method=%s matched=%s",
            mode,
            composed_answer.method,
            selected_concept.concept.uri,
        )
        cache_response(cache_key, response_data)
        return response_data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Chat query failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ أثناء معالجة السؤال. راجع سجلات الخادم لمعرفة التفاصيل.",
        ) from exc


@app.post("/api/chat/query", response_model=QueryResponse)
async def chat_query(request: QueryRequest, http_request: Request) -> Dict[str, Any]:
    _enforce_rate_limit(http_request, "chat_query")
    return await _process_chat_query(request, use_ai=True)


@app.post("/api/chat/query-without-ai", response_model=QueryResponse)
async def chat_query_without_ai(request: QueryRequest, http_request: Request) -> Dict[str, Any]:
    _enforce_rate_limit(http_request, "chat_query_without_ai")
    return await _process_chat_query(request, use_ai=False)


@app.post("/api/ontology/upload")
async def upload_ontology_file(
    request: Request,
    file: UploadFile = File(...),
    generate_embeddings: bool = False,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _enforce_rate_limit(request, "ontology_upload")
    validate_ttl_file(file)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ttl") as temp_file:
        content = await file.read()
        try:
            decoded_content = decode_utf8_payload(content)
        except SanitizationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        temp_file.write(decoded_content.encode("utf-8"))
        temp_file_path = temp_file.name

    try:
        parsed_data = parse_ttl(temp_file_path)
        if "parse_error" in parsed_data:
            raise HTTPException(status_code=400, detail=f"TTL parsing failed: {parsed_data['parse_error']}")

        concepts_created = 0
        concepts_updated = 0
        synonyms_created = 0
        relations_created = 0
        stored_synonyms: list[ConceptSynonym] = []
        stored_relations: list[ConceptRelation] = []

        for concept_data in parsed_data["concepts"]:
            _, created = upsert_concept(db, concept_data)
            if created:
                concepts_created += 1
            else:
                concepts_updated += 1

        db.flush()

        concept_uris = [concept_data["uri"] for concept_data in parsed_data["concepts"]]
        existing_concepts = db.execute(
            select(Concept).where(Concept.uri.in_(concept_uris))
        ).scalars().all()
        concept_id_by_uri = {concept.uri: concept.id for concept in existing_concepts}

        for synonym_data in parsed_data["synonyms"]:
            synonym, created = upsert_synonym(db, synonym_data, concept_id_by_uri)
            if created:
                synonyms_created += 1
            stored_synonyms.append(synonym)

        db.flush()
        stored_synonym_ids = [synonym.id for synonym in stored_synonyms if synonym.id is not None]

        for relation_data in parsed_data["relations"]:
            relation, created = upsert_relation(db, relation_data, concept_id_by_uri)
            if relation:
                if created:
                    relations_created += 1
                stored_relations.append(relation)

        db.flush()
        stored_relation_ids = [relation.id for relation in stored_relations if relation.id is not None]

        db.commit()

        embedding_summary: Dict[str, Any] = {
            "concepts": {
                "total_concepts": len(parsed_data["concepts"]),
                "generated_embeddings": 0,
                "stored_embeddings": 0,
                "skipped_embeddings": 0,
            },
            "synonyms": {
                "total_synonyms": len(stored_synonym_ids),
                "generated_embeddings": 0,
                "stored_embeddings": 0,
                "skipped_embeddings": 0,
            },
            "relations": {
                "total_relations": len(stored_relation_ids),
                "generated_embeddings": 0,
                "stored_embeddings": 0,
                "skipped_embeddings": 0,
            },
            "documents": {
                "total_documents": 0,
                "generated_embeddings": 0,
                "stored_embeddings": 0,
                "skipped_embeddings": 0,
                "status": "not_ingested_from_current_ttl",
            },
            "totals": {
                "processed_records": len(parsed_data["concepts"]) + len(stored_synonym_ids) + len(stored_relation_ids),
                "generated_embeddings": 0,
                "stored_embeddings": 0,
                "skipped_embeddings": 0,
            },
        }
        embedding_status = "not_requested"
        embedding_error = None
        if generate_embeddings and embedding_service:
            try:
                embedding_summary = _run_embedding_jobs(
                    parsed_data["concepts"],
                    synonym_ids=stored_synonym_ids,
                    relation_ids=stored_relation_ids,
                    document_ids=[],
                )
                embedding_status = "completed"
            except Exception as exc:
                logger.warning("Embedding generation failed after upload: %s", exc)
                embedding_status = "failed"
                embedding_error = str(exc)
        elif generate_embeddings:
            embedding_status = "unavailable"
            embedding_error = "Embedding service not configured"

        unresolved_relations = _relation_missing_fk_summary(db, stored_relation_ids)
        clear_query_cache()

        return {
            "status": "success",
            "message": "Ontology file processed successfully",
            "data": {
                "concepts_stored": concepts_created + concepts_updated,
                "concepts_created": concepts_created,
                "concepts_updated": concepts_updated,
                "synonyms_stored": synonyms_created,
                "relations_stored": relations_created,
                "concepts_embeddings_processed": embedding_summary["concepts"]["total_concepts"],
                "concepts_embeddings_stored": embedding_summary["concepts"]["stored_embeddings"],
                "synonyms_embeddings_processed": embedding_summary["synonyms"]["total_synonyms"],
                "synonyms_embeddings_stored": embedding_summary["synonyms"]["stored_embeddings"],
                "relations_embeddings_processed": embedding_summary["relations"]["total_relations"],
                "relations_embeddings_stored": embedding_summary["relations"]["stored_embeddings"],
                "documents_embeddings_processed": embedding_summary["documents"]["total_documents"],
                "documents_embeddings_stored": embedding_summary["documents"]["stored_embeddings"],
                "embeddings_generated": embedding_summary["totals"]["generated_embeddings"],
                "embeddings_stored": embedding_summary["totals"]["stored_embeddings"],
                "embedding_status": embedding_status,
                "embedding_error": embedding_error,
                "embedding_summary": embedding_summary,
                "undefined_relation_endpoints": unresolved_relations,
                "warnings": parsed_data.get("warnings", []),
            },
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected ontology upload failure: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error while processing the ontology file.") from exc
    finally:
        os.unlink(temp_file_path)


@app.post("/api/ontology/reindex")
async def reindex_ontology(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _enforce_rate_limit(request, "ontology_reindex")
    if not embedding_service:
        raise HTTPException(status_code=503, detail="Embedding service not configured")

    concepts = db.query(Concept).all()
    concept_payload = _build_concept_payloads(concepts)

    try:
        embedding_summary = _run_embedding_jobs(concept_payload)
    except Exception as exc:
        logger.exception("Embedding reindex failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Embedding generation failed: {exc}",
        ) from exc

    clear_query_cache()
    return {
        "status": "success",
        "concepts_processed": embedding_summary["concepts"].get("total_concepts", 0),
        "concepts_embeddings_stored": embedding_summary["concepts"].get("stored_embeddings", 0),
        "synonyms_processed": embedding_summary["synonyms"].get("total_synonyms", 0),
        "synonyms_embeddings_stored": embedding_summary["synonyms"].get("stored_embeddings", 0),
        "relations_processed": embedding_summary["relations"].get("total_relations", 0),
        "relations_embeddings_stored": embedding_summary["relations"].get("stored_embeddings", 0),
        "documents_processed": embedding_summary["documents"].get("total_documents", 0),
        "documents_embeddings_stored": embedding_summary["documents"].get("stored_embeddings", 0),
        "embeddings_generated": embedding_summary["totals"].get("generated_embeddings", 0),
        "embeddings_stored": embedding_summary["totals"].get("stored_embeddings", 0),
        "embeddings_skipped": embedding_summary["totals"].get("skipped_embeddings", 0),
        "undefined_relation_endpoints": _relation_missing_fk_summary(db),
        "embedding_summary": embedding_summary,
    }


@app.get("/api/stats")
async def get_stats(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _enforce_rate_limit(request, "stats")
    audit = _database_audit(db)
    return {
        "concept_count": audit["row_counts"]["concepts"],
        "embedding_count": audit["embedding_coverage"]["concepts"],
        "relation_count": audit["row_counts"]["concept_relations"],
        "synonym_count": audit["row_counts"]["concept_synonyms"],
        "document_count": audit["row_counts"]["documents"],
        "embedding_coverage": audit["embedding_coverage"],
        "concept_coverage": audit["concept_coverage"],
        "documents_status": audit["documents"]["status"],
        "unresolved_relation_endpoints": audit["unresolved_relation_endpoints"],
        "total_queries": 0,
        "avg_processing_time": 0.0,
        "avg_confidence": 0.0,
    }


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    statuses = _service_status()
    overall_status = "healthy" if statuses["database"] == "up" else "degraded"
    if database_schema_warnings:
        overall_status = "degraded"
    return {
        "status": overall_status,
        "services": statuses,
        "schema_warnings": list(database_schema_warnings),
    }


@app.get("/api/debug/database-audit")
async def debug_database_audit(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _enforce_rate_limit(request, "database_audit")
    return _database_audit(db)


@app.get("/api/debug/concept_matcher_module")
async def debug_concept_matcher_module() -> Dict[str, str]:
    import processing.concept_matcher as concept_matcher_module

    return {"concept_matcher_file": concept_matcher_module.__file__}
