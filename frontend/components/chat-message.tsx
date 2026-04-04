"use client";

import { MarkdownMessage } from "./markdown-message";

type ChatMessageProps = {
  copyLabel?: string;
  isAnimating?: boolean;
  onCopy?: () => void;
  responseMode?: "ai" | "without_ai";
  sender: "user" | "assistant";
  text: string;
};

export function ChatMessage({
  text,
  sender,
  onCopy,
  responseMode = "ai",
  copyLabel = "نسخ",
  isAnimating = false,
}: ChatMessageProps) {
  const isAssistant = sender === "assistant";
  const isWithoutAi = isAssistant && responseMode === "without_ai";

  const assistantShellClasses = isWithoutAi
    ? "self-start border-emerald-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(236,253,245,0.94))] text-slate-900"
    : "self-start border-sky-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(240,249,255,0.94))] text-slate-900";
  const assistantBadgeClasses = isWithoutAi
    ? "bg-emerald-100 text-emerald-800"
    : "bg-sky-100 text-sky-800";
  const assistantLabelClasses = isWithoutAi ? "text-emerald-600" : "text-sky-600";
  const copyButtonClasses = isWithoutAi
    ? "border-emerald-200 bg-white text-emerald-700 hover:border-emerald-300 hover:text-emerald-900"
    : "border-sky-200 bg-white text-sky-700 hover:border-sky-300 hover:text-sky-900";
  const cursorClasses = isWithoutAi ? "bg-emerald-500" : "bg-sky-500";
  const assistantBadgeText = isWithoutAi ? "مباشر" : "ذكاء";
  const assistantTitle = isWithoutAi ? "المجيب المباشر" : "المجيب التحليلي";

  return (
    <article
      className={`group relative min-w-0 w-full max-w-full rounded-[22px] border px-3.5 py-3 shadow-[0_18px_50px_-28px_rgba(15,23,42,0.35)] transition-transform duration-300 sm:max-w-[92%] sm:rounded-[26px] sm:px-5 sm:py-4 xl:max-w-[88%] ${
        isAssistant
          ? assistantShellClasses
          : "self-end border-sky-500/30 bg-[linear-gradient(135deg,#0f172a,#1d4ed8)] text-white"
      }`}
    >
      <div className="mb-2.5 flex items-center justify-between gap-3 sm:mb-3">
        <div className="min-w-0 flex items-center gap-3">
          <span
            className={`flex h-8 w-8 items-center justify-center rounded-xl text-xs font-semibold sm:h-10 sm:w-10 sm:rounded-2xl sm:text-sm ${
              isAssistant
                ? assistantBadgeClasses
                : "bg-white/15 text-white"
            }`}
          >
            {isAssistant ? assistantBadgeText : "أنت"}
          </span>
          <div>
            <p
              className={`text-xs font-semibold tracking-[0.2em] ${
                isAssistant ? assistantLabelClasses : "text-white/70"
              }`}
            >
              {isAssistant ? assistantTitle : "رسالتك"}
            </p>
          </div>
        </div>

        {isAssistant && onCopy ? (
          <button
            type="button"
            onClick={onCopy}
            className={`rounded-full border px-2.5 py-1 text-[11px] font-medium opacity-100 transition md:opacity-0 md:group-hover:opacity-100 ${copyButtonClasses}`}
          >
            {copyLabel}
          </button>
        ) : null}
      </div>

      {isAssistant ? (
        <div className="relative min-w-0">
          <MarkdownMessage content={text} />
          {isAnimating ? (
            <span className={`mr-1 inline-block h-5 w-[2px] animate-pulse rounded-full align-middle ${cursorClasses}`} />
          ) : null}
        </div>
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm leading-7 text-white sm:text-[15px] sm:leading-8">{text}</p>
      )}
    </article>
  );
}
