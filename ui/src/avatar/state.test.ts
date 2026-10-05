import { describe, expect, it } from "vitest";

import type { Mood } from "../protocol";
import { ASLEEP_AFTER_MS, type Inputs, VISUAL_STATES, visualState } from "./state";

const base: Inputs = { mood: "calm", link: "online", claude: "ready", idleMs: 0 };
const at = (changes: Partial<Inputs>) => visualState({ ...base, ...changes });

describe("each mood of the core has its state (DESIGN.md section 4)", () => {
  it.each<[Mood, string]>([
    ["calm", "calm"],
    ["busy", "busy"],
    ["stressed", "stressed"],
    ["tired", "tired"],
    ["working", "working"],
    ["waiting", "waiting"],
    ["done", "done"],
    ["error", "error"],
  ])("%s -> %s", (mood, expected) => {
    expect(at({ mood })).toBe(expected);
  });
});

describe("links", () => {
  it("without the core, the avatar is offline whatever the last mood said", () => {
    expect(at({ link: "offline", mood: "working" })).toBe("offline");
    expect(at({ link: "connecting", mood: "waiting" })).toBe("connecting");
  });

  it("Claude unreachable shows, unless Claude is busy with you", () => {
    expect(at({ claude: "offline" })).toBe("offline");
    expect(at({ claude: "connecting" })).toBe("connecting");
    expect(at({ claude: "offline", mood: "waiting" })).toBe("waiting");
  });

  it("Claude not connected yet, without a problem, is not offline", () => {
    expect(at({ claude: "idle" })).toBe("calm");
  });
});

describe("sleep", () => {
  it("comes after three quiet minutes", () => {
    expect(at({ idleMs: ASLEEP_AFTER_MS - 1 })).toBe("calm");
    expect(at({ idleMs: ASLEEP_AFTER_MS })).toBe("asleep");
  });

  it("never while something is going on", () => {
    expect(at({ idleMs: ASLEEP_AFTER_MS, mood: "busy" })).toBe("busy");
    expect(at({ idleMs: ASLEEP_AFTER_MS, mood: "waiting" })).toBe("waiting");
  });
});

it("every state of the table is reachable", () => {
  const reached = new Set<string>();
  const moods: Mood[] = [
    "calm",
    "busy",
    "stressed",
    "tired",
    "working",
    "waiting",
    "done",
    "error",
  ];
  for (const mood of moods)
    for (const link of ["online", "connecting", "offline"] as const)
      for (const claude of ["ready", "connecting", "offline", "idle"])
        for (const idleMs of [0, ASLEEP_AFTER_MS])
          reached.add(visualState({ mood, link, claude, idleMs }));
  expect([...reached].sort()).toEqual([...VISUAL_STATES].sort());
});
