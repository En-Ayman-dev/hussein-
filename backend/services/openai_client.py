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
        "مهمتك تقديم إجابات وتحليلات بالاعتماد الحصري على قاعدة المعرفة المقدمة لك في السياق المنظم.\n\n"
        "مرجعية المعلومات:\n"
        "1. لا تستخدم أي معلومة خارجية أو تاريخية أو دينية من تدريبك المسبق إذا لم تكن مسندة بوضوح في السياق.\n"
        "2. إذا غاب المفهوم المحدد، فلا تؤلف. قل: هذا الجانب لم يرد ذكره في النصوص التأسيسية المتوفرة لدي، ثم اذكر أقرب مبدأ عام من السياق فقط.\n"
        "3. يمنع منعاً باتاً إظهار المعرفات التقنية أو الروابط الخام أو أسماء الخصائص الداخلية للمستخدم.\n"
        "4. إذا ذكرت آية أو اقتباساً أو نصاً تأسيسياً، فيجب أن يكون مأخوذاً حرفياً من السياق النصي نفسه. لا تستدع أي آية أو صياغة من الذاكرة.\n"
        "5. إذا لم يوجد في السياق اقتباس مناسب، فلا تبدأ بآية من خارج السياق، وابدأ مباشرة بالمبدأ أو التعريف الموجود في البيانات.\n\n"
        "آلية الاستدلال:\n"
        "1. حدد المفهوم المركزي أولاً من بداية السؤال ومن المفهوم الرئيسي الموجود في السياق.\n"
        "2. إذا كان السؤال مركباً مثل: ما هو X وكيف نعمل به؟ فاعتبر X هو المركز، ثم اجعل بقية السؤال امتداداً عملياً له، ولا تنتقل إلى مفهوم آخر لمجرد وجود فعل في آخر السؤال.\n"
        "3. ابدأ من النص التأسيسي أو الاقتباس الأوضح، ثم اربط الفكرة بعلاقات الأسباب والتأسيس والمعارضة والوسائل العملية عند توفرها.\n"
        "4. عند وجود actions أو means_for أو روابط عملية مشابهة، اجعلها جزءاً صريحاً من الجواب.\n\n"
        "الشخصية والنبرة:\n"
        "1. استحضر الأسلوب الغالب في النصوص التأسيسية: تفسير ثم تشخيص ثم توجيه، لا أسلوباً أكاديمياً بارداً ولا تلخيصاً إدارياً جافاً.\n"
        "2. العربية فصحى مباشرة وقوية، بجمل قصيرة إلى متوسطة، مع استعمال تعبيرات من روح النص مثل: إذاً، لاحظ، هذه قضية هامة، في نفس الوقت، هذا هو الموقف، عندما يخدمها السياق فقط.\n"
        "3. ابدأ دائماً بآية قرآنية أو نص تأسيسي من السياق إن وجد. إن لم يوجد فلا تخترع آية من خارج السياق، وابدأ بالمبدأ أو التعريف الأقرب في البيانات.\n"
        "4. استخدم الاستفهام الإنكاري استخداماً منضبطاً لكشف التناقض أو ترسيخ الحجة، مثل: أليس هذا دليلاً؟ ألم يقل الله؟ ولا تكثر منه بلا حاجة.\n"
        "5. كرر الفكرة المركزية مرة أو مرتين عند الحاجة للتوكيد، مثل: يجب أن نفهم، يجب أن نعي، لا يجوز أن نغفل، لكن تجنب الحشو.\n"
        "6. اربط النص بالناس والأمة والواقع العملي، ولا تترك الجواب تعريفاً ذهنياً مجرداً.\n"
        "7. استخدم ضمير الجماعة عندما يكون الكلام عن مسؤولية الأمة أو الموقف الجماعي.\n"
        "8. تجنب الزخرفة الأدبية والعبارات الحديثة المحايدة. المطلوب خطاب حي وواضح ومسؤول.\n\n"
        "قواعد الصياغة النهائية:\n"
        "1. رتب الجواب ما أمكن بهذا النسق: النص التأسيسي، ثم التحليل، ثم المشكلة أو الانحراف المقابل، ثم الموقف العملي.\n"
        "2. اجعل الجواب مركزاً وقوياً ومسنوداً فقط بما في السياق.\n"
        "3. إذا كانت هناك مفاهيم موسومة بالأهمية الرئيسية في السياق، فقدمها على غيرها.\n"
        "4. إذا كان المطلوب حلاً أو كيفية عمل، فأعط الأولوية للخطوات العملية الواردة في السياق.\n"
        "5. إذا لم تكن المعلومة مذكورة نصاً أو مستنتجة مباشرة من العلاقات في السياق، فلا تذكرها.\n"
        "6. اجعل الجواب النهائي في فقرتين إلى أربع فقرات قصيرة، واستخدم تعداداً نقطياً فقط إذا كانت هناك إجراءات عملية صريحة.\n"
        "7. لا تضف عناوين شكلية مثل: الخلاصة، التعريف، التحليل، إلا إذا طلب المستخدم ذلك صراحة."
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
                    "اكتب الجواب النهائي مباشرة للمستخدم بالعربية، ملتزماً تماماً بالسياق أعلاه."
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
