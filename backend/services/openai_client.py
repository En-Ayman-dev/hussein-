import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from openai import APIError, OpenAI, RateLimitError

logger = logging.getLogger(__name__)


@dataclass
class OpenAIResult:
    """LLM output plus optional usage metadata."""

    content: str
    token_usage: Optional[Dict[str, int]] = None


class OpenAIClient:
    """OpenAI client for generating grounded answers from structured context."""

    MAX_CONTEXT_CHARS = 12000

    SYSTEM_PROMPT = (
        'أنت "محرك الاستدلال المعرفي لرؤية السيد حسين بدر الدين الحوثي". '
        "مهمتك تقديم إجابات عربية قوية بالاعتماد الحصري على السياق المنظم.\n\n"
        "قواعد المرجعية:\n"
        "1. لا تستخدم أي معلومة من خارج السياق.\n"
        "2. إذا غاب جانب محدد، فقل إنه غير وارد في النصوص المتوفرة لديك، ثم اذكر أقرب مبدأ عام من السياق فقط.\n"
        "3. لا تظهر أي معرفات تقنية أو روابط خام أو أسماء خصائص داخلية.\n"
        "4. أي آية أو اقتباس يجب أن يكون منقولاً من النص الموجود في السياق نفسه، لا من الذاكرة.\n\n"
        "طريقة الجواب:\n"
        "1. حدد المفهوم المركزي من بداية السؤال ومن المفهوم الرئيسي في السياق.\n"
        "2. إذا كان السؤال مركباً، فأجب عن الشقين: التعريف ثم الكيفية أو الأثر العملي.\n"
        "3. لا تكتفِ بأول تعريف فقط. إذا كان في السياق أكثر من تعريف أو اقتباس أو إجراء مناسب، فاستخدم أكثر من شاهد واحد عندما يخدم السؤال.\n"
        "4. ابدأ بالنص التأسيسي الأقوى إن وجد، ثم ابنِ عليه التحليل، ثم بيّن جهة الانحراف أو التضليل إن كانت موجودة، ثم اختم بالموقف العملي.\n"
        "5. عند وجود actions أو relations أو context_evidence، حولها إلى جواب حي، لا إلى سرد جامد لحقول البيانات.\n\n"
        "الشخصية والنبرة:\n"
        "1. العربية فصحى مباشرة وقوية، بروح تفسير ثم تشخيص ثم توجيه.\n"
        "2. اربط الجواب بالأمة والناس والواقع العملي، ولا تتركه تعريفاً ذهنياً مجرداً.\n"
        "3. استخدم الاستفهام الإنكاري والتوكيد عند الحاجة فقط، بلا حشو.\n"
        "4. تجنب الأسلوب الأكاديمي البارد، وتجنب أيضاً الزخرفة الأدبية الفارغة.\n\n"
        "التنسيق:\n"
        "1. إذا وُجد اقتباس أو آية مناسبة، فاعرضها أولاً بصيغة markdown blockquote.\n"
        "2. بعد ذلك اكتب 2 إلى 4 فقرات قصيرة مترابطة.\n"
        "3. استخدم تعداداً نقطياً فقط إذا كانت هناك خطوات عملية صريحة في السياق.\n"
        "4. لا تضع عناوين شكلية مثل: الخلاصة، التعريف، التحليل، إلا إذا طلب المستخدم ذلك.\n"
        "5. المطلوب جواب يجيب عن السؤال فعلاً، لا إعادة تنسيق للمدخلات."
    )

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        max_tokens: int = 1000,
        temperature: float = 0.1,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        max_retry_delay: float = 60.0,
    ):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_retry_delay = max_retry_delay

    def _prepare_context_json(self, context: Dict[str, Any]) -> str:
        return json.dumps(self._clean_context(context), ensure_ascii=False, indent=2)

    def _clean_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}

        for key, value in context.items():
            if hasattr(value, "__dict__"):
                clean[key] = self._object_to_dict(value)
            elif isinstance(value, (list, tuple)):
                clean[key] = [self._clean_value(item) for item in value]
            elif isinstance(value, dict):
                clean[key] = self._clean_context(value)
            else:
                clean[key] = self._clean_value(value)

        return clean

    def _object_to_dict(self, obj: Any) -> Dict[str, Any]:
        if not hasattr(obj, "__dict__"):
            return {"value": str(obj)}

        result: Dict[str, Any] = {}
        for key, value in obj.__dict__.items():
            if key.startswith("_"):
                continue
            result[key] = self._clean_value(value)
        return result

    def _clean_value(self, value: Any) -> Any:
        if hasattr(value, "__dict__"):
            return self._object_to_dict(value)
        if isinstance(value, (int, float, str, bool, type(None))):
            return value
        if isinstance(value, dict):
            return self._clean_context(value)
        if isinstance(value, (list, tuple)):
            return [self._clean_value(item) for item in value]
        return str(value)

    def _make_api_call(self, context_json: str, user_query: str) -> OpenAIResult:
        delay = self.retry_delay
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                "السياق المعرفي المنظم:\n"
                f"{context_json}\n\n"
                "سؤال المستخدم:\n"
                f"{user_query}\n\n"
                "اكتب الجواب النهائي مباشرة للمستخدم بالعربية، ملتزماً تماماً بالسياق أعلاه. "
                "إذا وجدت في context_evidence أكثر من شاهد مناسب، فاستخدم أكثر من شاهد واحد في الجواب. "
                "لا تكتف بإعادة تعريف واحد إذا كان السؤال يطلب بناء الوعي أو التوجيه أو المواجهة."
                ),
            },
        ]

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )

                content = (response.choices[0].message.content or "").strip()
                usage = None
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }

                return OpenAIResult(content=content, token_usage=usage)

            except RateLimitError as exc:
                if attempt == self.max_retries:
                    raise
                logger.warning("OpenAI rate limit, retrying in %.1fs: %s", delay, exc)
                time.sleep(delay)
                delay = min(delay * 2, self.max_retry_delay)
            except APIError as exc:
                if attempt == self.max_retries:
                    raise
                logger.warning("OpenAI API error, retrying in %.1fs: %s", delay, exc)
                time.sleep(delay)
                delay = min(delay * 2, self.max_retry_delay)

        raise RuntimeError("OpenAI call retries exhausted")

    def generate_answer(self, context: Dict[str, Any], user_query: str) -> OpenAIResult:
        try:
            context_json = self._prepare_context_json(context)

            # Keep enough room for the response.
            if len(context_json) > self.MAX_CONTEXT_CHARS:
                logger.info("Truncating LLM context from %s to %s chars", len(context_json), self.MAX_CONTEXT_CHARS)
                context_json = context_json[: self.MAX_CONTEXT_CHARS]

            return self._make_api_call(context_json, user_query)
        except Exception as exc:
            logger.error("Failed to generate answer: %s", exc)
            return OpenAIResult(
                content=f"عذراً، حدث خطأ في إنشاء الإجابة: {exc}",
                token_usage=None,
            )

    def generate_answer_with_fallback(
        self,
        context: Dict[str, Any],
        user_query: str,
        fallback_answer: Optional[str] = None,
    ) -> OpenAIResult:
        result = self.generate_answer(context, user_query)
        if result.content.startswith("عذراً، حدث خطأ"):
            return OpenAIResult(
                content=fallback_answer
                or "عذراً، لم نتمكن من إنشاء إجابة في الوقت الحالي. يرجى المحاولة مرة أخرى.",
                token_usage=result.token_usage,
            )
        return result


def create_openai_client(
    api_key: str,
    model: str = "gpt-4o-mini",
    max_tokens: int = 1000,
    **kwargs,
) -> OpenAIClient:
    return OpenAIClient(api_key, model, max_tokens, **kwargs)


def generate_answer_from_context(
    context: Dict[str, Any],
    user_query: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    max_tokens: int = 1000,
) -> str:
    client = OpenAIClient(api_key, model, max_tokens)
    return client.generate_answer(context, user_query).content
