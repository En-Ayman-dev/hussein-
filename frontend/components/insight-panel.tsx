"use client";

import { useMemo, useState } from "react";

export type InsightSectionKey = "overview" | "actions" | "relations" | "quotes" | "concepts";

export type InsightQuoteItem = {
  label: string;
  text: string;
};

export type InsightRelationItem = {
  target?: string;
  text: string;
  typeKey: string;
  typeLabel: string;
};

export type InsightRelationGroup = {
  items: InsightRelationItem[];
  key: string;
  title: string;
};

export type InsightView = {
  actions: string[];
  definition: string | null;
  focusSection: InsightSectionKey;
  quoteItems: InsightQuoteItem[];
  quotes: string[];
  relatedTerms: string[];
  relationGroups: InsightRelationGroup[];
  relationItems: string[];
  summary: string | null;
  title: string | null;
};

type InsightPanelProps = {
  insight: InsightView;
  onSelectQuote?: (quote: InsightQuoteItem) => void;
  onSelectRelation?: (relation: InsightRelationItem) => void;
  onSelectTerm?: (term: string) => void;
};

function buildInitialSections(insight: InsightView): Record<InsightSectionKey, boolean> {
  return {
    overview: true,
    actions: insight.focusSection === "actions",
    relations: insight.focusSection === "relations" || (insight.focusSection === "actions" && insight.relationGroups.length > 0),
    quotes: insight.focusSection === "quotes",
    concepts: insight.focusSection === "concepts",
  };
}

function sectionLabel(key: InsightSectionKey): string {
  switch (key) {
    case "overview":
      return "الصورة السريعة";
    case "actions":
      return "التوجيه العملي";
    case "relations":
      return "العلاقات";
    case "quotes":
      return "الاقتباسات";
    case "concepts":
      return "المفاهيم المرتبطة";
    default:
      return "تفاصيل";
  }
}

function sectionCount(insight: InsightView, key: InsightSectionKey): number {
  switch (key) {
    case "overview":
      return [insight.summary, insight.definition].filter(Boolean).length;
    case "actions":
      return insight.actions.length;
    case "relations":
      return insight.relationGroups.reduce((count, group) => count + group.items.length, 0);
    case "quotes":
      return insight.quoteItems.length || insight.quotes.length;
    case "concepts":
      return insight.relatedTerms.length;
    default:
      return 0;
  }
}

function orderSections(focusSection: InsightSectionKey): InsightSectionKey[] {
  const ordered: InsightSectionKey[] = ["overview", focusSection, "actions", "relations", "quotes", "concepts"];
  return ordered.filter((item, index) => ordered.indexOf(item) === index);
}

