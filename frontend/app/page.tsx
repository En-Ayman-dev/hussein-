"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { ChatMessage } from "@/components/chat-message";
import { TypingIndicator } from "@/components/typing-indicator";
import { getChatApiUrl, getChatWithoutAiApiUrl } from "@/lib/api";

const MAX_QUESTION_LENGTH = 500;
const CHAT_ENDPOINTS = {
  ai: getChatApiUrl(),
  without_ai: getChatWithoutAiApiUrl(),
} as const;
const RESPONSE_MODE_OPTIONS = [
  { value: "ai", label: "AI" },
  { value: "without_ai", label: "بدون AI" },
] as const;

type ResponseMode = keyof typeof CHAT_ENDPOINTS;

const MODE_CONTENT: Record<
  ResponseMode,
  {
    headerDescription: string;
    insightHint: string;
    placeholder: string;
    suggestedQuestions: string[];
    welcomeBody: string[];
  }
> = {
  ai: {
    headerDescription: "إجابة تحليلية أوسع تربط بين المفهوم والواقع والموقف العملي.",
    insightHint: "بعد إرسال السؤال ستظهر هنا الخلاصة العملية والعلاقات والاقتباسات المؤسسة.",
    placeholder: "اكتب سؤالك هنا... يمكنك الجمع بين التعريف والموقف العملي في سؤال واحد.",
    suggestedQuestions: [
      "ما هو كتاب الله، وكيف نتبعه؟",
      "كيف يبني القرآن وعي الأمة في مواجهة التضليل؟",
      "ما الفرق بين الأمة الوسط وبين التخفيف في الدين؟",
    ],
    welcomeBody: [
      "• هذا المسار يقدم جواباً تحليلياً أوسع، لكنه يظل مقيداً بالنصوص والعلاقات الموجودة في قاعدة المعرفة.",
      "• يمكنك طرح سؤال مباشر أو سؤال مركب يجمع بين المعنى والموقف العملي.",
      "• ستظهر لك الخلاصة والاقتباسات والعلاقات المهمة بدون أي رموز تقنية.",
    ],
  },
  without_ai: {
    headerDescription: "إجابة مبنية مباشرة على المطابقة والعلاقات والقوالب المحلية داخل القاعدة.",
    insightHint: "بعد إرسال السؤال ستظهر هنا الخلاصة المباشرة للمفهوم كما تستخرجها القاعدة نفسها.",
    placeholder: "اكتب سؤالك هنا... الأفضل أن يكون واضحاً ومباشراً حول مفهوم أو سبب أو حل.",
    suggestedQuestions: [
      "ما هو القرآن؟",
      "ما معنى الأمة الوسط؟",
      "ما هي قسوة القلب؟",
    ],
    welcomeBody: [
      "• هذا المسار يعتمد على القاعدة مباشرة ولا يستخدم التوليد عبر OpenAI.",
      "• يعمل أفضل مع الأسئلة الواضحة والمفاهيم المباشرة والأسئلة عن السبب أو الحل.",
      "• ستظهر لك الخلاصة والعلاقات والاقتباسات المؤسسة فقط.",
    ],
  },
};

const SUMMARY_STOP_WORDS = new Set([
  "ما",
  "ماذا",
  "هو",
  "هي",
  "كيف",
  "لماذا",
  "لما",
  "هل",
  "عن",
  "في",
  "من",
  "على",
  "الى",
  "إلى",
  "ثم",
  "و",
  "أو",
  "او",
  "أن",
  "إن",
  "هذا",
  "هذه",
]);

const STRUCTURAL_SECTION_TITLES = new Set([
  "الخلاصة",
  "التعريف",
  "اقتباس",
  "اقتباسات",
  "اقتباسات مؤسسة",
  "النص التأسيسي",
  "التحليل",
  "الموقف العملي",
  "المطلوب عملياً",
  "المصطلحات ذات الصلة",
  "روابط مهمة",
  "الأسباب",
  "المشكلة المقابلة",
  "الحلول والطرق",
  "الإجراءات المقترحة",
  "حلول إضافية",
  "المقارنة",
  "المقارنة والاختلافات",
  "الاختلافات الرئيسية",
]);

