import { describe, expect, it } from "vitest";

import { colors } from "../design/tokens";
import {
  BLINK_MS,
  BREATH_PERIOD_MS,
  frameIntervalMs,
  MAX_PUPIL,
  pose,
  type PoseContext,
  poseKey,
  WORKING_PULSE_MS,
} from "./pose";
import { VISUAL_STATES } from "./state";

const calm: PoseContext = {
  state: "calm",
  sinceStateMs: 10_000,
  sinceBlinkMs: Infinity,
  pointer: null,
  hover: false,
  reducedMotion: false,
};
const at = (now: number, changes: Partial<PoseContext> = {}) =>
  pose(now, { ...calm, ...changes });

describe("breathing (DESIGN.md: scale Y 1 -> 1.02, 3.5 s)", () => {
  it("goes from 1 to 1.02 and back in 3.5 s", () => {
    expect(at(0).breath).toBeCloseTo(1, 6);
    expect(at(BREATH_PERIOD_MS / 2).breath).toBeCloseTo(1.02, 6);
    expect(at(BREATH_PERIOD_MS).breath).toBeCloseTo(1, 6);
  });

  it("is faster when the machine is busy", () => {
    expect(at(BREATH_PERIOD_MS / 2, { state: "busy" }).breath).toBeLessThan(1.02);
  });

  it("stops with reduced motion, and in sleep", () => {
    expect(at(BREATH_PERIOD_MS / 2, { reducedMotion: true }).breath).toBe(1);
    expect(at(BREATH_PERIOD_MS / 2, { state: "asleep" }).breath).toBe(1);
  });
});

describe("eyes", () => {
  it("follow the pointer, never past 30 % of the eye's radius", () => {
    for (const [dx, dy] of [
      [1000, 0],
      [-500, 700],
      [3, 4],
      [0, -9000],
    ]) {
      const p = at(0, { pointer: { dx: dx!, dy: dy! } });
      expect(Math.hypot(p.pupilX, p.pupilY)).toBeLessThanOrEqual(MAX_PUPIL + 1e-9);
    }
    const right = at(0, { pointer: { dx: 1000, dy: 0 } });
    expect(right.pupilX).toBeCloseTo(MAX_PUPIL);
    expect(right.pupilY).toBeCloseTo(0);
  });

  it("look straight ahead when the pointer is on him", () => {
    const p = at(0, { pointer: { dx: 0, dy: 0 } });
    expect([p.pupilX, p.pupilY]).toEqual([0, 0]);
  });

  it("blink: closed in the middle, open at both ends", () => {
    expect(at(0, { sinceBlinkMs: 0 }).eyeOpen).toBeCloseTo(1);
    expect(at(0, { sinceBlinkMs: BLINK_MS / 2 }).eyeOpen).toBeCloseTo(0);
    expect(at(0, { sinceBlinkMs: BLINK_MS }).eyeOpen).toBe(1);
  });

  it("squint when stressed, half-close when tired, close in sleep", () => {
    expect(at(0, { state: "stressed" }).eyeOpen).toBe(0.6);
    expect(at(0, { state: "tired" }).eyeOpen).toBe(0.5);
    expect(at(0, { state: "asleep" }).eyeOpen).toBe(0);
  });

  it("read left to right while Claude works", () => {
    const xs = [0, 400, 800, 1200].map((t) => at(t, { state: "working" }).pupilX);
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(0.3);
  });

  it("look up at the panel while a question waits", () => {
    expect(at(0, { state: "waiting", pointer: { dx: 500, dy: 500 } }).pupilY).toBe(
      -MAX_PUPIL,
    );
  });

  it("grow slightly on hover", () => {
    expect(at(0, { hover: true }).eyeScale).toBeGreaterThan(1);
  });
});

describe("the orb carries the state", () => {
  it("has the colour of the table for each state", () => {
    expect(at(0).orbColor).toBe(colors.staffRest);
    expect(at(0, { state: "working" }).orbColor).toBe(colors.stateWorking);
    expect(at(0, { state: "waiting" }).orbColor).toBe(colors.stateWaiting);
    expect(at(0, { state: "done" }).orbColor).toBe(colors.stateSuccess);
    expect(at(0, { state: "error" }).orbColor).toBe(colors.stateDanger);
    expect(at(0, { state: "offline" }).orbColor).toBe(colors.stateOffline);
  });

  it("pulses every 1.2 s while Claude works", () => {
    const w = (t: number) => at(t, { state: "working" }).orbIntensity;
    expect(w(0)).toBeCloseTo(1);
    expect(w(WORKING_PULSE_MS / 2)).toBeCloseTo(0.45);
    expect(w(WORKING_PULSE_MS)).toBeCloseTo(1);
  });

  it("is off when offline or asleep, steady when calm", () => {
    expect(at(0, { state: "offline" }).orbIntensity).toBe(0);
    expect(at(0, { state: "asleep" }).orbIntensity).toBe(0);
    expect(at(123).orbIntensity).toBe(1);
  });

  it("flashes once when done", () => {
    expect(at(0, { state: "done", sinceStateMs: 100 }).orbIntensity).toBe(1);
    expect(at(0, { state: "done", sinceStateMs: 5000 }).orbIntensity).toBeLessThan(1);
  });

  it("brightens a little on hover", () => {
    // At the bottom of the busy pulse (1.2 s into its 2.4 s), where there is room.
    expect(at(1200, { state: "busy", hover: true }).orbIntensity).toBeGreaterThan(
      at(1200, { state: "busy" }).orbIntensity,
    );
  });
});

