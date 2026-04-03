export function TypingIndicator() {
  return (
    <div className="self-start rounded-[28px] border border-white/70 bg-white/95 px-5 py-4 shadow-[0_18px_50px_-28px_rgba(15,23,42,0.35)]">
      <div className="mb-3 flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-100 text-sm font-semibold text-slate-700">
          AI
        </span>
        <div>
          <p className="text-xs font-semibold tracking-[0.2em] text-slate-400">المجيب</p>
          <p className="text-sm text-slate-500">يكتب الآن</p>
        </div>
      </div>

      <div className="flex items-center gap-2 px-1">
        <span className="h-2.5 w-2.5 animate-[typingPulse_1s_infinite] rounded-full bg-sky-500/80" />
        <span className="h-2.5 w-2.5 animate-[typingPulse_1s_infinite_0.15s] rounded-full bg-sky-500/60" />
        <span className="h-2.5 w-2.5 animate-[typingPulse_1s_infinite_0.3s] rounded-full bg-sky-500/40" />
      </div>
    </div>
  );
}
