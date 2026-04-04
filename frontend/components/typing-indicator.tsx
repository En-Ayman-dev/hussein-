type TypingIndicatorProps = {
  responseMode?: "ai" | "without_ai";
};

export function TypingIndicator({ responseMode = "ai" }: TypingIndicatorProps) {
  const isWithoutAi = responseMode === "without_ai";
  const shellClasses = isWithoutAi
    ? "border-emerald-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(236,253,245,0.94))]"
    : "border-sky-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(240,249,255,0.94))]";
  const badgeClasses = isWithoutAi ? "bg-emerald-100 text-emerald-800" : "bg-sky-100 text-sky-800";
  const labelClasses = isWithoutAi ? "text-emerald-600" : "text-sky-600";
  const subLabelClasses = isWithoutAi ? "text-emerald-700/80" : "text-slate-500";
  const pulseClasses = isWithoutAi
    ? ["bg-emerald-500/80", "bg-emerald-500/60", "bg-emerald-500/40"]
    : ["bg-sky-500/80", "bg-sky-500/60", "bg-sky-500/40"];
  const badgeText = isWithoutAi ? "مباشر" : "ذكاء";
  const titleText = isWithoutAi ? "المجيب المباشر" : "المجيب التحليلي";

  return (
    <div className={`self-start rounded-[28px] border px-5 py-4 shadow-[0_18px_50px_-28px_rgba(15,23,42,0.35)] ${shellClasses}`}>
      <div className="mb-3 flex items-center gap-3">
        <span className={`flex h-10 w-10 items-center justify-center rounded-2xl text-sm font-semibold ${badgeClasses}`}>
          {badgeText}
        </span>
        <div>
          <p className={`text-xs font-semibold tracking-[0.2em] ${labelClasses}`}>{titleText}</p>
          <p className={`text-sm ${subLabelClasses}`}>يكتب الآن</p>
        </div>
      </div>

      <div className="flex items-center gap-2 px-1">
        <span className={`h-2.5 w-2.5 animate-[typingPulse_1s_infinite] rounded-full ${pulseClasses[0]}`} />
        <span className={`h-2.5 w-2.5 animate-[typingPulse_1s_infinite_0.15s] rounded-full ${pulseClasses[1]}`} />
        <span className={`h-2.5 w-2.5 animate-[typingPulse_1s_infinite_0.3s] rounded-full ${pulseClasses[2]}`} />
      </div>
    </div>
  );
}
