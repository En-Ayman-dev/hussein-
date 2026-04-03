import re
import logging
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from openai import APIError, OpenAI, RateLimitError
from processing.text_normalizer import ArabicNormalizer

logger = logging.getLogger(__name__)


class QueryIntent(Enum):
    """Enumeration of possible query intents."""
    DEFINITION = "definition"
    CAUSE = "cause"
    SOLUTION = "solution"
    COMPARISON = "comparison"
    UNKNOWN = "unknown"


@dataclass
class QueryAnalysis:
    """Result of query analysis."""
    intent: QueryIntent
    confidence: float
    keywords: List[str]
    method: str  # "rule_based" or "llm"
    query: str  # The original query text
    raw_response: Optional[str] = None


class QueryAnalyzer:
    """Analyzer for Arabic ontology queries using rule-based and LLM approaches."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        llm_model: str = "gpt-4o-mini",
        confidence_threshold: float = 0.55
    ):
        """Initialize the query analyzer.

        Args:
            openai_api_key: OpenAI API key for LLM fallback
            llm_model: OpenAI model to use
            confidence_threshold: Minimum confidence for rule-based classification
        """
        self.text_normalizer = ArabicNormalizer()
        self.openai_api_key = openai_api_key
        self.llm_model = llm_model
        self.confidence_threshold = confidence_threshold
        self.openai_client = None
        if openai_api_key:
            try:
                self.openai_client = OpenAI(api_key=openai_api_key)
            except Exception as exc:
                logger.warning("Query analyzer LLM disabled: %s", exc)

        # Rule-based patterns for intent classification
        self.intent_patterns = self._build_intent_patterns()

        # Keywords for each intent
        self.intent_keywords = {
            intent: [self.text_normalizer.normalize_text(keyword) for keyword in keywords]
            for intent, keywords in self._build_intent_keywords().items()
        }

    def _build_intent_patterns(self) -> Dict[QueryIntent, List[str]]:
        """Build regex patterns for intent classification."""
        return {
            QueryIntent.DEFINITION: [
                r'\b(ما\s*هو|ماهو|ما\s*هي|ماهي|تعريف|معنى|شرح|وصف)\b',
                r'\b(ما\s+المقصود\s+ب|ما\s+يعني)\b',
                r'\b(من\s+هو|من\s+هي)\b',
            ],
            QueryIntent.CAUSE: [
                r'\b(لماذا|لما|سبب|أسباب|ما\s+السبب)\b',
                r'\b(كيف\s+حدث|ما\s+الذي\s+أدى\s+إلى)\b',
                r'\b(من\s+أين\s+جاء|ما\s+المصدر)\b',
            ],
            QueryIntent.SOLUTION: [
                r'\b(كيف\s+|طريقة|خطوات|حل|الحل)\b',
                r'\b(ما\s+الطريقة|كيف\s+أفعل|كيف\s+نفعل)\b',
                r'\b(نصيحة|نصائح|إرشاد|إرشادات)\b',
            ],
            QueryIntent.COMPARISON: [
                r'\b(مقارنة|فرق\s+بين|أيهما|ما\s+الفرق)\b',
                r'\b(أفضل|أحسن|مقابل|بديل)\b',
                r'\b(بين|ضد|مع|و)\b.*\b(و|أم|أو)\b',
            ],
        }

    def _build_intent_keywords(self) -> Dict[QueryIntent, List[str]]:
        """Build keyword lists for intent classification."""
        return {
            QueryIntent.DEFINITION: [
                'تعريف', 'معنى', 'شرح', 'وصف', 'مفهوم', 'مبدأ',
                'ما هو', 'ما هي', 'من هو', 'من هي'
            ],
            QueryIntent.CAUSE: [
                'سبب', 'أسباب', 'لماذا', 'لما', 'كيف حدث', 'مصدر',
                'أصل', 'منشأ', 'جذور'
            ],
            QueryIntent.SOLUTION: [
                'حل', 'طريقة', 'خطوات', 'كيف', 'نصيحة', 'إرشاد',
                'علاج', 'تصرف', 'إجراء'
            ],
            QueryIntent.COMPARISON: [
                'مقارنة', 'فرق', 'أيهما', 'أفضل', 'أحسن', 'بديل',
                'مقابل', 'بين', 'ضد'
            ],
        }

    def _normalize_query(self, query: str) -> str:
        """Normalize the query text for analysis."""
        return self.text_normalizer.normalize_text(query)

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract keywords from the query.

        Args:
            query: Input query text

        Returns:
            List of extracted keywords
        """
        normalized = self._normalize_query(query)
        normalized = re.sub(r"[؟?!،,:؛;]+", " ", normalized)

        # Split into words and filter
        words = re.findall(r'\b\w+\b', normalized)

        # Remove common Arabic stop words
        stop_words = {
            'في', 'على', 'من', 'إلى', 'عن', 'مع', 'هو', 'هي', 'هم', 'هن',
            'أنا', 'نحن', 'أنت', 'أنتِ', 'أنتم', 'أنتن', 'هو', 'هي', 'هما',
            'كان', 'كانت', 'كانوا', 'سوف', 'سي', 'قد', 'كان', 'كانت', 'إذا',
            'أو', 'و', 'لكن', 'بل', 'أم', 'إما', 'ثم', 'أي', 'كل', 'بعض'
        }

        keywords = [
            re.sub(r"^و+", "", word)
            for word in words
            if len(re.sub(r"^و+", "", word)) > 1 and re.sub(r"^و+", "", word) not in stop_words
        ]

        # Limit to most relevant keywords (up to 10)
        return keywords[:10]

    def _classify_rule_based(self, query: str) -> Tuple[QueryIntent, float]:
        """Classify query intent using rule-based approach.

        Args:
            query: Normalized query text

        Returns:
            Tuple of (intent, confidence)
        """
        scores = {intent: 0.0 for intent in QueryIntent}

        # Check patterns
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    scores[intent] += 0.4  # Pattern match weight

        # Check keywords
        words = re.findall(r'\b\w+\b', query.lower())
        for intent, keywords in self.intent_keywords.items():
            for keyword in keywords:
                if keyword in query:
                    scores[intent] += 0.3  # Keyword match weight

        # Find best intent
        best_intent = max(scores, key=scores.get)
        confidence = scores[best_intent]

        # Normalize confidence
        total_score = sum(scores.values())
        if total_score > 0:
            confidence = confidence / total_score

        return best_intent, min(confidence, 1.0)

    def _classify_with_llm(self, query: str) -> Tuple[QueryIntent, float, str]:
        """Classify query intent using LLM.

        Args:
            query: Original query text

        Returns:
            Tuple of (intent, confidence, raw_response)
        """
        if not self.openai_api_key or not self.openai_client:
            return QueryIntent.UNKNOWN, 0.0, "No OpenAI API key configured"

        try:
            prompt = f"""
            Analyze this Arabic question and classify its intent. Return only a JSON object with these fields:
            - intent: one of ["definition", "cause", "solution", "comparison", "unknown"]
            - confidence: number between 0 and 1
            - reasoning: brief explanation

            Question: {query}

            JSON response:
            """

            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.1
            )

            raw_response = (response.choices[0].message.content or "").strip()
            cleaned_response = raw_response
            fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_response, re.DOTALL)
            if fenced_match:
                cleaned_response = fenced_match.group(1).strip()

            # Parse JSON response
            try:
                result = json.loads(cleaned_response)

                intent_str = result.get("intent", "unknown")
                confidence = float(result.get("confidence", 0.0))

                # Convert string to enum
                intent_map = {
                    "definition": QueryIntent.DEFINITION,
                    "cause": QueryIntent.CAUSE,
                    "solution": QueryIntent.SOLUTION,
                    "comparison": QueryIntent.COMPARISON,
                    "unknown": QueryIntent.UNKNOWN
                }

                intent = intent_map.get(intent_str.lower(), QueryIntent.UNKNOWN)

                return intent, confidence, raw_response

            except json.JSONDecodeError:
                logger.warning(f"Failed to parse LLM response: {raw_response}")
                return QueryIntent.UNKNOWN, 0.0, raw_response

        except (RateLimitError, APIError, Exception) as e:
            logger.error(f"LLM classification failed: {e}")
            return QueryIntent.UNKNOWN, 0.0, str(e)

    def analyze_query(self, query: str) -> QueryAnalysis:
        """Analyze an Arabic query to determine intent and extract keywords.

        Args:
            query: Arabic question text

        Returns:
            QueryAnalysis object with intent, confidence, keywords, and method
        """
        if not query or not query.strip():
            return QueryAnalysis(
                intent=QueryIntent.UNKNOWN,
                confidence=0.0,
                keywords=[],
                method="empty_query",
                query=query
            )

        # Extract keywords first
        keywords = self._extract_keywords(query)

        # Try rule-based classification
        normalized_query = self._normalize_query(query)
        intent, confidence = self._classify_rule_based(normalized_query)

        method = "rule_based"
        raw_response = None

        # Fallback to LLM if confidence is low
        if confidence < self.confidence_threshold and self.openai_api_key:
            logger.info(f"Rule-based confidence {confidence:.2f} below threshold, using LLM")
            llm_intent, llm_confidence, raw_response = self._classify_with_llm(query)

            # Use LLM result if it's more confident
            if llm_confidence > confidence:
                intent = llm_intent
                confidence = llm_confidence
                method = "llm"
            else:
                raw_response = None

        return QueryAnalysis(
            intent=intent,
            confidence=confidence,
            keywords=keywords,
            method=method,
            raw_response=raw_response,
            query=query
        )


