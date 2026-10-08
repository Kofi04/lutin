import { describe, expect, it } from "vitest";

import { isSelection, MIN_SIDE, rectBetween } from "./region";

describe("the rectangle drawn on screen", () => {
  it("is the same whichever way it was dragged", () => {
    const down = { x: 300, y: 200 };
    const up = { x: 100, y: 50 };
    expect(rectBetween(down, up)).toEqual({ x: 100, y: 50, width: 200, height: 150 });
    expect(rectBetween(up, down)).toEqual(rectBetween(down, up));
  });

  it("is whole pixels", () => {
    expect(rectBetween({ x: 10.4, y: 0 }, { x: 20.6, y: 9.5 })).toEqual({
      x: 10,
      y: 0,
      width: 10,
      height: 10,
    });
  });

  it("a click or a thin line is not a selection", () => {
    expect(isSelection(rectBetween({ x: 5, y: 5 }, { x: 5, y: 5 }))).toBe(false);
    expect(isSelection({ x: 0, y: 0, width: 400, height: MIN_SIDE - 1 })).toBe(false);
    expect(isSelection({ x: 0, y: 0, width: MIN_SIDE, height: MIN_SIDE })).toBe(true);
  });
});