type ApiConcept = {
  actions: string[];
  confidence: number;
  definition: string[];
  importance?: string[];
  labels: string[];
  quote: string[];
  uri: string;
};

type ApiRelationDetail = {
  source_label?: string | null;
  summary?: string | null;
  target_label?: string | null;
  type: string;
  type_label?: string | null;
};

type ChatApiResponse = {
  answer: string;
  confidence: number;
  intent: string;
  matched_concept?: string | null;
  method: string;
  mode: ResponseMode | string;
  processing_time: number;
  quote?: string | null;
  relation_details?: ApiRelationDetail[];
  relations: string[];
  sources: string[];
  token_usage?: Record<string, unknown> | null;
  top_concepts: ApiConcept[];
  top_quotes: string[];
  validation_score: number;
};

type Message = {
  id: string;
  isAnimating?: boolean;
  sender: "user" | "assistant";
  text: string;
};

type DisplayRelation = {
  target?: string;
  text: string;
};

type InsightView = {
  actions: string[];
  definition: string | null;
  quotes: string[];
  relatedTerms: string[];
  relationItems: string[];
  summary: string | null;
  title: string | null;
};

type PresentationModel = {
  insight: InsightView | null;
  message: string;
};

function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function createWelcomeMessage(mode: ResponseMode): Message {
  const content = MODE_CONTENT[mode];

  return {
    id: "welcome",
    sender: "assistant",
    text: [
      `**${mode === "ai" ? "وضع AI" : "وضع بدون AI"}**`,
      `**كيف سيظهر لك الجواب؟**\n${content.welcomeBody.join("\n")}`,
    ].join("\n\n"),
  };
}

