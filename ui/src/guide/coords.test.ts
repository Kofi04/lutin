import { describe, expect, it } from "vitest";

import { type Monitor, monitorAt, overlaySize, toOverlay } from "./coords";

// The primary at 150 %, and one to its left, higher up, at 100 %: Windows
// gives the second negative coordinates.
const PRIMARY: Monitor = {
  id: "\\\\.\\DISPLAY1",
  x: 0,
  y: 0,
  width: 2400,
  height: 1350,
  scale: 1.5,
};
const LEFT: Monitor = {
  id: "\\\\.\\DISPLAY2",
  x: -1920,
  y: -200,
  width: 1920,
  height: 1080,
  scale: 1,
};
const MONITORS = [PRIMARY, LEFT];

describe("one conversion, desktop -> overlay window", () => {
  it.each([1, 1.25, 1.5, 1.75, 2])(
    "at %s, the corner is 0,0 and the far edge the CSS size",
    (scale) => {
      const m: Monitor = { ...PRIMARY, width: 1600 * scale, height: 900 * scale, scale };
      expect(toOverlay({ x: 0, y: 0 }, m)).toEqual({ x: 0, y: 0 });
      expect(toOverlay({ x: 1600 * scale, y: 900 * scale }, m)).toEqual({
        x: 1600,
        y: 900,
      });
      expect(overlaySize(m)).toEqual({ width: 1600, height: 900 });
    },
  );

  it("a monitor with negative coordinates", () => {
    expect(toOverlay({ x: -1900, y: -150 }, LEFT)).toEqual({ x: 20, y: 50 });
  });

  it("each monitor divides by its own scale, not the primary's", () => {
    expect(toOverlay({ x: 300, y: 150 }, PRIMARY)).toEqual({ x: 200, y: 100 });
    expect(toOverlay({ x: -1620, y: -50 }, LEFT)).toEqual({ x: 300, y: 150 });
  });
});

describe("which monitor", () => {
  it("finds the monitor of a point, edges included on the left/top only", () => {
    expect(monitorAt({ x: 0, y: 0 }, MONITORS)?.id).toBe(PRIMARY.id);
    expect(monitorAt({ x: -1, y: 0 }, MONITORS)?.id).toBe(LEFT.id);
    expect(monitorAt({ x: 2400, y: 0 }, MONITORS)).toBeNull();
  });

  it("a point in the gap between monitors has none", () => {
    expect(monitorAt({ x: -100, y: 1000 }, MONITORS)).toBeNull();
  });
});