describe("what happens once", () => {
  it("done: a jump that lands", () => {
    expect(at(0, { state: "done", sinceStateMs: 0 }).liftY).toBeGreaterThan(5);
    expect(at(0, { state: "done", sinceStateMs: 3000 }).liftY).toBeCloseTo(0, 1);
  });

  it("error: one shake of the head, then still", () => {
    const shakes = [30, 80, 200].map((t) =>
      Math.abs(at(0, { state: "error", sinceStateMs: t }).shakeX),
    );
    expect(Math.max(...shakes)).toBeGreaterThan(1);
    expect(at(0, { state: "error", sinceStateMs: 2000 }).shakeX).toBe(0);
  });

  it("nothing moves with reduced motion", () => {
    for (const state of VISUAL_STATES) {
      const p = at(500, { state, sinceStateMs: 50, reducedMotion: true });
      expect([p.liftY, p.shakeX, p.hatSway]).toEqual([0, 0, 0]);
    }
  });
});

describe("the frame budget", () => {
  it("two instants that look the same have the same key", () => {
    expect(poseKey(at(1000))).toBe(poseKey(at(1001)));
  });

  it("a calm wizard redraws far less often than every tick", () => {
    const keys = new Set<string>();
    for (let t = 0; t < BREATH_PERIOD_MS; t += 100) keys.add(poseKey(at(t)));
    // 35 ticks in a breath; most frames look like the previous one.
    expect(keys.size).toBeLessThan(15);
  });

  it("ticks slowly at rest, faster only when something pulses or moves", () => {
    expect(
      frameIntervalMs({ state: "calm", sinceStateMs: 9e9, reducedMotion: false }),
    ).toBe(250);
    expect(
      frameIntervalMs({ state: "working", sinceStateMs: 9e9, reducedMotion: false }),
    ).toBe(50);
    expect(
      frameIntervalMs({ state: "done", sinceStateMs: 0, reducedMotion: false }),
    ).toBeLessThan(40);
    expect(
      frameIntervalMs({ state: "asleep", sinceStateMs: 0, reducedMotion: false }),
    ).toBe(2000); // nothing moves in sleep: only a safety net
  });
});

describe("settled", () => {
  it("no breathing, no blink, the gaze stays", () => {
    const p = at(BREATH_PERIOD_MS / 2, {
      settled: true,
      sinceBlinkMs: BLINK_MS / 2,
      pointer: { dx: 1000, dy: 0 },
    });
    expect(p.breath).toBe(1);
    expect(p.eyeOpen).toBe(1);
    expect(p.pupilX).toBeCloseTo(MAX_PUPIL);
  });

  it("asleep, the z does not pulse", () => {
    const zs = [0, 700, 1500, 2300].map((t) => at(t, { state: "asleep" }).zAlpha);
    expect(new Set(zs).size).toBe(1);
  });
});

describe("the gaze in steps", () => {
  it("a small move of the mouse changes nothing on screen", () => {
    const a = at(0, { pointer: { dx: 400, dy: 100 } });
    const b = at(0, { pointer: { dx: 410, dy: 104 } });
    expect([a.pupilX, a.pupilY]).toEqual([b.pupilX, b.pupilY]);
  });

  it("still looks left, right, up and down exactly", () => {
    const left = at(0, { pointer: { dx: -500, dy: 0 } });
    expect(left.pupilX).toBeCloseTo(-MAX_PUPIL);
    expect(left.pupilY).toBeCloseTo(0);
    const up = at(0, { pointer: { dx: 0, dy: -500 } });
    expect(up.pupilY).toBeCloseTo(-MAX_PUPIL);
  });

  it("looks less far for a pointer close by", () => {
    const near = at(0, { pointer: { dx: 80, dy: 0 } });
    expect(near.pupilX).toBeGreaterThan(0);
    expect(near.pupilX).toBeLessThan(MAX_PUPIL);
  });
});

it("the orb is dark while the guide cursor is out (DESIGN.md section 6)", () => {
  expect(at(0, { guiding: true }).orbIntensity).toBe(0);
  expect(at(0, { state: "working", guiding: true }).orbIntensity).toBe(0);
});