export function InsightPanel({ insight, onSelectQuote, onSelectRelation, onSelectTerm }: InsightPanelProps) {
  const [openSections, setOpenSections] = useState<Record<InsightSectionKey, boolean>>(
    buildInitialSections(insight),
  );
  const [selectedFollowUpKey, setSelectedFollowUpKey] = useState<string | null>(null);

  const orderedSections = useMemo(() => orderSections(insight.focusSection), [insight.focusSection]);

  function toggleSection(section: InsightSectionKey) {
    setOpenSections((current) => ({
      ...current,
      [section]: !current[section],
    }));
  }

  function handleTermSelection(term: string) {
    setSelectedFollowUpKey(`term:${term}`);
    onSelectTerm?.(term);
  }

  function handleRelationSelection(relation: InsightRelationItem, index: number) {
    setSelectedFollowUpKey(`relation:${relation.typeKey}:${relation.target || relation.text}:${index}`);
    onSelectRelation?.(relation);
  }

  function handleQuoteSelection(quote: InsightQuoteItem, index: number) {
    setSelectedFollowUpKey(`quote:${quote.label}:${index}`);
    onSelectQuote?.(quote);
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200/80 bg-slate-50/75 px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold tracking-[0.18em] text-slate-400">لوحة الاستكشاف</p>
            <h3 className="mt-2 text-2xl font-semibold text-slate-950">
              {insight.title || "نتيجة البحث"}
            </h3>
          </div>
          <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
            {sectionLabel(insight.focusSection)}
          </span>
        </div>

        {insight.summary ? (
          <p className="mt-4 text-sm leading-8 text-slate-700">{insight.summary}</p>
        ) : insight.definition ? (
          <p className="mt-4 text-sm leading-8 text-slate-600">{insight.definition}</p>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        {orderedSections.map((section) => {
          const count = sectionCount(insight, section);
          if (count === 0) {
            return null;
          }

          const isActive = openSections[section];
          const isFocused = insight.focusSection === section;

          return (
            <button
              key={section}
              type="button"
              onClick={() => toggleSection(section)}
              className={[
                "rounded-full border px-3 py-2 text-xs font-semibold shadow-sm transition",
                isActive
                  ? isFocused
                    ? "border-sky-500 bg-sky-600 text-white shadow-[0_10px_24px_-16px_rgba(2,132,199,0.85)]"
                    : "border-slate-400 bg-slate-800 text-white shadow-[0_10px_24px_-16px_rgba(15,23,42,0.75)]"
                  : "border-slate-200 bg-white text-slate-600 hover:border-sky-300 hover:text-sky-800",
              ].join(" ")}
            >
              {sectionLabel(section)} {count > 0 ? `(${count})` : ""}
            </button>
          );
        })}
      </div>

      <div className="space-y-3">
        {orderedSections.map((section) => {
          const count = sectionCount(insight, section);
          if (count === 0) {
            return null;
          }

          const isOpen = openSections[section];

          return (
            <section
              key={section}
              className={[
                "overflow-hidden rounded-2xl border bg-white/85 transition",
                isOpen
                  ? insight.focusSection === section
                    ? "border-sky-300 shadow-[0_18px_40px_-28px_rgba(14,165,233,0.45)]"
                    : "border-slate-300 shadow-[0_18px_40px_-30px_rgba(15,23,42,0.25)]"
                  : "border-slate-200/80",
              ].join(" ")}
            >
              <button
                type="button"
                onClick={() => toggleSection(section)}
                className={[
                  "flex w-full items-center justify-between gap-4 px-4 py-4 text-right transition",
                  isOpen
                    ? insight.focusSection === section
                      ? "bg-sky-50/80"
                      : "bg-slate-50/80"
                    : "bg-white",
                ].join(" ")}
              >
                <div>
                  <p className="text-sm font-semibold text-slate-900">{sectionLabel(section)}</p>
                  <p className="mt-1 text-xs text-slate-500">{count} عناصر ظاهرة في هذا القسم</p>
                </div>
                <span
                  className={[
                    "flex h-9 w-9 items-center justify-center rounded-full border text-lg font-semibold transition",
                    isOpen
                      ? insight.focusSection === section
                        ? "border-sky-300 bg-sky-600 text-white"
                        : "border-slate-300 bg-slate-800 text-white"
                      : "border-slate-200 bg-white text-slate-500",
                  ].join(" ")}
                >
                  {isOpen ? "−" : "+"}
                </span>
              </button>

              {isOpen ? (
                <div className="border-t border-slate-200/80 px-4 py-4">
                  {section === "overview" ? (
                    <div className="space-y-4">
                      {insight.summary ? (
                        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-4">
                          <p className="text-sm font-semibold text-slate-900">الخلاصة</p>
                          <p className="mt-2 text-sm leading-8 text-slate-700">{insight.summary}</p>
                        </div>
                      ) : null}

                      {insight.definition ? (
                        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-4">
                          <p className="text-sm font-semibold text-slate-900">التعريف الأوضح</p>
                          <p className="mt-2 text-sm leading-8 text-slate-700">{insight.definition}</p>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {section === "actions" ? (
                    <ul className="space-y-2 text-sm leading-7 text-slate-700">
                      {insight.actions.map((action) => (
                        <li
                          key={action}
                          className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3"
                        >
                          {action}
                        </li>
                      ))}
                    </ul>
                  ) : null}

                  {section === "relations" ? (
                    <div className="space-y-4">
                      {insight.relationGroups.map((group) => (
                        <div key={group.key} className="space-y-2">
                          <p className="text-sm font-semibold text-slate-900">{group.title}</p>
                          <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                            {group.items.map((item, index) => {
                              const selectionKey = `relation:${item.typeKey}:${item.target || item.text}:${index}`;
                              const isSelected = selectedFollowUpKey === selectionKey;

                              return (
                                <button
                                  key={`${group.key}-${item.text}-${index}`}
                                  type="button"
                                  onClick={() => handleRelationSelection(item, index)}
                                  className={[
                                    "w-full rounded-2xl border px-4 py-3 text-right text-sm leading-7 transition",
                                    isSelected
                                      ? "border-sky-400 bg-sky-100 text-sky-900 shadow-[0_10px_24px_-18px_rgba(2,132,199,0.65)]"
                                      : "border-slate-200/80 bg-slate-50/70 text-slate-700 hover:border-sky-300 hover:bg-sky-50 hover:text-sky-900",
                                  ].join(" ")}
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <span className="text-xs font-semibold tracking-[0.14em] text-sky-700">
                                      {group.title}
                                    </span>
                                    <span
                                      className={[
                                        "rounded-full px-2 py-1 text-[11px] font-semibold",
                                        isSelected ? "bg-sky-600 text-white" : "bg-white text-slate-500",
                                      ].join(" ")}
                                    >
                                      متابعة
                                    </span>
                                  </div>
                                  <p className="mt-2">{item.text}</p>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {section === "quotes" ? (
                    <div className="max-h-72 space-y-3 overflow-y-auto pr-1">
                      {(insight.quoteItems.length > 0
                        ? insight.quoteItems.map((quote, index) => {
                            const selectionKey = `quote:${quote.label}:${index}`;
                            const isSelected = selectedFollowUpKey === selectionKey;

                            return (
                              <button
                                key={`${quote.label}-${quote.text}`}
                                type="button"
                                onClick={() => handleQuoteSelection(quote, index)}
                                className={[
                                  "w-full rounded-2xl border px-4 py-4 text-right text-sm leading-8 transition",
                                  isSelected
                                    ? "border-amber-400 bg-amber-100 text-amber-950 shadow-[0_10px_24px_-18px_rgba(245,158,11,0.7)]"
                                    : "border-sky-200 bg-sky-50/80 text-slate-700 hover:border-amber-300 hover:bg-amber-50 hover:text-amber-950",
                                ].join(" ")}
                              >
                                <div className="mb-3 flex items-start justify-between gap-3">
                                  <p
                                    className={[
                                      "text-xs font-semibold tracking-[0.14em]",
                                      isSelected ? "text-amber-800" : "text-sky-700",
                                    ].join(" ")}
                                  >
                                    {quote.label}
                                  </p>
                                  <span
                                    className={[
                                      "rounded-full px-2 py-1 text-[11px] font-semibold",
                                      isSelected ? "bg-amber-600 text-white" : "bg-white text-slate-500",
                                    ].join(" ")}
                                  >
                                    استكشف
                                  </span>
                                </div>
                                <blockquote>{quote.text}</blockquote>
                              </button>
                            );
                          })
                        : insight.quotes.map((quote, index) => {
                            const selectionKey = `quote:quote:${index}`;
                            const isSelected = selectedFollowUpKey === selectionKey;

                            return (
                              <button
                                key={quote}
                                type="button"
                                onClick={() => handleQuoteSelection({ label: "اقتباس", text: quote }, index)}
                                className={[
                                  "w-full rounded-2xl border px-4 py-4 text-right text-sm leading-8 transition",
                                  isSelected
                                    ? "border-amber-400 bg-amber-100 text-amber-950 shadow-[0_10px_24px_-18px_rgba(245,158,11,0.7)]"
                                    : "border-sky-200 bg-sky-50/80 text-slate-700 hover:border-amber-300 hover:bg-amber-50 hover:text-amber-950",
                                ].join(" ")}
                              >
                                <div className="mb-3 flex items-start justify-between gap-3">
                                  <p
                                    className={[
                                      "text-xs font-semibold tracking-[0.14em]",
                                      isSelected ? "text-amber-800" : "text-sky-700",
                                    ].join(" ")}
                                  >
                                    اقتباس
                                  </p>
                                  <span
                                    className={[
                                      "rounded-full px-2 py-1 text-[11px] font-semibold",
                                      isSelected ? "bg-amber-600 text-white" : "bg-white text-slate-500",
                                    ].join(" ")}
                                  >
                                    استكشف
                                  </span>
                                </div>
                                <blockquote>{quote}</blockquote>
                              </button>
                            );
                          }))}
                    </div>
                  ) : null}

                  {section === "concepts" ? (
                    <div className="space-y-3">
                      {onSelectTerm ? (
                        <p className="text-xs leading-6 text-slate-500">
                          اضغط على أي مفهوم لملء السؤال به مباشرة.
                        </p>
                      ) : null}
                      <div className="flex flex-wrap gap-2">
                        {insight.relatedTerms.map((term) => (
                          <button
                            key={term}
                            type="button"
                            onClick={() => handleTermSelection(term)}
                            className={[
                              "rounded-full border px-3 py-1.5 text-sm transition",
                              selectedFollowUpKey === `term:${term}`
                                ? "border-emerald-400 bg-emerald-100 text-emerald-900 shadow-[0_10px_24px_-18px_rgba(16,185,129,0.65)]"
                                : "border-slate-200 bg-slate-50 text-slate-700 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-800",
                            ].join(" ")}
                          >
                            {term}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