# Convenience functions
def analyze_arabic_query(
    query: str,
    openai_api_key: Optional[str] = None,
    **kwargs
) -> QueryAnalysis:
    """Convenience function to analyze an Arabic query."""
    analyzer = QueryAnalyzer(openai_api_key=openai_api_key, **kwargs)
    return analyzer.analyze_query(query)


def extract_query_keywords(query: str) -> List[str]:
    """Convenience function to extract keywords from a query."""
    analyzer = QueryAnalyzer()
    return analyzer._extract_keywords(query)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Analyze Arabic ontology queries")
    parser.add_argument("query", help="Arabic question to analyze")
    parser.add_argument("--openai-key", help="OpenAI API key for LLM fallback")
    parser.add_argument("--confidence-threshold", type=float, default=0.7, help="Confidence threshold for rule-based classification")

    args = parser.parse_args()

    analyzer = QueryAnalyzer(
        openai_api_key=args.openai_key,
        confidence_threshold=args.confidence_threshold
    )

    result = analyzer.analyze_query(args.query)

    output = {
        "query": args.query,
        "intent": result.intent.value,
        "confidence": result.confidence,
        "keywords": result.keywords,
        "method": result.method,
    }

    if result.raw_response:
        output["llm_response"] = result.raw_response

    print(json.dumps(output, ensure_ascii=False, indent=2))
