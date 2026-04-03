import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from fastapi import Request


CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
HTML_TAG_PATTERN = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int
    label: str


class RateLimitExceeded(Exception):
    def __init__(self, detail: str, retry_after: int):
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after


class SanitizationError(ValueError):
    pass


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, Tuple[int, float]] = {}

    def consume(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        now = time.time()
        with self._lock:
            count, reset_at = self._buckets.get(key, (0, now + window_seconds))
            if reset_at <= now:
                count = 0
                reset_at = now + window_seconds

            count += 1
            self._buckets[key] = (count, reset_at)

            if count <= limit:
                return True, 0

            retry_after = max(1, int(reset_at - now))
            return False, retry_after

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class RequestSecurityManager:
    def __init__(self, redis_client=None, prefix: str = "rate_limit") -> None:
        self.redis_client = redis_client
        self.prefix = prefix
        self.memory_limiter = InMemoryRateLimiter()

    def _redis_key(self, scope: str, identifier: str) -> str:
        return f"{self.prefix}:{scope}:{identifier}"

    def _consume_redis(self, scope: str, identifier: str, rule: RateLimitRule) -> Tuple[bool, int]:
        if not self.redis_client:
            return self.memory_limiter.consume(
                self._redis_key(scope, identifier), rule.limit, rule.window_seconds
            )

        try:
            key = self._redis_key(scope, identifier)
            pipeline = self.redis_client.pipeline()
            pipeline.incr(key)
            pipeline.ttl(key)
            count, ttl = pipeline.execute()

            if count == 1 or ttl == -1:
                self.redis_client.expire(key, rule.window_seconds)
                ttl = rule.window_seconds

            if count <= rule.limit:
                return True, 0

            retry_after = max(1, int(ttl if ttl and ttl > 0 else rule.window_seconds))
            return False, retry_after
        except Exception:
            return self.memory_limiter.consume(
                self._redis_key(scope, identifier), rule.limit, rule.window_seconds
            )

    def _client_identifier(self, request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        if request.client and request.client.host:
            return request.client.host

        return "unknown"

    def enforce_rate_limit(self, request: Request, scope: str, rule: RateLimitRule) -> None:
        identifier = self._client_identifier(request)
        allowed, retry_after = self._consume_redis(scope, identifier, rule)
        if allowed:
            return

        raise RateLimitExceeded(
            detail=f"تم تجاوز الحد المسموح لهذا المسار: {rule.label}",
            retry_after=retry_after,
        )

    def reset(self) -> None:
        self.memory_limiter.reset()


def sanitize_question(question: str, max_length: int = 500) -> str:
    cleaned = CONTROL_CHAR_PATTERN.sub(" ", str(question or "").replace("\x00", " "))
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned).strip()

    if not cleaned:
        raise SanitizationError("السؤال فارغ بعد تنظيف الإدخال.")

    if HTML_TAG_PATTERN.search(cleaned):
        raise SanitizationError("يحتوي السؤال على وسوم HTML خام غير مسموح بها.")

    if len(cleaned) > max_length:
        raise SanitizationError(f"السؤال يتجاوز الحد الأقصى المسموح وهو {max_length} حرفاً.")

    return cleaned


def decode_utf8_payload(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SanitizationError("ملف TTL يجب أن يكون UTF-8 صالحاً.") from exc
