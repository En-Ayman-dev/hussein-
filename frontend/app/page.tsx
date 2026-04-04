"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

import { ChatMessage } from "@/components/chat-message";
import {
  InsightPanel,
  type InsightQuoteItem,
  type InsightRelationGroup,
  type InsightSectionKey,
  type InsightView,
} from "@/components/insight-panel";
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
      "ما هي آيات الله؟",
      "ما هو التضليل؟",
      "ما هو خبث اليهود؟",
      "ما معنى الثقلين؟",
      "من هم أعلام الهدى؟",
      "ما هي العزة والقوة؟",
      "ما معنى الهدى؟",
      "ما هو الانحراف التاريخي؟",
      "ما هو التقصير؟",
      "ما معنى المسؤولية؟",
      "ما هي البصيرة؟",
      "ما معنى الوعي؟",
      "كيف يواجه المؤمن التضليل؟",
      "ما سبب قسوة القلب؟",
      "كيف نرجع إلى القرآن؟",
    ],
    welcomeBody: [
      "• هذا المسار يعتمد على القاعدة مباشرة ولا يستخدم أي توليد خارجي.",
      "• يعمل أفضل مع الأسئلة الواضحة والمفاهيم المباشرة والأسئلة عن السبب أو الحل.",
      "• ستظهر لك الخلاصة والعلاقات والاقتباسات المؤسسة فقط.",
    ],
  },
};

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
  responseMode?: ResponseMode;
  sender: "user" | "assistant";
  text: string;
};

type DisplayRelation = {
  target?: string;
  text: string;
  typeKey: string;
  typeLabel: string;
};

type PresentationModel = {
  insight: InsightView | null;
  message: string;
};

type EmptyChatStateProps = {
  mode: ResponseMode;
};

type MobilePanel = "chat" | "insight";

function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeResponseMode(value: string | null | undefined): ResponseMode | null {
  return value === "ai" || value === "without_ai" ? value : null;
}

function buildRelationFollowUpQuestion(
  conceptTitle: string | null,
  relation: DisplayRelation,
): string {
  const concept = conceptTitle || "هذا المفهوم";
  const target = relation.target || relation.text;

  switch (relation.typeKey) {
    case "IS_MEANS_FOR":
      return `كيف يكون ${target} وسيلة مرتبطة بـ ${concept}؟`;
    case "CAUSES":
    case "IS_CAUSED_BY":
      return `ما علاقة ${concept} بـ ${target} من جهة السبب والنتيجة؟`;
    case "OPPOSES":
      return `ما الفرق بين ${concept} و${target}؟`;
    case "ESTABLISHES":
      return `كيف يرتبط ${concept} بـ ${target} في التأسيس والمعنى؟`;
    case "NEGATES":
      return `ما الذي ينفيه ${concept} في سياق ${target}؟`;
    default:
      return `ما علاقة ${concept} بـ ${target}؟`;
  }
}

function buildQuoteFollowUpQuestion(
  conceptTitle: string | null,
  quote: InsightQuoteItem,
): string {
  const concept = conceptTitle || "هذا المفهوم";

  if (quote.label && quote.label !== "اقتباس" && quote.label !== concept) {
    return `ما دلالة اقتباس ${quote.label} في فهم ${concept}؟`;
  }

  return `ما دلالة هذا الاقتباس في فهم ${concept}؟`;
}

