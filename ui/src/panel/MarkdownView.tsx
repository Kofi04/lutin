/**
 * An answer's Markdown as React elements: nothing in it is ever HTML
 * (markdown.ts explains why). Code blocks get a Copy button.
 */

import { Check, Copy } from "lucide-react";
import { Fragment, useState } from "react";

import { type Block, type Inline, parse } from "./markdown";

function InlineView({ pieces }: { pieces: Inline[] }) {
  return (
    <>
      {pieces.map((piece, i) => {
        switch (piece.kind) {
          case "text":
            return <Fragment key={i}>{piece.text}</Fragment>;
          case "code":
            return <code key={i}>{piece.text}</code>;
          case "strong":
            return (
              <strong key={i}>
                <InlineView pieces={piece.children} />
              </strong>
            );
          case "em":
            return (
              <em key={i}>
                <InlineView pieces={piece.children} />
              </em>
            );
          case "link":
            // Shown, not followed: a click would navigate the panel itself.
            return (
              <span key={i}>
                {piece.text} <span className="lw-link-url">({piece.url})</span>
              </span>
            );
        }
      })}
    </>
  );
}

function CodeBlock({ text, onCopy }: { text: string; onCopy: (text: string) => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ position: "relative", marginBottom: "var(--lw-space-2)" }}>
      <pre className="lw-mono">{text}</pre>
      <button
        className="lw-chip"
        style={{ position: "absolute", top: 6, right: 6 }}
        onClick={() => {
          onCopy(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        aria-label="Copier le code"
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
        {copied ? "Copié" : "Copier"}
      </button>
    </div>
  );
}

function BlockView({ block, onCopy }: { block: Block; onCopy: (text: string) => void }) {
  switch (block.kind) {
    case "code":
      return <CodeBlock text={block.text} onCopy={onCopy} />;
    case "heading": {
      const Tag = (["h1", "h2", "h3"] as const)[block.level - 1]!;
      return (
        <Tag>
          <InlineView pieces={block.inline} />
        </Tag>
      );
    }
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag>
          {block.items.map((item, i) => (
            <li key={i}>
              <InlineView pieces={item} />
            </li>
          ))}
        </Tag>
      );
    }
    case "paragraph":
      return (
        <p>
          <InlineView pieces={block.inline} />
        </p>
      );
  }
}

export function MarkdownView({
  text,
  onCopy,
}: {
  text: string;
  onCopy: (text: string) => void;
}) {
  return (
    <>
      {parse(text).map((block, i) => (
        <BlockView key={i} block={block} onCopy={onCopy} />
      ))}
    </>
  );
}
