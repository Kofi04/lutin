import { describe, expect, it } from "vitest";

import {
  initial,
  MAX_TOASTS,
  type PanelEvent,
  type PanelState,
  reduce,
  windowVisible,
} from "./machine";

const run = (...events: PanelEvent[]): PanelState => events.reduce(reduce, initial);

const approval: PanelEvent = {
  type: "approval.request",
  payload: {
    request_id: "r1",
    tool: "Bash",
    detail: "ls",
    project: "",
    timeout_seconds: 110,
  },
};
const preview: PanelEvent = {
  type: "capture.preview",
  payload: {
    capture_id: "k1",
    kind: "region",
    label: "Zone",
    width: 10,
    height: 10,
    tokens: 1,
    png_base64: "x",
  },
};
const menu: PanelEvent = {
  type: "selection.menu",
  payload: { selection_id: "s1", preview: "Bonjour", actions: [] },
};

describe("the main path of DESIGN.md section 5", () => {
  it("hidden -> bar (with focus) -> answer -> hidden", () => {
    let s = run({ type: "toggle" });
    expect([s.view, s.focus]).toEqual(["bar", true]);
    s = reduce(s, { type: "submit", question: "Pourquoi ?" });
    expect(s.view).toBe("answer");
    expect(s.answer).toMatchObject({ question: "Pourquoi ?", streaming: true, text: "" });
    s = reduce(s, { type: "escape" });
    expect(s.view).toBe("hidden");
  });

  it("an answer streams in, then ends", () => {
    const s = run(
      { type: "toggle" },
      { type: "submit", question: "q" },
      { type: "stream.start" },
      { type: "stream.status", text: "Lecture de app.py" },
      { type: "stream.chunk", text: "Bon" },
      { type: "stream.chunk", text: "jour" },
      { type: "stream.end", status: "Terminé" },
    );
    expect(s.answer).toMatchObject({
      text: "Bonjour",
      streaming: false,
      status: "Terminé",
    });
  });

  it("the answer keeps coming with the panel closed; reopening shows it", () => {
    const s = run(
      { type: "toggle" },
      { type: "submit", question: "q" },
      { type: "escape" },
      { type: "stream.chunk", text: "suite" },
      { type: "toggle" },
    );
    expect(s.view).toBe("answer");
    expect(s.answer?.text).toBe("suite");
  });

  it("a new conversation goes back to an empty bar", () => {
    const s = run(
      { type: "toggle" },
      { type: "submit", question: "q" },
      { type: "conversation.new" },
    );
    expect([s.view, s.answer]).toEqual(["bar", null]);
  });

  it("the core can open the bar, or a resumed conversation", () => {
    expect(run({ type: "panel.open", payload: { state: "bar" } }).view).toBe("bar");
    const resumed = run({
      type: "panel.open",
      payload: { state: "answer", context: "## Avant", status: "Discussion reprise" },
    });
    expect(resumed.view).toBe("answer");
    expect(resumed.answer).toMatchObject({
      context: "## Avant",
      status: "Discussion reprise",
    });
  });
});

describe("approval: an interruption that returns", () => {
  it("returns to the view it interrupted", () => {
    let s = run({ type: "toggle" }, { type: "submit", question: "q" }, approval);
    expect([s.view, s.back]).toEqual(["approval", "answer"]);
    s = reduce(s, { type: "approval.answered" });
    expect([s.view, s.approval]).toEqual(["answer", null]);
  });

  it("from a closed panel, closes it again", () => {
    const s = run(approval, { type: "approval.answered" });
    expect(s.view).toBe("hidden");
  });

  it("never takes the focus away from what you are typing in", () => {
    expect(run(approval).focus).toBe(false);
  });

  it("clicking the avatar does not dismiss it: silence would time it out", () => {
    expect(run(approval, { type: "toggle" }).view).toBe("approval");
  });

  it("Escape is left to the view, which answers deny", () => {
    expect(run(approval, { type: "escape" }).view).toBe("approval");
  });

  it("closes when the core settles it (answered elsewhere, or timed out)", () => {
    const s = run({ type: "toggle" }, approval, {
      type: "approval.cancel",
      requestId: "r1",
    });
    expect([s.view, s.approval]).toEqual(["bar", null]);
  });

  it("ignores the cancel of another request", () => {
    expect(run(approval, { type: "approval.cancel", requestId: "r9" }).view).toBe(
      "approval",
    );
  });
});

