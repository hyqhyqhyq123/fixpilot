import type { ReactNode } from "react";

interface MarkdownViewProps {
  content: string;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={key} className="rounded bg-slate-100 px-1 py-0.5 text-slate-900">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    return <span key={key}>{part}</span>;
  });
}

function isBlockStart(line: string): boolean {
  return (
    /^#{1,4}\s+/.test(line) ||
    /^```/.test(line) ||
    /^\s*-\s+/.test(line) ||
    /^---+$/.test(line.trim())
  );
}

function renderHeading(level: number, key: string, className: string, text: string) {
  const content = renderInline(text, key);

  if (level === 1) {
    return (
      <h2 key={key} className={className}>
        {content}
      </h2>
    );
  }

  if (level === 2) {
    return (
      <h3 key={key} className={className}>
        {content}
      </h3>
    );
  }

  return (
    <h4 key={key} className={className}>
      {content}
    </h4>
  );
}

export function MarkdownView({ content }: MarkdownViewProps) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(
        <pre
          key={`code-${index}`}
          className="overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-6 text-slate-100"
        >
          <code>{codeLines.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2];
      const className =
        level === 1
          ? "text-xl font-semibold text-slate-950"
          : level === 2
            ? "text-lg font-semibold text-slate-950"
            : "text-base font-semibold text-slate-900";
      blocks.push(renderHeading(level, `heading-${index}`, className, text));
      index += 1;
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      blocks.push(<hr key={`hr-${index}`} className="border-slate-200" />);
      index += 1;
      continue;
    }

    if (/^\s*-\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*-\s+/.test(lines[index])) {
        const itemMatch = /^(\s*)-\s+(.+)$/.exec(lines[index]);
        if (itemMatch) {
          const depth = Math.floor(itemMatch[1].length / 2);
          items.push(
            <li key={`li-${index}`} style={{ marginLeft: depth * 16 }}>
              {renderInline(itemMatch[2], `li-${index}`)}
            </li>,
          );
        }
        index += 1;
      }
      blocks.push(
        <ul key={`ul-${index}`} className="list-disc space-y-1 pl-5">
          {items}
        </ul>,
      );
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isBlockStart(lines[index])
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={`p-${index}`} className="whitespace-pre-wrap">
        {renderInline(paragraphLines.join("\n"), `p-${index}`)}
      </p>,
    );
  }

  return (
    <div className="space-y-3 text-sm leading-7 text-slate-700">
      {blocks.length > 0 ? blocks : <p>暂无内容</p>}
    </div>
  );
}
