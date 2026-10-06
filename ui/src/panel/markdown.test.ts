import { describe, expect, it } from "vitest";

import { parse, parseInline } from "./markdown";

describe("blocks", () => {
  it("splits prose and code, keeping the code exactly", () => {
    const blocks = parse(
      "Voici :\n\n```python\nitems = load() or []\n  indent\n```\n\nFin.",
    );
    expect(blocks).toEqual([
      { kind: "paragraph", inline: [{ kind: "text", text: "Voici :" }] },
      { kind: "code", lang: "python", text: "items = load() or []\n  indent" },
      { kind: "paragraph", inline: [{ kind: "text", text: "Fin." }] },
    ]);
  });

  it("an unclosed fence still shows its code (a cut answer)", () => {
    expect(parse("```js\nlet x = 1")).toEqual([
      { kind: "code", lang: "js", text: "let x = 1" },
    ]);
  });

  it("headings, bullet and numbered lists", () => {
    const blocks = parse("## Étapes\n1. ouvrir\n2. fermer\n- a\n- b");
    expect(blocks.map((b) => b.kind)).toEqual(["heading", "list", "list"]);
    expect(blocks[1]).toMatchObject({
      ordered: true,
      items: [[{ text: "ouvrir" }], [{ text: "fermer" }]],
    });
    expect(blocks[2]).toMatchObject({ ordered: false });
  });

  it("joins the lines of a paragraph", () => {
    expect(parse("une\nphrase")).toEqual([
      { kind: "paragraph", inline: [{ kind: "text", text: "une phrase" }] },
    ]);
  });
});

describe("inline", () => {
  it("code, bold, italic", () => {
    expect(parseInline("a `b` **c** *d* _e_")).toEqual([
      { kind: "text", text: "a " },
      { kind: "code", text: "b" },
      { kind: "text", text: " " },
      { kind: "strong", children: [{ kind: "text", text: "c" }] },
      { kind: "text", text: " " },
      { kind: "em", children: [{ kind: "text", text: "d" }] },
      { kind: "text", text: " " },
      { kind: "em", children: [{ kind: "text", text: "e" }] },
    ]);
  });

  it("a link keeps its text and its address, as data", () => {
    expect(parseInline("[doc](https://example.com/x)")).toEqual([
      { kind: "link", text: "doc", url: "https://example.com/x" },
    ]);
  });

  it("HTML is text, never markup", () => {
    const html = '<img src=x onerror="alert(1)"><script>steal()</script>';
    expect(parse(html)).toEqual([
      { kind: "paragraph", inline: [{ kind: "text", text: html }] },
    ]);
  });

  it("an identifier with underscores is not italic", () => {
    expect(parseInline("call my_var_name now")).toEqual([
      { kind: "text", text: "call my_var_name now" },
    ]);
  });

  it("no formatting inside code", () => {
    expect(parseInline("`**not bold**`")).toEqual([
      { kind: "code", text: "**not bold**" },
    ]);
  });
});