function EmptyChatState({ mode }: EmptyChatStateProps) {
  const content = MODE_CONTENT[mode];
  const modeBadge = mode === "ai" ? "المجيب التحليلي" : "المجيب المباشر";
  const modeTitle = mode === "ai" ? "وضع AI" : "وضع بدون AI";
  const primaryHint = content.welcomeBody[0]?.replace(/^•\s*/, "") || content.headerDescription;
  const secondaryHints = content.welcomeBody.slice(1, 3).map((item) => item.replace(/^•\s*/, ""));

  return (
    <div className="mx-auto w-full max-w-3xl rounded-[18px] border border-slate-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(248,250,252,0.94))] px-3 py-2.5 shadow-[0_18px_50px_-36px_rgba(15,23,42,0.35)] sm:rounded-[24px] sm:px-4 sm:py-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <span
          className={[
            "rounded-full px-2.5 py-1 text-[11px] font-semibold sm:px-3 sm:text-xs",
            mode === "ai" ? "bg-sky-100 text-sky-800" : "bg-emerald-100 text-emerald-800",
          ].join(" ")}
        >
          {modeBadge}
        </span>
        <span className="text-[11px] font-semibold tracking-[0.18em] text-slate-400 sm:text-xs">{modeTitle}</span>
      </div>

      <p className="mt-2 text-[13px] font-medium leading-6 text-slate-800 sm:text-[15px] sm:leading-8">
        {primaryHint}
      </p>

      <p className="mt-1 hidden text-xs leading-6 text-slate-500 sm:block sm:text-sm sm:leading-7">
        {content.headerDescription}
      </p>

      {secondaryHints.length > 0 ? (
        <div className="mt-3 hidden gap-2 sm:flex sm:flex-wrap">
          {secondaryHints.map((hint) => (
            <span
              key={hint}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600"
            >
              {hint}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
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

function trimSummary(value: string, maxLength = 340): string {
  const cleaned = sanitizeText(value);
  if (cleaned.length <= maxLength) {
    return cleaned;
  }

  return `${cleaned.slice(0, maxLength).trimEnd()}...`;
}

function buildInsightSummary(
  question: string,
  definition: string | null,
  relatedTerms: string[],
  relationItems: string[],
  actions: string[],
): string | null {
  const parts: string[] = [];
  const normalizedQuestion = normalizeComparisonText(question);

  if (definition) {
    parts.push(definition);
  }

  if (/(كيف|نواجه|مواجهة|نعمل|نطبق|نتبع|حل)/.test(normalizedQuestion) && actions.length > 0) {
    parts.push(`وأبرز ما يتصل بهذا الطلب عملياً هو: ${actions[0]}`);
  } else if (/(سبب|لماذا|لما|نتيجة)/.test(normalizedQuestion) && relationItems.length > 0) {
    parts.push(`وفي سياق السبب أو النتيجة يظهر ارتباطه بـ ${relationItems.slice(0, 2).join("، ")}.`);
  } else if (relationItems.length > 0) {
    parts.push(`ويرتبط في السياق بـ ${relationItems.slice(0, 2).join("، ")}.`);
  }

  if (parts.length < 2 && actions.length > 0 && !parts.some((part) => part.includes(actions[0]))) {
    parts.push(`ومن التوجيه العملي الأقرب إليه: ${actions[0]}`);
  } else if (parts.length < 2 && relatedTerms.length > 0) {
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
    return { target, text: `${relationVerb} ${target}`, typeKey: toRelationKey(rawType), typeLabel: relationVerb };
  }

  if (primaryLabel && target === primaryLabel && source) {
    return { target: source, text: `${source} ${relationVerb}`, typeKey: toRelationKey(rawType), typeLabel: relationVerb };
  }

  if (source && target) {
    return { target, text: `${source} ${relationVerb} ${target}`, typeKey: toRelationKey(rawType), typeLabel: relationVerb };
  }

  if (target) {
    return { target, text: `${relationVerb} ${target}`, typeKey: toRelationKey(rawType), typeLabel: relationVerb };
  }

  return { target: source || undefined, text: `${source} ${relationVerb}`, typeKey: toRelationKey(rawType), typeLabel: relationVerb };
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
  const typeKey = toRelationKey(detail.type);

  if (summary) {
    return { target: target || source || undefined, text: summary, typeKey, typeLabel: relationVerb };
  }

  if (!source && !target) {
    return null;
  }

  if (primaryLabel && source === primaryLabel && target) {
    return { target, text: `${relationVerb} ${target}`, typeKey, typeLabel: relationVerb };
  }

  if (primaryLabel && target === primaryLabel && source) {
    return { target: source, text: `${source} ${relationVerb}`, typeKey, typeLabel: relationVerb };
  }

  if (source && target) {
    return { target, text: `${source} ${relationVerb} ${target}`, typeKey, typeLabel: relationVerb };
  }

  if (target) {
    return { target, text: `${relationVerb} ${target}`, typeKey, typeLabel: relationVerb };
  }

  return { target: source || undefined, text: `${source} ${relationVerb}`, typeKey, typeLabel: relationVerb };
}

function buildQuoteItems(concepts: ApiConcept[]): InsightView["quoteItems"] {
  const seen = new Set<string>();
  const items: InsightView["quoteItems"] = [];

  for (const concept of concepts) {
    const label = uniqueValues(concept.labels)[0];
    if (!label) {
      continue;
    }

    for (const quote of uniqueValues(concept.quote)) {
      const signature = `${label}::${quote}`;
      if (seen.has(signature)) {
        continue;
      }
      seen.add(signature);
      items.push({ label, text: quote });
    }
  }

  return items.slice(0, 12);
}

function groupRelationItems(items: DisplayRelation[]): InsightRelationGroup[] {
  const groups = new Map<string, InsightRelationGroup>();

  for (const item of items) {
    if (!groups.has(item.typeKey)) {
      groups.set(item.typeKey, {
        key: item.typeKey,
        title: item.typeLabel,
        items: [],
      });
    }

    groups.get(item.typeKey)?.items.push(item);
  }

  const order = [
    "IS_MEANS_FOR",
    "CAUSES",
    "IS_CAUSED_BY",
    "ESTABLISHES",
    "OPPOSES",
    "RELATED_TO",
    "BELONGS_TO_GROUP",
    "BELONGS_TO_COLLECTION",
    "BELONGS_TO_LESSON",
    "PRECEDES",
    "NEGATES",
  ];

  return [...groups.values()].sort((left, right) => {
    const leftIndex = order.indexOf(left.key);
    const rightIndex = order.indexOf(right.key);
    const safeLeft = leftIndex === -1 ? order.length : leftIndex;
    const safeRight = rightIndex === -1 ? order.length : rightIndex;
    return safeLeft - safeRight;
  });
}

function inferInsightFocus(
  question: string,
  options: {
    hasActions: boolean;
    hasQuotes: boolean;
    hasRelations: boolean;
    hasTerms: boolean;
  },
): InsightSectionKey {
  const normalized = normalizeComparisonText(question);

  if (/(آية|آيات|دليل|اقتباس|نص)/.test(normalized) && options.hasQuotes) {
    return "quotes";
  }

  if (/(كيف|نواجه|مواجهة|نتبع|نعمل|نطبق|الموقف|واجب|حل)/.test(normalized)) {
    if (options.hasActions) {
      return "actions";
    }
    if (options.hasRelations) {
      return "relations";
    }
  }

  if (/(سبب|لماذا|لما|نتيجة|يؤدي)/.test(normalized) && options.hasRelations) {
    return "relations";
  }

  if (/(فرق|مقارنة|مقابل|بين)/.test(normalized) && options.hasRelations) {
    return "relations";
  }

  if (options.hasActions) {
    return "actions";
  }

  if (options.hasRelations) {
    return "relations";
  }

  if (options.hasQuotes) {
    return "quotes";
  }

  if (options.hasTerms) {
    return "concepts";
  }

  return "overview";
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
  const relationGroups = groupRelationItems(parsedRelations);
  const relatedTerms = uniqueValues([
    ...parsedRelations.map((relation) => relation.target),
    ...response.top_concepts.flatMap((concept) => concept.labels),
  ])
    .filter((label) => label !== primaryLabel)
    .slice(0, 6);

  const quoteItems = buildQuoteItems(response.top_concepts);
  const quotes = uniqueValues([
    response.quote,
    ...response.top_quotes,
    ...quoteItems.map((item) => item.text),
    ...(primaryConcept ? primaryConcept.quote : []),
  ]).slice(0, 8);
  const focusSection = inferInsightFocus(question, {
    hasActions: primaryActions.length > 0,
    hasQuotes: quotes.length > 0,
    hasRelations: relationGroups.length > 0,
    hasTerms: relatedTerms.length > 0,
  });
  const summary = buildInsightSummary(
    question,
    primaryDefinition,
    relatedTerms,
    relationItems,
    primaryActions,
  );

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
      focusSection,
      quoteItems,
      quotes,
      relatedTerms,
      relationGroups,
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
  const [messages, setMessages] = useState<Message[]>([]);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");
  const [mobileSuggestionsOpen, setMobileSuggestionsOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isReplyAnimating, setIsReplyAnimating] = useState(false);
  const [activeInsight, setActiveInsight] = useState<InsightView | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
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

      const apiResponse = payload as ChatApiResponse;
      const assistantResponseMode = normalizeResponseMode(apiResponse.mode) || responseMode;
      const presentation = buildPresentation(apiResponse, trimmedQuestion);
      const assistantMessageId = createId("assistant");
      setActiveInsight(presentation.insight);
      setMobilePanel("chat");
      setMessages((current) => [
        ...current,
        {
          id: assistantMessageId,
          isAnimating: true,
          responseMode: assistantResponseMode,
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
      setMobilePanel("chat");
      setMessages((current) => [
        ...current,
        {
          id: assistantMessageId,
          isAnimating: true,
          responseMode,
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

  function handleQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && event.shiftKey) {
      event.preventDefault();
      void sendQuestion(draft);
    }
  }

  function handleInsightTermSelection(term: string) {
    setDraft(`ما معنى ${term}؟`);
    textareaRef.current?.focus();
  }

  function handleInsightRelationSelection(relation: DisplayRelation) {
    setDraft(buildRelationFollowUpQuestion(activeInsight?.title || null, relation));
    textareaRef.current?.focus();
  }

  function handleInsightQuoteSelection(quote: InsightQuoteItem) {
    setDraft(buildQuoteFollowUpQuestion(activeInsight?.title || null, quote));
    textareaRef.current?.focus();
  }

  const hasConversationStarted = messages.length > 0;

  return (
    <main className="h-[100dvh] overflow-hidden p-1.5 sm:p-3 lg:p-4">
      <div className="mx-auto grid h-full min-h-0 max-w-7xl grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-2 sm:gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(320px,360px)] lg:grid-rows-1 lg:gap-4">
        <div className="flex items-center gap-2 rounded-[22px] border border-white/75 bg-white/82 p-1 shadow-[0_18px_40px_-28px_rgba(15,23,42,0.3)] backdrop-blur-xl lg:hidden">
          {([
            { key: "chat", label: "المحادثة" },
            { key: "insight", label: "الخلاصة" },
          ] as const).map((item) => {
            const isActive = mobilePanel === item.key;

            return (
              <button
                key={item.key}
                type="button"
                aria-pressed={isActive}
                onClick={() => setMobilePanel(item.key)}
                className={[
                  "flex-1 rounded-full px-3 py-2 text-sm font-semibold transition",
                  isActive
                    ? "bg-slate-900 text-white shadow-[0_14px_28px_-18px_rgba(15,23,42,0.7)]"
                    : "text-slate-500 hover:text-slate-900",
                ].join(" ")}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        <section
          className={[
            "grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-[24px] border border-white/75 bg-white/82 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl sm:rounded-[28px] lg:rounded-[30px]",
            mobilePanel === "chat" ? "grid" : "hidden",
            "lg:grid",
          ].join(" ")}
        >
          <header className="flex min-w-0 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-200/80 px-3 py-1.5 sm:px-4 sm:py-2.5 lg:px-5 lg:py-4">
            <div>
              <h1 className="text-sm font-semibold text-slate-950 sm:text-lg lg:text-xl">المحادثة</h1>
              <p className="mt-1 hidden text-xs leading-5 text-slate-500 sm:block sm:text-sm">
                {modeContent.headerDescription}
              </p>
            </div>

            <div className="inline-flex rounded-full border border-slate-200 bg-slate-100/90 p-0.5 sm:p-1">
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
                      "rounded-full px-2.5 py-1 text-[10px] font-medium transition sm:px-4 sm:py-1.5 sm:text-sm",
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
            className="min-h-0 min-w-0 overflow-y-auto overscroll-contain px-2.5 py-2 sm:px-4 sm:py-3.5 lg:px-5 lg:py-5"
          >
            <div className="mx-auto flex w-full min-w-0 max-w-3xl flex-col gap-2.5 sm:gap-4">
              {messages.length === 0 ? <EmptyChatState mode={responseMode} /> : null}

              {messages.map((message) => (
                <div key={message.id} className="w-full animate-[floatIn_0.35s_ease-out]">
                  <ChatMessage
                    copyLabel={copiedMessageId === message.id ? "تم النسخ" : "نسخ"}
                    isAnimating={message.isAnimating}
                    onCopy={
                      message.sender === "assistant"
                        ? () => void copyText(message.id, message.text)
                        : undefined
                    }
                    responseMode={message.responseMode}
                    sender={message.sender}
                    text={message.text}
                  />
                </div>
              ))}

              {isSubmitting ? (
                <div className="w-full">
                  <TypingIndicator responseMode={responseMode} />
                </div>
              ) : null}
            </div>
          </div>

          <div className="min-w-0 shrink-0 border-t border-slate-200/80 bg-white/92 px-2.5 py-1.5 sm:px-4 sm:py-2 lg:px-5 lg:py-3">
            <div className="mb-1 flex items-center justify-between gap-2 sm:hidden">
              <button
                type="button"
                onClick={() => setMobileSuggestionsOpen((current) => !current)}
                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-semibold text-slate-600 transition hover:border-sky-300 hover:text-sky-700"
              >
                {mobileSuggestionsOpen ? "إخفاء الاقتراحات" : "إظهار الاقتراحات"}
              </button>
              <p className="text-[11px] text-slate-400">
                {draft.length > 0 ? `${draft.length}/${MAX_QUESTION_LENGTH}` : hasConversationStarted ? "متابعة مباشرة" : "أسئلة سريعة"}
              </p>
            </div>

            <div className="mb-1 hidden items-center justify-between gap-3 sm:flex">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-400">
                أسئلة سريعة
              </p>
              <p className="text-[11px] text-slate-400">
                {draft.length > 0 ? `${draft.length}/${MAX_QUESTION_LENGTH}` : `${modeContent.suggestedQuestions.length} اقتراحات`}
              </p>
            </div>

            <div
              className={[
                "min-w-0 max-w-full overflow-x-auto pb-1",
                mobileSuggestionsOpen || !hasConversationStarted ? "mb-1.5 block sm:mb-2" : "hidden sm:mb-2",
                "sm:block",
              ].join(" ")}
            >
              <div className="inline-flex min-w-max gap-2">
                {modeContent.suggestedQuestions.map((question) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => void sendQuestion(question)}
                    disabled={isSubmitting || isReplyAnimating}
                    className="shrink-0 whitespace-nowrap rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] text-slate-600 transition hover:border-sky-300 hover:text-sky-700 disabled:cursor-not-allowed disabled:opacity-50 sm:px-3 sm:py-1.5 sm:text-xs"
                  >
                    {question}
                  </button>
                ))}
              </div>
            </div>

            <form onSubmit={handleSubmit} className="min-w-0 space-y-1.5 sm:space-y-2">
              <label htmlFor="chat-question" className="sr-only">
                اكتب سؤالك
              </label>
              <div className="grid min-w-0 gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end sm:gap-2.5">
                <textarea
                  id="chat-question"
                  ref={textareaRef}
                  rows={1}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value.slice(0, MAX_QUESTION_LENGTH))}
                  onKeyDown={handleQuestionKeyDown}
                  placeholder={modeContent.placeholder}
                  disabled={isSubmitting || isReplyAnimating}
                  className="min-h-[42px] max-h-[4.5rem] w-full resize-none rounded-[14px] border border-slate-200 bg-slate-50/85 px-3 py-2 text-[13px] leading-6 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-sky-300 focus:bg-white focus:ring-4 focus:ring-sky-100 sm:min-h-[52px] sm:max-h-20 sm:rounded-[18px] sm:px-3.5 sm:py-2 sm:text-sm md:min-h-[50px] md:max-h-[4.5rem] md:text-sm md:leading-6 lg:min-h-[60px] lg:max-h-24 lg:rounded-[20px] lg:px-4 lg:py-2.5 lg:text-[15px] lg:leading-7"
                />
                <div className="flex flex-col items-start gap-1.5 sm:self-end sm:items-end">
                  <button
                    type="submit"
                    disabled={!draft.trim() || isSubmitting || isReplyAnimating}
                    className="inline-flex h-10 w-full items-center justify-center rounded-full bg-[linear-gradient(135deg,#0f172a,#0369a1)] px-4 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 sm:min-w-24 sm:h-auto sm:w-auto sm:py-2 sm:text-sm md:min-w-[5.25rem] md:text-[13px] lg:min-w-28 lg:py-2.5 lg:text-sm"
                  >
                    {isSubmitting
                      ? "جارٍ التحليل"
                      : isReplyAnimating
                        ? "قيد الكتابة"
                        : "إرسال"}
                  </button>
                  <p className="hidden text-[11px] text-slate-400 sm:block">
                    إرسال سريع: <span className="font-semibold text-slate-500">Shift + Enter</span>
                  </p>
                </div>
              </div>
            </form>
          </div>
        </section>

        <aside
          className={[
            "min-h-0 overflow-hidden rounded-[24px] border border-white/75 bg-white/82 shadow-[0_24px_80px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl sm:rounded-[28px] lg:rounded-[30px]",
            mobilePanel === "insight" ? "grid" : "hidden",
            "grid-rows-[auto_minmax(0,1fr)] lg:grid",
          ].join(" ")}
        >
          <div className="contents">
            <header className="border-b border-slate-200/80 px-4 py-2 sm:px-4 sm:py-2.5 lg:px-5 lg:py-4">
              <h2 className="text-base font-semibold text-slate-950">خلاصة المفهوم</h2>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-2.5 sm:px-4 sm:py-3 lg:px-5 lg:py-5">
              {activeInsight ? (
                <InsightPanel
                  key={`${activeInsight.title || "none"}-${activeInsight.focusSection}-${activeInsight.summary || ""}`}
                  insight={activeInsight}
                  onSelectQuote={handleInsightQuoteSelection}
                  onSelectRelation={handleInsightRelationSelection}
                  onSelectTerm={handleInsightTermSelection}
                />
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