describe("capture: nothing is sent unseen", () => {
  it("shows the preview, and returns to the bar once decided", () => {
    let s = run({ type: "toggle" }, preview);
    expect([s.view, s.preview?.capture_id]).toEqual(["capture", "k1"]);
    s = reduce(s, { type: "capture.decided" });
    expect([s.view, s.preview]).toEqual(["bar", null]);
  });

  it("the core's panel.open after the confirmation attaches the capture", () => {
    const s = run(
      preview,
      { type: "capture.decided" },
      {
        type: "panel.open",
        payload: {
          state: "bar",
          capture: { capture_id: "k2", label: "Zone", width: 10, height: 10 },
        },
      },
    );
    expect([s.view, s.attachment?.capture_id]).toEqual(["bar", "k2"]);
    expect(reduce(s, { type: "submit", question: "et ça ?" }).attachment).toBeNull();
  });

  it("cannot be dismissed by clicking the avatar either", () => {
    expect(run(preview, { type: "toggle" }).view).toBe("capture");
  });

  it("a preview arriving during an approval waits its turn", () => {
    let s = run(approval, preview);
    expect(s.view).toBe("approval");
    s = reduce(s, { type: "approval.answered" });
    expect(s.view).toBe("capture");
    s = reduce(s, { type: "capture.decided" });
    expect(s.view).toBe("hidden");
  });

  it("an approval arriving on a preview comes first, then the preview again", () => {
    let s = run(preview, approval);
    expect(s.view).toBe("approval");
    s = reduce(s, { type: "approval.answered" });
    expect(s.view).toBe("capture");
  });
});

describe("selection", () => {
  it("menu -> working -> done, then Escape returns", () => {
    let s = run(menu);
    expect(s.selection?.phase).toBe("menu");
    s = reduce(s, { type: "selection.picked", action: "translate_en" });
    expect(s.selection?.phase).toBe("working");
    s = reduce(s, {
      type: "selection.result",
      payload: {
        selection_id: "s1",
        action: "translate_en",
        status: "done",
        text: "Hello",
        replaces: true,
      },
    });
    expect(s.selection).toMatchObject({ phase: "done", text: "Hello", replaces: true });
    s = reduce(s, { type: "escape" });
    expect([s.view, s.selection]).toEqual(["hidden", null]);
  });

  it("ignores a result for an older selection", () => {
    const s = run(menu, {
      type: "selection.result",
      payload: {
        selection_id: "s0",
        action: "x",
        status: "done",
        text: "old",
        replaces: false,
      },
    });
    expect(s.selection?.phase).toBe("menu");
  });
});

describe("toasts (DESIGN.md: three at most)", () => {
  const toast = (title: string): PanelEvent => ({
    type: "toast",
    payload: { title, body: "", kind: "info" },
  });

  it("keep the three newest, newest first", () => {
    const s = run(toast("a"), toast("b"), toast("c"), toast("d"));
    expect(s.toasts.map((t) => t.title)).toEqual(["d", "c", "b"]);
    expect(s.toasts).toHaveLength(MAX_TOASTS);
  });

  it("keep the window up with the panel closed, until dismissed", () => {
    let s = run(toast("a"));
    expect([s.view, windowVisible(s)]).toEqual(["hidden", true]);
    s = reduce(s, { type: "toast.dismiss", id: s.toasts[0]!.id });
    expect(windowVisible(s)).toBe(false);
  });
});

describe("an answer starting by itself", () => {
  it("shows if the bar is open", () => {
    expect(run({ type: "toggle" }, { type: "stream.start" }).view).toBe("answer");
  });

  it("does not open a closed panel", () => {
    expect(run({ type: "stream.start" }).view).toBe("hidden");
  });
});

describe("a tutorial's steps (DESIGN.md section 6: Previous / Next in the panel)", () => {
  it("shows the steps, keeps the window up, and stays within them", () => {
    let s = run({ type: "guide.steps", texts: ["Ouvre", "Clique", "Exporte"] });
    expect([s.guide, windowVisible(s)]).toEqual([
      { texts: ["Ouvre", "Clique", "Exporte"], index: 0 },
      true,
    ]);
    s = reduce(s, { type: "guide.step", index: 5 });
    expect(s.guide?.index).toBe(2);
    s = reduce(s, { type: "guide.step", index: -1 });
    expect(s.guide?.index).toBe(0);
  });

  it("goes when the core clears the guide", () => {
    const s = run({ type: "guide.steps", texts: ["a"] }, { type: "guide.clear" });
    expect([s.guide, windowVisible(s)]).toEqual([null, false]);
  });
});
