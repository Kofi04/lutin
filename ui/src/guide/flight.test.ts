import { describe, expect, it } from "vitest";

import { ease, flightDuration, frameAt, GHOSTS, MAX_MS, MIN_MS, plan } from "./flight";

describe("duration: clamp(450 + distance × 0.35, 450, 900) ms", () => {
  it.each([
    [0, MIN_MS],
    [100, 485],
    [1000, 800],
    [5000, MAX_MS],
  ])("%s px -> %s ms", (distance, ms) => {
    expect(flightDuration({ x: 0, y: 0 }, { x: distance, y: 0 })).toBeCloseTo(ms);
  });
});

describe("the curve", () => {
  it("starts where it leaves and ends on the target", () => {
    const f = plan({ x: 100, y: 500 }, { x: 900, y: 300 });
    expect(frameAt(f, 0).at).toEqual({ x: 100, y: 500 });
    const end = frameAt(f, f.durationMs);
    expect(end.at.x).toBeCloseTo(900);
    expect(end.at.y).toBeCloseTo(300);
    expect(end.done).toBe(true);
  });

  it("bends upward, by a quarter of the distance", () => {
    const f = plan({ x: 0, y: 500 }, { x: 800, y: 500 });
    expect(f.control).toEqual({ x: 400, y: 300 });
    // Halfway in time, the cursor is above the straight line.
    expect(frameAt(f, f.durationMs / 2).at.y).toBeLessThan(500);
  });

  it("bends upward whichever way it flies", () => {
    expect(plan({ x: 800, y: 500 }, { x: 0, y: 500 }).control.y).toBeLessThan(500);
  });

  it("eases in and out", () => {
    expect(ease(0)).toBe(0);
    expect(ease(0.5)).toBeCloseTo(0.5);
    expect(ease(1)).toBe(1);
    expect(ease(0.1)).toBeLessThan(0.1);
    expect(ease(0.9)).toBeGreaterThan(0.9);
  });

  it("stands upright again on arrival", () => {
    const f = plan({ x: 0, y: 0 }, { x: 600, y: 400 });
    expect(frameAt(f, f.durationMs).angle).toBeCloseTo(0);
    expect(Math.abs(frameAt(f, f.durationMs / 2).angle)).toBeGreaterThan(0);
  });
});

describe("the trail", () => {
  it("four ghosts behind the cursor in flight, none once landed", () => {
    const f = plan({ x: 0, y: 0 }, { x: 600, y: 0 });
    const mid = frameAt(f, f.durationMs / 2);
    expect(mid.ghosts).toHaveLength(GHOSTS);
    expect(mid.ghosts[0]!.x).toBeLessThan(mid.at.x);
    expect(frameAt(f, f.durationMs).ghosts).toEqual([]);
  });

  it("none with reduced motion", () => {
    const f = plan({ x: 0, y: 0 }, { x: 600, y: 0 });
    expect(frameAt(f, 100, false).ghosts).toEqual([]);
  });
});
