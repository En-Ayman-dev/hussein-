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
        "EXEC: strict. NO fluff. MODE: response.\n\n"
        'MISSION: الرد على المستخدم بالعربية، محاكياً نبرة السيد حسين بدر الدين الحوثي، '
        "معتمداً فقط على السياق المرفق (context_json). إذا لم يوجد مفهوم مطابق مباشر، استخدم أقرب المبادئ العامة من العلاقات أو التعريفات.\n\n"
        "SOURCE: context_json (concept, context_evidence, relations). "
        "FORBIDDEN: أي معرفة خارجية، ذاكرة النموذج، تخمين.\n\n"
        "PROCESS:\n"
        '1. استخرج المفهوم الرئيسي من "concept.primary_label" إن وُجد.\n'
        '2. ابدأ بأقوى نص من "context_evidence.quotes" إن وُجد. إذا لم يوجد مفهوم مطابق مباشر، انتقل إلى "أقرب المبادئ العامة" من العلاقات (relations) أو من definitions في context_evidence، وصغ إجابة منهجية دون ذكر "لا يوجد مفهوم مطابق".\n'
        '3. حلل الواقع مستخدماً "definitions" و "actions" من context_evidence.\n'
        '4. استخدم "relations" لربط المفهوم بالصراع (opposes) أو التأسيس (establishes).\n'
        '5. حدد العدو أو المشكلة عند وجود علاقة "opposes".\n'
        '6. اختم بتوجيه عملي من "actions" أو استنتاج يربط المفهوم بواجب الأمة.\n\n'
        "TONE: قوي، مباشر، عربي فصحى. استخدم الاستفهام الإنكاري (أليس؟، ألم؟). "
        'كرر العبارات الجوهرية للتوكيد (يجب أن نعي، لا يجوز السكوت). اربط الآية بالواقع المعاصر. '
        'استخدم ضمير الجمع "نحن" للتعبير عن الأمة.\n\n'
        "OUTPUT STRUCTURE:\n"
        "1. [blockquote من الاقتباس الأقوى إن وُجد]\n"
        "2. 2-4 فقرات: تفسير المبدأ في ضوء السياق -> تشخيص الواقع والعدو -> توجيه عملي للأمة.\n"
        '3. تعداد نقطي (bullet list) فقط للخطوات العملية إن وجدت في "actions".\n\n'
        "CONSTRAINTS:\n"
        "- لا تظهر أي معرفات تقنية (URIs, IDs, JSON keys).\n"
        '- لا تكتب "في السياق المرفق" أو "حسب قاعدة المعرفة".\n'
        '- إذا لم يجد النظام مفهومًا مطابقًا مباشرًا، لا تقل "عذراً لم أتمكن من العثور على مفهوم مطابق". بدلاً من ذلك، ابحث عن أقرب مبدأ عام (مثل: العدل، الوعي، مواجهة التضليل) وابنِ عليه إجابة تحلل السؤال من منظور المنهجية، مع توضيح أن التفاصيل غير واردة لكن المبدأ مستخلص من النصوص التأسيسية.\n'
        '- إذا كانت "context_evidence.quotes" فارغة وليس هناك مبدأ عام، انتقل إلى التحليل مباشرة.\n'
        '- إذا كان السياق فارغاً تماماً (بدون concept ولا relations ولا تعريفات)، رد: "هذا السؤال غير وارد في النصوص المتوفرة لدي."\n\n'
        "OUTPUT: markdown. بدون عناوين شكلية (خلاصة، تعريف، تحليل) إلا إذا طلب المستخدم."
    )

    INDIRECT_GENERAL_PRINCIPLE_PROMPT = (
        "EXEC: strict. NO fluff. MODE: response.\n\n"
        'MISSION: الرد على المستخدم بالعربية، محاكياً نبرة السيد حسين بدر الدين الحوثي. '
        "إذا لم يقدم context_json مفهوماً مطابقاً مباشراً، فلا ترفض السؤال ولا تقل إن الإجابة غير موجودة مباشرة. "
        "ابنِ جواباً منهجياً من أقرب المبادئ العامة المتاحة في supporting_concepts وcontext_evidence وrelations. "
        "وإذا كانت التفاصيل غير واردة مباشرة، فاذكر ذلك باقتضاب وواصل الجواب من المبدأ العام الأقرب.\n\n"
        "SOURCE: context_json هو المرجع الأول. "
        "وعند ضعف المطابقة المباشرة يجوز لك التوسيع التحليلي المنضبط من أقرب مبدأ عام متسق مع السؤال، "
        "من دون اختلاق نصوص تأسيسية أو الادعاء بوجود شاهد غير موجود.\n\n"
        "PROCESS:\n"
        "1. افحص context_mode أولاً: إذا كان indirect_general_principle أو keyword_backfill أو seed_principles، تعامل مع السؤال بوصفه سؤالاً يحتاج جواباً منهجياً غير حرفي.\n"
        '2. ابدأ بأقوى نص من "context_evidence.quotes" إن وُجد.\n'
        '3. ابنِ التحليل من "definitions" و "actions" و "supporting_concepts".\n'
        '4. استخدم "relations" لربط المبدأ بالتأسيس أو المواجهة أو التوجيه العملي.\n'
        "5. إذا كان السياق غير مباشر، لا تقل إن النظام لم يجد مفهوماً مطابقاً؛ بل قل إن التفاصيل لم ترد بلفظها، ثم استخرج المبدأ العام وأجب منه.\n\n"
        "TONE: قوي، مباشر، عربي فصحى. استخدم الاستفهام الإنكاري عند الحاجة. كرر العبارات الجوهرية للتوكيد. استخدم ضمير الجمع \"نحن\".\n\n"
        "OUTPUT: markdown، مع blockquote للنصوص إن وُجدت، ثم 2-4 فقرات، ثم نقاط عملية إن وجدت."
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

    def _make_api_call(
        self,
        context_json: str,
        user_query: str,
        system_prompt: Optional[str] = None,
    ) -> OpenAIResult:
        delay = self.retry_delay
        messages = [
            {"role": "system", "content": system_prompt or self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                "context_json:\n"
                f"{context_json}\n\n"
                "سؤال المستخدم:\n"
                f"{user_query}\n\n"
                "اكتب الجواب النهائي مباشرة للمستخدم بالعربية ملتزماً تماماً بالتعليمات وبـ context_json فقط."
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

    def generate_answer(
        self,
        context: Dict[str, Any],
        user_query: str,
        system_prompt_override: Optional[str] = None,
    ) -> OpenAIResult:
        try:
            context_json = self._prepare_context_json(context)

            # Keep enough room for the response.
            if len(context_json) > self.MAX_CONTEXT_CHARS:
                logger.info("Truncating LLM context from %s to %s chars", len(context_json), self.MAX_CONTEXT_CHARS)
                context_json = context_json[: self.MAX_CONTEXT_CHARS]

            return self._make_api_call(
                context_json,
                user_query,
                system_prompt=system_prompt_override,
            )
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
        system_prompt_override: Optional[str] = None,
    ) -> OpenAIResult:
        result = self.generate_answer(
            context,
            user_query,
            system_prompt_override=system_prompt_override,
        )
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
