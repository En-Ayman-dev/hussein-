"use client";

import { MarkdownMessage } from "./markdown-message";

type ChatMessageProps = {
  copyLabel?: string;
  isAnimating?: boolean;
  onCopy?: () => void;
  sender: "user" | "assistant";
  text: string;
};

export function ChatMessage({
  text,
  sender,
  onCopy,
  copyLabel = "نسخ",
  isAnimating = false,
}: ChatMessageProps) {
  const isAssistant = sender === "assistant";

  return (
    <article
      className={`group relative max-w-[88%] rounded-[28px] border px-5 py-4 shadow-[0_18px_50px_-28px_rgba(15,23,42,0.35)] transition-transform duration-300 ${
        isAssistant
          ? "self-start border-white/70 bg-white/95 text-slate-900"
          : "self-end border-sky-500/30 bg-[linear-gradient(135deg,#0f172a,#1d4ed8)] text-white"
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className={`flex h-10 w-10 items-center justify-center rounded-2xl text-sm font-semibold ${
              isAssistant
                ? "bg-slate-100 text-slate-700"
                : "bg-white/15 text-white"
            }`}
          >
            {isAssistant ? "AI" : "أنت"}
          </span>
          <div>
            <p
              className={`text-xs font-semibold tracking-[0.2em] ${
                isAssistant ? "text-slate-400" : "text-white/70"
              }`}
            >
              {isAssistant ? "المجيب" : "رسالتك"}
            </p>
          </div>
        </div>

        {isAssistant && onCopy ? (
          <button
            type="button"
            onClick={onCopy}
            className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 opacity-100 transition hover:border-slate-300 hover:text-slate-900 md:opacity-0 md:group-hover:opacity-100"
          >
            {copyLabel}
          </button>
        ) : null}
      </div>

      {isAssistant ? (
        <div className="relative">
          <MarkdownMessage content={text} />
          {isAnimating ? (
            <span className="mr-1 inline-block h-5 w-[2px] animate-pulse rounded-full bg-sky-500 align-middle" />
          ) : null}
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-[15px] leading-8 text-white">{text}</p>
      )}
    </article>
  );
}
