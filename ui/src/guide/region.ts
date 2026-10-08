/**
 * The rectangle drawn to show Claude a zone (capture.select), in the overlay
 * window's CSS pixels, which are the screen's logical pixels: what
 * capture.region expects.
 */

import type { Point } from "./coords";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Below this the user meant to click, not to select (the Qt veil used 6). */
export const MIN_SIDE = 6;

/** The rectangle between two corners, whichever way it was dragged. */
export function rectBetween(a: Point, b: Point): Rect {
  return {
    x: Math.round(Math.min(a.x, b.x)),
    y: Math.round(Math.min(a.y, b.y)),
    width: Math.round(Math.abs(b.x - a.x)),
    height: Math.round(Math.abs(b.y - a.y)),
  };
}

/** Big enough to be a selection, not a slip of the mouse. */
export function isSelection(rect: Rect): boolean {
  return rect.width >= MIN_SIDE && rect.height >= MIN_SIDE;
}