function sanitizeText(value: string): string {
  return value.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

function isUriLike(value: string): boolean {
  return /^https?:\/\//i.test(value) || value.includes("#");
}

function isInternalCode(value: string): boolean {
  return /^(?:[A-Z]\d+[_-][A-Z0-9_-]+|F\d+[_-][A-Z0-9_-]+)$/i.test(value);
}

function normalizeDisplayValue(value: string | null | undefined): string | null {
  const trimmed = sanitizeText((value || "").replace(/^"+|"+$/g, ""));
  if (!trimmed || isUriLike(trimmed) || isInternalCode(trimmed)) {
    return null;
  }

  return trimmed;
}

function uniqueValues(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  for (const value of values) {
    const normalized = normalizeDisplayValue(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }

    seen.add(normalized);
    result.push(normalized);
  }

  return result;
}

function normalizeComparisonText(value: string): string {
  return sanitizeText(value)
    .replace(/[*_`>#~]/g, " ")
    .replace(/[•\-]/g, " ")
    .replace(/[؟?!،,:؛/()[\]{}"'“”]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function meaningfulTokens(value: string): string[] {
  return normalizeComparisonText(value)
    .split(" ")
    .filter((token) => token.length > 1 && !SUMMARY_STOP_WORDS.has(token));
}

function isTooSimilarToQuestion(candidate: string, question: string): boolean {
  const normalizedCandidate = normalizeComparisonText(candidate);
  const normalizedQuestion = normalizeComparisonText(question);

  if (!normalizedCandidate || !normalizedQuestion) {
    return false;
  }

  if (normalizedCandidate === normalizedQuestion) {
    return true;
  }

  const candidateTokens = meaningfulTokens(normalizedCandidate);
  const questionTokens = meaningfulTokens(normalizedQuestion);
  if (candidateTokens.length === 0 || questionTokens.length === 0) {
    return false;
  }

  const questionTokenSet = new Set(questionTokens);
  const overlap = candidateTokens.filter((token) => questionTokenSet.has(token)).length;
  return overlap / Math.max(Math.min(candidateTokens.length, questionTokens.length), 1) >= 0.85;
}

function trimSummary(value: string, maxLength = 340): string {
  const cleaned = sanitizeText(value);
  if (cleaned.length <= maxLength) {
    return cleaned;
  }

  return `${cleaned.slice(0, maxLength).trimEnd()}...`;
}

function toPlainLine(value: string): string {
  let cleaned = sanitizeText(value)
    .replace(/^>\s*/g, "")
    .replace(/^[-•]\s*/g, "")
    .replace(/^\*\*(.*?)\*\*:?\s*$/g, "$1")
    .replace(/\*\*/g, "")
    .trim();

  cleaned = normalizeComparisonText(cleaned);
  return cleaned;
}

function extractSummaryCandidate(
  answer: string,
  question: string,
  primaryLabel: string | null,
): string | null {
  const lines = sanitizeText(answer)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const summaryLines: string[] = [];

  for (const rawLine of lines) {
    if (rawLine.startsWith(">")) {
      continue;
    }

    const plainLine = toPlainLine(rawLine);
    if (!plainLine) {
      continue;
    }

    if (STRUCTURAL_SECTION_TITLES.has(plainLine)) {
      continue;
    }

    if (primaryLabel && normalizeComparisonText(primaryLabel) === plainLine) {
      continue;
    }

    if (isTooSimilarToQuestion(plainLine, question)) {
      continue;
    }

    summaryLines.push(plainLine);
    if (summaryLines.length >= 2) {
      break;
    }
  }

  if (summaryLines.length === 0) {
    return null;
  }

  return trimSummary(summaryLines.join(" "));
}

function buildFallbackSummary(
  definition: string | null,
  relatedTerms: string[],
  relationItems: string[],
  actions: string[],
): string | null {
  const parts: string[] = [];

  if (definition) {
    parts.push(definition);
  }

  if (actions.length > 0) {
    parts.push(`والموقف العملي المتصل به هو: ${actions[0]}`);
  } else if (relationItems.length > 0) {
    parts.push(`ويرتبط في السياق بـ ${relationItems.slice(0, 2).join("، ")}.`);
  } else if (relatedTerms.length > 0) {
    parts.push(`ويرتبط أيضاً بمفاهيم مثل: ${relatedTerms.slice(0, 3).join("، ")}.`);
  }

  if (parts.length === 0) {
    return null;
  }

  return trimSummary(parts.join(" "));
}

function toRelationKey(rawType: string): string {
  return rawType
    .trim()
    .replace(/([a-z])([A-Z])/g, "$1_$2")
    .replace(/[\s-]+/g, "_")
    .toUpperCase();
}

function humanizeRelationType(rawType: string): string {
  const mapping: Record<string, string> = {
    BELONGS_TO_COLLECTION: "يندرج ضمن سلسلة",
    BELONGS_TO_GROUP: "يندرج تحت",
    BELONGS_TO_LESSON: "ينتمي إلى درس",
    CAUSES: "يسبب",
    ESTABLISHES: "يرسخ",
    IS_CAUSED_BY: "ينتج عن",
    IS_CONDITION_FOR: "شرط لـ",
    IS_MEANS_FOR: "يمهد إلى",
    NEGATES: "ينفي",
    OPPOSES: "يعارض",
    PRECEDES: "يسبق",
    RELATED_TO: "يرتبط بـ",
  };

  return mapping[toRelationKey(rawType)] || "يرتبط بـ";
}

function parseRelationSummary(
  summary: string,
  primaryLabel: string | null,
): DisplayRelation | null {
  const match = summary.match(/^([^:]+):\s*(.*?)\s*->\s*(.*?)$/);
  if (!match) {
    return null;
  }

  const [, rawType, rawSource, rawTarget] = match;
  const source = normalizeDisplayValue(rawSource);
  const target = normalizeDisplayValue(rawTarget);
  const relationVerb = humanizeRelationType(rawType);

  if (!source && !target) {
    return null;
  }

  if (primaryLabel && source === primaryLabel && target) {
    return { target, text: `${relationVerb} ${target}` };
  }

  if (primaryLabel && target === primaryLabel && source) {
    return { target: source, text: `${source} ${relationVerb}` };
  }

  if (source && target) {
    return { target, text: `${source} ${relationVerb} ${target}` };
  }

  if (target) {
    return { target, text: `${relationVerb} ${target}` };
  }

  return { target: source || undefined, text: `${source} ${relationVerb}` };
}

function buildRelationFromDetail(
  detail: ApiRelationDetail,
  primaryLabel: string | null,
): DisplayRelation | null {
  const source = normalizeDisplayValue(detail.source_label);
  const target = normalizeDisplayValue(detail.target_label);
  const summary = normalizeDisplayValue(detail.summary);
  const relationVerb =
    normalizeDisplayValue(detail.type_label) || humanizeRelationType(detail.type);

  if (summary) {
    return { target: target || source || undefined, text: summary };
  }

  if (!source && !target) {
    return null;
  }

  if (primaryLabel && source === primaryLabel && target) {
    return { target, text: `${relationVerb} ${target}` };
  }

  if (primaryLabel && target === primaryLabel && source) {
    return { target: source, text: `${source} ${relationVerb}` };
  }

  if (source && target) {
    return { target, text: `${source} ${relationVerb} ${target}` };
  }

  if (target) {
    return { target, text: `${relationVerb} ${target}` };
  }

  return { target: source || undefined, text: `${source} ${relationVerb}` };
}

function isAnswerHelpful(answer: string): boolean {
  const normalized = answer.trim();
  if (!normalized) {
    return false;
  }

  return ![
    "Connection error",
    "حدث خطأ",
    "عذراً، حدث خطأ",
  ].some((fragment) => normalized.includes(fragment));
}

function pickPrimaryConcept(concepts: ApiConcept[]): ApiConcept | null {
  if (concepts.length === 0) {
    return null;
  }

  const scored = [...concepts].sort((left, right) => {
    const leftScore =
      (normalizeDisplayValue(left.labels[0]) ? 3 : 0) +
      (normalizeDisplayValue(left.definition[0]) ? 2 : 0) +
      (normalizeDisplayValue(left.quote[0]) ? 1 : 0) +
      left.confidence;
    const rightScore =
      (normalizeDisplayValue(right.labels[0]) ? 3 : 0) +
      (normalizeDisplayValue(right.definition[0]) ? 2 : 0) +
      (normalizeDisplayValue(right.quote[0]) ? 1 : 0) +
      right.confidence;

    return rightScore - leftScore;
  });

  return scored[0] || null;
}

function buildPresentation(response: ChatApiResponse, question: string): PresentationModel {
  const cleanedAnswer = sanitizeText(response.answer || "");
  if (response.top_concepts.length === 0) {
    return {
      insight: null,
      message: cleanedAnswer || "لم أجد نتيجة مناسبة لهذا السؤال في البيانات الحالية.",
    };
  }

  const primaryConcept = pickPrimaryConcept(response.top_concepts);
  const primaryLabel = primaryConcept ? uniqueValues(primaryConcept.labels)[0] || null : null;
  const primaryDefinition = primaryConcept ? uniqueValues(primaryConcept.definition)[0] || null : null;
  const primaryActions = primaryConcept ? uniqueValues(primaryConcept.actions).slice(0, 3) : [];

  const detailRelations = (response.relation_details || [])
    .map((detail) => buildRelationFromDetail(detail, primaryLabel))
    .filter((relation): relation is DisplayRelation => Boolean(relation));

  const parsedRelations =
    detailRelations.length > 0
      ? detailRelations
      : response.relations
          .map((relation) => parseRelationSummary(relation, primaryLabel))
          .filter((relation): relation is DisplayRelation => Boolean(relation));

  const relationItems = uniqueValues(parsedRelations.map((relation) => relation.text)).slice(0, 5);
  const relatedTerms = uniqueValues([
    ...parsedRelations.map((relation) => relation.target),
    ...response.top_concepts.flatMap((concept) => concept.labels),
  ])
    .filter((label) => label !== primaryLabel)
    .slice(0, 6);

  const quotes = uniqueValues([
    response.quote,
    ...response.top_quotes,
    ...(primaryConcept ? primaryConcept.quote : []),
  ]).slice(0, 4);
  const summary =
    (isAnswerHelpful(cleanedAnswer)
      ? extractSummaryCandidate(cleanedAnswer, question, primaryLabel)
      : null) ||
    buildFallbackSummary(primaryDefinition, relatedTerms, relationItems, primaryActions);

  const fallbackSections: string[] = [];
  if (primaryLabel) {
    fallbackSections.push(`**${primaryLabel}**`);
  }

  if (summary) {
    fallbackSections.push(`**الخلاصة:**\n${summary}`);
  }

  if (primaryDefinition) {
    fallbackSections.push(`**التعريف:**\n• ${primaryDefinition}`);
  }

  if (primaryActions.length > 0) {
    fallbackSections.push(
      `**المطلوب عملياً:**\n${primaryActions.map((action) => `• ${action}`).join("\n")}`,
    );
  }

  if (relatedTerms.length > 0) {
    fallbackSections.push(
      `**المصطلحات ذات الصلة:**\n${relatedTerms.map((term) => `• ${term}`).join("\n")}`,
    );
  }

  if (relationItems.length > 0) {
    fallbackSections.push(
      `**روابط مهمة:**\n${relationItems.map((item) => `• ${item}`).join("\n")}`,
    );
  }

  if (quotes.length > 0) {
    fallbackSections.push(`**اقتباسات مؤسسة:**\n${quotes.map((quote) => `> ${quote}`).join("\n\n")}`);
  }

  if (fallbackSections.length === 0) {
    fallbackSections.push(cleanedAnswer || "تعذر تكوين عرض مناسب من البيانات المتاحة حالياً.");
  }

  const fallbackMessage = fallbackSections.join("\n\n");
  const shouldShowAnswerDirectly = isAnswerHelpful(cleanedAnswer);

  return {
    insight: {
      actions: primaryActions,
      definition: primaryDefinition,
      quotes,
      relatedTerms,
      relationItems,
      summary,
      title: primaryLabel,
    },
    message: shouldShowAnswerDirectly ? cleanedAnswer : fallbackMessage,
  };
}

export default function HomePage() {
  const [responseMode, setResponseMode] = useState<ResponseMode>("ai");
  const modeContent = MODE_CONTENT[responseMode];
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Message[]>(() => [createWelcomeMessage("ai")]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isReplyAnimating, setIsReplyAnimating] = useState(false);
  const [activeInsight, setActiveInsight] = useState<InsightView | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const typingTimersRef = useRef<number[]>([]);
  const copyTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [isSubmitting, messages]);

  useEffect(() => {
    return () => {
      typingTimersRef.current.forEach((timer) => window.clearTimeout(timer));
      if (copyTimerRef.current) {
        window.clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    setMessages((current) => {
      if (current.length === 0 || current[0]?.id !== "welcome") {
        return current;
      }

      const nextWelcome = createWelcomeMessage(responseMode);
      if (current[0].text === nextWelcome.text) {
        return current;
      }

      return [nextWelcome, ...current.slice(1)];
    });
  }, [responseMode]);

  function clearTypingTimers() {
    typingTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    typingTimersRef.current = [];
  }

  function animateAssistantMessage(messageId: string, fullText: string) {
    clearTypingTimers();
    setIsReplyAnimating(true);

    const chunkSize = fullText.length > 900 ? 8 : fullText.length > 450 ? 5 : 3;
    const delay = fullText.length > 900 ? 16 : 22;
    let cursor = 0;

    const tick = () => {
      cursor = Math.min(fullText.length, cursor + chunkSize);
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? { ...message, isAnimating: cursor < fullText.length, text: fullText.slice(0, cursor) }
            : message,
        ),
      );

      if (cursor < fullText.length) {
        const nextTimer = window.setTimeout(tick, delay);
        typingTimersRef.current.push(nextTimer);
      } else {
        setIsReplyAnimating(false);
      }
    };

    const initialTimer = window.setTimeout(tick, 120);
    typingTimersRef.current.push(initialTimer);
  }

  async function copyText(messageId: string, text: string) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.setAttribute("readonly", "");
        helper.style.position = "absolute";
        helper.style.left = "-9999px";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        document.body.removeChild(helper);
      }

      setCopiedMessageId(messageId);
      if (copyTimerRef.current) {
        window.clearTimeout(copyTimerRef.current);
      }
      copyTimerRef.current = window.setTimeout(() => setCopiedMessageId(null), 1600);
    } catch {
      setCopiedMessageId(null);
    }
  }

  async function sendQuestion(question: string) {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || isSubmitting || isReplyAnimating) {
      return;
    }

    const userMessageId = createId("user");
    setDraft("");
    setIsSubmitting(true);
    setMessages((current) => [
      ...current,
      { id: userMessageId, sender: "user", text: trimmedQuestion },
    ]);

    try {
      const response = await fetch(CHAT_ENDPOINTS[responseMode], {
        body: JSON.stringify({
          max_depth: 2,
          max_relations: 8,
          question: trimmedQuestion,
          use_embeddings: false,
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });

      const payload = (await response.json()) as ChatApiResponse | { detail?: string };
      if (!response.ok) {
        const detail =
          "detail" in payload && payload.detail ? payload.detail : "تعذر الوصول إلى خدمة المحادثة الآن.";
        throw new Error(detail);
      }

      const presentation = buildPresentation(payload as ChatApiResponse, trimmedQuestion);
      const assistantMessageId = createId("assistant");
      setActiveInsight(presentation.insight);
      setMessages((current) => [
        ...current,
        {
          id: assistantMessageId,
          isAnimating: true,
          sender: "assistant",
          text: "",
        },
      ]);
      animateAssistantMessage(assistantMessageId, presentation.message);
    } catch (error) {
      const assistantMessageId = createId("assistant");
      const errorMessage =
        error instanceof Error
          ? `**تعذر إكمال الطلب الآن**\n${sanitizeText(error.message)}`
          : "**تعذر إكمال الطلب الآن**\nحدث خطأ غير متوقع أثناء الاتصال بالخادم.";

      setActiveInsight(null);
      setMessages((current) => [
        ...current,
        {
          id: assistantMessageId,
          isAnimating: true,
          sender: "assistant",
          text: "",
        },
      ]);
      animateAssistantMessage(assistantMessageId, errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendQuestion(draft);
  }

  return (
    <main className="h-[100dvh] overflow-hidden p-3 sm:p-4">
      <div className="mx-auto grid h-full max-w-7xl gap-4 grid-rows-[minmax(0,1fr)_240px] lg:grid-cols-[minmax(0,1fr)_340px] lg:grid-rows-1">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-[30px] border border-white/75 bg-white/82 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/80 px-5 py-4">
            <div>
              <h1 className="text-xl font-semibold text-slate-950">المحادثة</h1>
              <p className="mt-1 text-sm text-slate-500">
                {modeContent.headerDescription}
              </p>
            </div>

            <div className="inline-flex rounded-full border border-slate-200 bg-slate-100/90 p-1">
              {RESPONSE_MODE_OPTIONS.map((option) => {
                const isActive = responseMode === option.value;

                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={isActive}
                    onClick={() => setResponseMode(option.value)}
                    disabled={isSubmitting || isReplyAnimating}
                    className={[
                      "rounded-full px-4 py-2 text-sm font-medium transition",
                      isActive
                        ? "bg-white text-slate-950 shadow-sm"
                        : "text-slate-500 hover:text-slate-800",
                      isSubmitting || isReplyAnimating ? "cursor-not-allowed opacity-60" : "",
                    ].join(" ")}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </header>

          <div
            ref={scrollContainerRef}
            className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-5"
          >
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {messages.map((message) => (
                <div key={message.id} className="animate-[floatIn_0.35s_ease-out]">
                  <ChatMessage
                    copyLabel={copiedMessageId === message.id ? "تم النسخ" : "نسخ"}
                    isAnimating={message.isAnimating}
                    onCopy={
                      message.sender === "assistant"
                        ? () => void copyText(message.id, message.text)
                        : undefined
                    }
                    sender={message.sender}
                    text={message.text}
                  />
                </div>
              ))}

              {isSubmitting ? <TypingIndicator /> : null}
            </div>
          </div>

          <div className="border-t border-slate-200/80 bg-white/88 px-4 py-4 sm:px-5">
            <div className="mb-3 flex flex-wrap gap-2">
              {modeContent.suggestedQuestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => void sendQuestion(question)}
                  disabled={isSubmitting || isReplyAnimating}
                  className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 transition hover:border-sky-300 hover:text-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {question}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="space-y-3">
              <label htmlFor="chat-question" className="sr-only">
                اكتب سؤالك
              </label>
              <textarea
                id="chat-question"
                value={draft}
                onChange={(event) => setDraft(event.target.value.slice(0, MAX_QUESTION_LENGTH))}
                placeholder={modeContent.placeholder}
                disabled={isSubmitting || isReplyAnimating}
                className="min-h-24 w-full resize-none rounded-[24px] border border-slate-200 bg-slate-50/80 px-5 py-4 text-[15px] leading-8 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-sky-300 focus:bg-white focus:ring-4 focus:ring-sky-100"
              />
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={!draft.trim() || isSubmitting || isReplyAnimating}
                  className="inline-flex items-center justify-center rounded-full bg-[linear-gradient(135deg,#0f172a,#0369a1)] px-6 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isSubmitting
                    ? "جارٍ تحليل السؤال..."
                    : isReplyAnimating
                      ? "الرد قيد الكتابة..."
                      : "إرسال السؤال"}
                </button>
              </div>
            </form>
          </div>
        </section>

        <aside className="min-h-0 overflow-hidden rounded-[30px] border border-white/75 bg-white/82 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl">
          <div className="flex h-full min-h-0 flex-col">
            <header className="border-b border-slate-200/80 px-5 py-4">
              <h2 className="text-base font-semibold text-slate-950">خلاصة المفهوم</h2>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
              {activeInsight ? (
                <div className="space-y-5">
                  {activeInsight.summary ? (
                    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-4">
                      <p className="text-sm font-semibold text-slate-900">الخلاصة</p>
                      <p className="mt-2 text-sm leading-8 text-slate-700">{activeInsight.summary}</p>
                    </div>
                  ) : null}

                  <div>
                    <h3 className="text-2xl font-semibold text-slate-950">
                      {activeInsight.title || "نتيجة البحث"}
                    </h3>
                    {activeInsight.definition ? (
                      <p className="mt-3 text-sm leading-8 text-slate-600">
                        {activeInsight.definition}
                      </p>
                    ) : (
                      <p className="mt-3 text-sm leading-8 text-slate-500">
                        لا يوجد تعريف نصي أوضح لهذا المفهوم في البيانات الحالية.
                      </p>
                    )}
                  </div>

                  <div>
                    <p className="text-sm font-semibold text-slate-900">المطلوب عملياً</p>
                    {activeInsight.actions.length > 0 ? (
                      <ul className="mt-3 space-y-2 text-sm leading-7 text-slate-600">
                        {activeInsight.actions.map((action) => (
                          <li
                            key={action}
                            className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3"
                          >
                            {action}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-sm text-slate-500">
                        لا يوجد توجيه عملي صريح لهذا المفهوم في هذه النتيجة.
                      </p>
                    )}
                  </div>

                  <div>
                    <p className="text-sm font-semibold text-slate-900">مصطلحات مرتبطة</p>
                    {activeInsight.relatedTerms.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {activeInsight.relatedTerms.map((term) => (
                          <span
                            key={term}
                            className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-700"
                          >
                            {term}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-2 text-sm text-slate-500">
                        لا توجد مصطلحات إضافية صالحة للعرض في هذه النتيجة.
                      </p>
                    )}
                  </div>

                  <div>
                    <p className="text-sm font-semibold text-slate-900">علاقات مهمة</p>
                    {activeInsight.relationItems.length > 0 ? (
                      <ul className="mt-3 space-y-2 text-sm leading-7 text-slate-600">
                        {activeInsight.relationItems.map((item) => (
                          <li
                            key={item}
                            className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3"
                          >
                            {item}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-sm text-slate-500">
                        لا توجد علاقات مهمة صالحة للعرض في هذه الاستجابة.
                      </p>
                    )}
                  </div>

                  <div>
                    <p className="text-sm font-semibold text-slate-900">اقتباسات</p>
                    {activeInsight.quotes.length > 0 ? (
                      <div className="mt-3 space-y-3">
                        {activeInsight.quotes.map((quote) => (
                          <blockquote
                            key={quote}
                            className="rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-4 text-sm leading-8 text-slate-700"
                          >
                            {quote}
                          </blockquote>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-2 text-sm text-slate-500">
                        لا توجد اقتباسات متاحة لهذا المفهوم حالياً.
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-sm leading-8 text-slate-500">
                  {modeContent.insightHint}
                </p>
              )}
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}
