import { describe, expect, it } from "vitest";

import {
  FOLLOW_OFFSET,
  type GuideEvent,
  type GuideState,
  initialGuide,
  onScreen,
  reduceGuide,
  type Spot,
  tail,
  type Target,
} from "./machine";

const run = (...events: GuideEvent[]): GuideState =>
  events.reduce(reduceGuide, initialGuide);
const A = "A";
const B = "B";
const pointer = (x: number, y: number, screen = A): GuideEvent => ({
  type: "pointer",
  at: { screen, x, y },
});
const target: Target = { screen: A, x: 500, y: 300, label: "Exporter" };
const avatar: Spot = { screen: A, x: 1500, y: 860 };

describe("thinking and talking, beside the pointer", () => {
  it("an answer starting makes it think beside the pointer", () => {
    const s = run(pointer(100, 100), { type: "stream.start" });
    expect(s.mode).toBe("thinking");
    expect(s.at).toEqual({
      screen: A,
      x: 100 + FOLLOW_OFFSET.x,
      y: 100 + FOLLOW_OFFSET.y,
    });
  });

  it("talks with the last three lines, then follows, then fades", () => {
    let s = run(
      pointer(0, 0),
      { type: "stream.start" },
      { type: "stream.chunk", text: "1\n2\n3\n4" },
    );
    expect([s.mode, s.bubble]).toEqual(["talking", "2\n3\n4"]);
    s = reduceGuide(s, { type: "stream.end" });
    expect(s.mode).toBe("follow");
    s = reduceGuide(s, { type: "linger.end" });
    expect(s.mode).toBe("hidden");
  });

  it("not while the panel shows the answer: one surface (DESIGN.md principle 1)", () => {
    expect(
      run({ type: "panel", open: true }, pointer(0, 0), { type: "stream.start" }).mode,
    ).toBe("hidden");
  });

  it("not without knowing where the pointer is", () => {
    expect(run({ type: "stream.start" }).mode).toBe("hidden");
  });

  it("sticks to the pointer while it follows", () => {
    const s = run(pointer(0, 0), { type: "stream.start" }, pointer(40, 60));
    expect(s.at).toMatchObject({ x: 40 + FOLLOW_OFFSET.x, y: 60 + FOLLOW_OFFSET.y });
  });
});

describe("pointing", () => {
  it("is born from the avatar the first time, and flies to the target", () => {
    const s = run({ type: "point", target, origin: avatar });
    expect([s.mode, s.from, s.at]).toEqual(["flying", avatar, target]);
    expect(reduceGuide(s, { type: "landed" }).mode).toBe("pointing");
  });

  it("flies from where it already is", () => {
    const s = run(
      pointer(10, 10),
      { type: "stream.start" },
      { type: "point", target, origin: avatar },
    );
    expect(s.from).toMatchObject({ x: 10 + FOLLOW_OFFSET.x });
  });

  it("stays on the target however much the mouse moves", () => {
    const s = run(
      { type: "point", target, origin: avatar },
      { type: "landed" },
      pointer(900, 900),
    );
    expect(s.at).toEqual(target);
  });

  it("goes back to the pointer when cleared, then follows", () => {
    let s = run(
      pointer(50, 50),
      { type: "point", target, origin: null },
      { type: "landed" },
    );
    s = reduceGuide(s, { type: "clear" });
    expect([s.mode, s.from]).toEqual(["returning", target]);
    s = reduceGuide(s, { type: "returned" });
    expect(s.mode).toBe("follow");
  });

  it("without a pointer, simply disappears when cleared", () => {
    const s = run(
      { type: "point", target, origin: avatar },
      { type: "landed" },
      { type: "clear" },
    );
    expect(s.mode).toBe("hidden");
  });

  it("gives up on its own after a while (nobody cleared it)", () => {
    const s = run(
      { type: "point", target, origin: avatar },
      { type: "landed" },
      { type: "pointing.end" },
    );
    expect(s.mode).toBe("hidden");
  });
});

describe("steps", () => {
  const steps = [
    { text: "Ouvre Fichier", target: { screen: A, x: 10, y: 10, label: "Fichier" } },
    { text: "Lis bien", target: null },
    { text: "Exporte", target: { screen: B, x: 300, y: 200, label: "Exporter" } },
  ];

  it("flies to the first step, lands in steps mode", () => {
    let s = run({ type: "steps", steps, origin: avatar });
    expect([s.mode, s.step, (s.at as Target | null)?.label]).toEqual([
      "flying",
      0,
      "Fichier",
    ]);
    s = reduceGuide(s, { type: "landed" });
    expect(s.mode).toBe("steps");
  });

  it("a step without a place keeps the cursor still", () => {
    const s = run(
      { type: "steps", steps, origin: avatar },
      { type: "landed" },
      { type: "step", index: 1 },
    );
    expect([s.mode, s.step, (s.at as Target | null)?.label]).toEqual([
      "steps",
      1,
      "Fichier",
    ]);
  });

  it("moves to another screen for a step there", () => {
    const s = run(
      { type: "steps", steps, origin: avatar },
      { type: "landed" },
      { type: "step", index: 2 },
    );
    expect([s.mode, s.from?.screen, s.at?.screen]).toEqual(["flying", A, B]);
  });

  it("clamps the index", () => {
    const s = run({ type: "steps", steps, origin: avatar }, { type: "step", index: 99 });
    expect(s.step).toBe(2);
  });
});

describe("which screen draws it", () => {
  it("the screen it is on", () => {
    const s = run({ type: "point", target, origin: avatar }, { type: "landed" });
    expect([onScreen(s, A), onScreen(s, B)]).toEqual([true, false]);
  });

  it("both screens while it crosses: one fades out, the other in", () => {
    const s = run({ type: "point", target: { ...target, screen: B }, origin: avatar });
    expect([onScreen(s, A), onScreen(s, B)]).toEqual([true, true]);
  });

  it("none when hidden: an idle overlay costs nothing", () => {
    expect(onScreen(initialGuide, A)).toBe(false);
  });
});

it("tail keeps the last lines", () => {
  expect(tail("a\nb\n\nc\nd\n")).toBe("b\nc\nd");
});
