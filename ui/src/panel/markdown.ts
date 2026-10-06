/**
 * The Markdown of Claude's answers, parsed into blocks and inline pieces.
 *
 * Deliberately small, and never HTML: the panel runs in a window that can
 * call Tauri, and an answer is text from the outside (it may quote a web
 * page, an email, a file). Everything here ends up as React elements, so a
 * `<script>` in an answer is shown, never run. Links are kept as text and
 * address: following one would navigate the panel itself away from the app.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "link"; text: string; url: string };

export type Block =
  | { kind: "code"; lang: string; text: string }
  | { kind: "heading"; level: 1 | 2 | 3; inline: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "paragraph"; inline: Inline[] };

const INLINE =
  /`([^`\n]+)`|\*\*([^*\n]+?)\*\*|\*([^*\n]+?)\*|(?<!\w)_([^_\n]+?)_(?!\w)|\[([^\]\n]+)\]\(([^)\s]+)\)/g;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    const at = match.index;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    const [, code, strong, em1, em2, linkText, url] = match;
    if (code !== undefined) out.push({ kind: "code", text: code });
    else if (strong !== undefined)
      out.push({ kind: "strong", children: parseInline(strong) });
    else if (em1 !== undefined || em2 !== undefined) {
      out.push({ kind: "em", children: parseInline((em1 ?? em2)!) });
    } else out.push({ kind: "link", text: linkText!, url: url! });
    last = at + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

const FENCE = /^\s*```\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,3})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export function parse(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length) {
      blocks.push({ kind: "paragraph", inline: parseInline(paragraph.join(" ")) });
      paragraph = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const fence = FENCE.exec(line);
    if (fence) {
      flush();
      const body: string[] = [];
      i++;
      // An answer cut short mid-block still shows its code: the fence closes
      // at the end of the text if it was never closed.
      while (i < lines.length && !FENCE.test(lines[i]!)) body.push(lines[i++]!);
      blocks.push({ kind: "code", lang: fence[1] ?? "", text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      const level = heading[1]!.length as 1 | 2 | 3;
      blocks.push({ kind: "heading", level, inline: parseInline(heading[2]!) });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      flush();
      const ordered = numbered !== null;
      const previous = blocks.at(-1);
      const item = parseInline((bullet ?? numbered)![1]!);
      if (previous?.kind === "list" && previous.ordered === ordered)
        previous.items.push(item);
      else blocks.push({ kind: "list", ordered, items: [item] });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}
