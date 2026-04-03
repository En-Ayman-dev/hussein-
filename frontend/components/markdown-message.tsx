import { Fragment, ReactNode } from "react";

type MarkdownMessageProps = {
  content: string;
};

function renderInline(text: string): ReactNode[] {
  const segments = text.split(/(\*\*.*?\*\*)/g).filter(Boolean);

  return segments.map((segment, index) => {
    const strongMatch = segment.match(/^\*\*(.+)\*\*$/);
    if (strongMatch) {
      return (
        <strong key={`${segment}-${index}`} className="font-semibold text-slate-950">
          {strongMatch[1]}
        </strong>
      );
    }

    return <Fragment key={`${segment}-${index}`}>{segment}</Fragment>;
  });
}

function renderContentBlock(lines: string[], key: string) {
  if (lines.length === 0) {
    return null;
  }

  const allBullets = lines.every((line) => /^[•*-]\s+/.test(line));
  const allQuotes = lines.every((line) => line.startsWith('"') || line.startsWith(">"));

  if (allBullets) {
    return (
      <ul key={key} className="space-y-2 text-[15px] leading-8 text-slate-700">
        {lines.map((line, index) => (
          <li key={`${key}-bullet-${index}`} className="flex gap-3">
            <span className="mt-2 h-2 w-2 rounded-full bg-sky-500/80" />
            <span>{renderInline(line.replace(/^[•*-]\s+/, ""))}</span>
          </li>
        ))}
      </ul>
    );
  }

  if (allQuotes) {
    return (
      <blockquote
        key={key}
        className="rounded-2xl border border-sky-200/80 bg-sky-50/90 px-4 py-3 text-[15px] leading-8 text-slate-700"
      >
        {lines.map((line, index) => (
          <p key={`${key}-quote-${index}`}>{renderInline(line.replace(/^>\s*/, ""))}</p>
        ))}
      </blockquote>
    );
  }

  return (
    <div key={key} className="space-y-2 text-[15px] leading-8 text-slate-700">
      {lines.map((line, index) => (
        <p key={`${key}-paragraph-${index}`}>{renderInline(line)}</p>
      ))}
    </div>
  );
}

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  const blocks = content
    .split(/\n\s*\n/)
    .map((block) => block.split("\n").map((line) => line.trim()).filter(Boolean))
    .filter((block) => block.length > 0);

  return (
    <div className="space-y-4">
      {blocks.map((block, blockIndex) => {
        const [firstLine, ...restLines] = block;
        const headingMatch = firstLine?.match(/^\*\*(.+)\*\*$/);
        const bodyLines = headingMatch ? restLines : block;

        return (
          <section key={`block-${blockIndex}`} className="space-y-3">
            {headingMatch ? (
              <h3 className="text-sm font-semibold tracking-[0.14em] text-slate-500">
                {headingMatch[1]}
              </h3>
            ) : null}
            {renderContentBlock(bodyLines, `block-content-${blockIndex}`)}
          </section>
        );
      })}
    </div>
  );
}
