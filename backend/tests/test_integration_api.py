import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main
from app.security import RequestSecurityManager
from core.models import Concept, ConceptRelation, ConceptSynonym, Document
from processing.concept_matcher import ConceptMatcher
from processing.ttl_parser import parse_ttl
from services.openai_client import OpenAIClient


EXPECTED_COUNTS = {
    "concepts": 2594,
    "synonyms": 3684,
    "relations": 6900,
    "documents": 0,
}


def minimal_query_response(mode: str = "ai") -> dict:
    return {
        "answer": "إجابة اختبارية",
        "confidence": 0.9,
        "intent": "definition",
        "mode": mode,
        "sources": [],
        "token_usage": None,
        "processing_time": 0.01,
        "validation_score": 0.95,
        "method": "template",
        "matched_concept": "test:concept",
        "top_concepts": [],
        "top_quotes": [],
        "quote": None,
        "relations": [],
        "relation_details": [],
    }


class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(main.app)

    def setUp(self) -> None:
        main.redis_client = None
        main.request_security = RequestSecurityManager(redis_client=None)

    def test_parser_and_database_counts_match_expected(self) -> None:
        parsed = parse_ttl(str(ROOT_DIR / "unified_ontology.ttl"))
        self.assertEqual(len(parsed["concepts"]), EXPECTED_COUNTS["concepts"])
        self.assertEqual(len(parsed["synonyms"]), EXPECTED_COUNTS["synonyms"])
        self.assertEqual(len(parsed["relations"]), EXPECTED_COUNTS["relations"])
        self.assertNotIn("parse_error", parsed)

        with main.SessionLocal() as db:
            self.assertEqual(db.query(Concept).count(), EXPECTED_COUNTS["concepts"])
            self.assertEqual(db.query(ConceptSynonym).count(), EXPECTED_COUNTS["synonyms"])
            self.assertEqual(db.query(ConceptRelation).count(), EXPECTED_COUNTS["relations"])
            self.assertEqual(db.query(Document).count(), EXPECTED_COUNTS["documents"])

    def test_without_ai_endpoint_does_not_call_openai_or_vector_search(self) -> None:
        payload = {
            "question": "ما هو القرآن؟",
            "use_embeddings": True,
            "max_relations": 6,
            "max_depth": 2,
        }

        with patch.object(
            OpenAIClient,
            "generate_answer_with_fallback",
            side_effect=AssertionError("OpenAI should not be called in without_ai mode"),
        ), patch.object(
            ConceptMatcher,
            "_vector_similarity_search",
            side_effect=AssertionError("Vector search should not be called in without_ai mode"),
        ):
            response = self.client.post("/api/chat/query-without-ai", json=payload)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["mode"], "without_ai")
        self.assertEqual(body["method"], "template")

    def test_without_ai_endpoint_recovers_locally_equivalent_phrase(self) -> None:
        response = self.client.post(
            "/api/chat/query-without-ai",
            json={
                "question": "ما هو اتباع النبي؟",
                "use_embeddings": False,
                "max_relations": 6,
                "max_depth": 2,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["mode"], "without_ai")
        self.assertNotEqual(body["method"], "no_match")
        top_labels = [
            label
            for concept in body.get("top_concepts", [])
            for label in concept.get("labels", [])
        ]
        self.assertTrue(
            any("الرسول" in label or "اتبعوني" in label for label in top_labels),
            msg=f"unexpected labels: {top_labels}",
        )

    def test_query_endpoint_rejects_raw_html(self) -> None:
        response = self.client.post(
            "/api/chat/query",
            json={
                "question": "<script>alert(1)</script>",
                "use_embeddings": False,
                "max_relations": 4,
                "max_depth": 2,
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("HTML", response.json()["detail"])

    def test_query_endpoint_rate_limits_after_configured_threshold(self) -> None:
        mocked = AsyncMock(return_value=minimal_query_response())
        with patch.object(main, "_process_chat_query", new=mocked):
            for _ in range(30):
                response = self.client.post(
                    "/api/chat/query",
                    json={
                        "question": "ما هو القرآن؟",
                        "use_embeddings": False,
                        "max_relations": 4,
                        "max_depth": 2,
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)

            blocked = self.client.post(
                "/api/chat/query",
                json={
                    "question": "ما هو القرآن؟",
                    "use_embeddings": False,
                    "max_relations": 4,
                    "max_depth": 2,
                },
            )

        self.assertEqual(blocked.status_code, 429, blocked.text)
        blocked_payload = blocked.json()
        self.assertIn("retry_after", blocked_payload)
        self.assertGreaterEqual(blocked_payload["retry_after"], 1)
        self.assertEqual(mocked.await_count, 30)

    def test_stats_and_audit_endpoints_return_current_shape(self) -> None:
        stats_response = self.client.get("/api/stats")
        audit_response = self.client.get("/api/debug/database-audit")

        self.assertEqual(stats_response.status_code, 200, stats_response.text)
        self.assertEqual(audit_response.status_code, 200, audit_response.text)

        stats_payload = stats_response.json()
        audit_payload = audit_response.json()

        self.assertIn("concept_count", stats_payload)
        self.assertIn("embedding_coverage", stats_payload)
        self.assertIn("documents_status", stats_payload)
        self.assertIn("row_counts", audit_payload)
        self.assertIn("embedding_coverage", audit_payload)
        self.assertEqual(audit_payload["documents"]["status"], "not_ingested_from_current_ttl")

    def test_reindex_endpoint_uses_expanded_summary_shape(self) -> None:
        summary = {
            "concepts": {"total_concepts": 10, "stored_embeddings": 8, "generated_embeddings": 8, "skipped_embeddings": 2},
            "synonyms": {"total_synonyms": 4, "stored_embeddings": 4, "generated_embeddings": 4, "skipped_embeddings": 0},
            "relations": {"total_relations": 6, "stored_embeddings": 6, "generated_embeddings": 6, "skipped_embeddings": 0},
            "documents": {"total_documents": 0, "stored_embeddings": 0, "generated_embeddings": 0, "skipped_embeddings": 0},
            "totals": {"stored_embeddings": 18, "generated_embeddings": 18, "skipped_embeddings": 2},
        }

        with patch.object(main, "embedding_service", new=object()), patch.object(
            main,
            "_run_embedding_jobs",
            return_value=summary,
        ):
            response = self.client.post("/api/ontology/reindex")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["concepts_processed"], 10)
        self.assertEqual(payload["synonyms_processed"], 4)
        self.assertEqual(payload["relations_processed"], 6)
        self.assertEqual(payload["embeddings_stored"], 18)
        self.assertEqual(payload["embeddings_skipped"], 2)

    def test_upload_ttl_is_idempotent_without_embeddings(self) -> None:
        ttl_path = ROOT_DIR / "unified_ontology.ttl"
        content = ttl_path.read_bytes()

        with main.SessionLocal() as db:
            before = {
                "concepts": db.query(Concept).count(),
                "synonyms": db.query(ConceptSynonym).count(),
                "relations": db.query(ConceptRelation).count(),
            }

        files = {"file": ("unified_ontology.ttl", content, "text/turtle")}
        first_response = self.client.post("/api/ontology/upload", files=files)
        self.assertEqual(first_response.status_code, 200, first_response.text)

        files = {"file": ("unified_ontology.ttl", content, "text/turtle")}
        second_response = self.client.post("/api/ontology/upload", files=files)
        self.assertEqual(second_response.status_code, 200, second_response.text)

        with main.SessionLocal() as db:
            after = {
                "concepts": db.query(Concept).count(),
                "synonyms": db.query(ConceptSynonym).count(),
                "relations": db.query(ConceptRelation).count(),
            }

        self.assertEqual(before, after)
        self.assertEqual(after["concepts"], EXPECTED_COUNTS["concepts"])
        self.assertEqual(after["synonyms"], EXPECTED_COUNTS["synonyms"])
        self.assertEqual(after["relations"], EXPECTED_COUNTS["relations"])


if __name__ == "__main__":
    unittest.main()
