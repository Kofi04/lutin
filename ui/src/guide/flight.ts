/**
 * The guide cursor's flight (DESIGN.md section 6), as pure functions of time.
 *
 * A quadratic Bézier curve: the control point sits at the middle of the
 * segment, pushed sideways by a quarter of the distance, upward when it can.
 * Duration clamp(450 + distance × 0.35, 450, 900) ms, eased in and out; the
 * cursor leans along the curve's tangent; four ghosts trail behind.
 */

import type { Point } from "./coords";

export const MIN_MS = 450;
export const MAX_MS = 900;
const BEND = 0.25;
export const GHOSTS = 4;
/** How far behind each ghost is, as a fraction of the flight. */
const GHOST_STEP = 0.045;

export interface Flight {
  from: Point;
  to: Point;
  control: Point;
  durationMs: number;
}

export function flightDuration(from: Point, to: Point): number {
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  return Math.min(MAX_MS, Math.max(MIN_MS, MIN_MS + distance * 0.35));
}

export function plan(from: Point, to: Point): Flight {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const distance = Math.hypot(dx, dy);
  const middle = { x: from.x + dx / 2, y: from.y + dy / 2 };
  if (distance === 0) return { from, to, control: middle, durationMs: MIN_MS };
  // The two perpendiculars; take the one that rises (smaller y is up).
  let nx = -dy / distance;
  let ny = dx / distance;
  if (ny > 0 || (ny === 0 && nx > 0)) {
    nx = -nx;
    ny = -ny;
  }
  const control = {
    x: middle.x + nx * distance * BEND,
    y: middle.y + ny * distance * BEND,
  };
  return { from, to, control, durationMs: flightDuration(from, to) };
}

/** Ease in and out (cubic): slow off the mark, slow on arrival. */
export function ease(t: number): number {
  const u = Math.min(1, Math.max(0, t));
  return u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2;
}

function bezier(f: Flight, s: number): Point {
  const a = (1 - s) * (1 - s);
  const b = 2 * (1 - s) * s;
  const c = s * s;
  return {
    x: a * f.from.x + b * f.control.x + c * f.to.x,
    y: a * f.from.y + b * f.control.y + c * f.to.y,
  };
}

export interface FlightFrame {
  at: Point;
  /** Lean along the tangent, radians; 0 is the cursor's usual upright pose. */
  angle: number;
  /** From the newest to the oldest ghost. */
  ghosts: Point[];
  done: boolean;
}

/** Where the cursor is `elapsedMs` into the flight. */
export function frameAt(f: Flight, elapsedMs: number, trail = true): FlightFrame {
  const t = Math.min(1, elapsedMs / f.durationMs);
  const s = ease(t);
  const at = bezier(f, s);
  // Tangent of the curve at s; an arrow cursor points up-left, so leaning is
  // measured from that direction, and it straightens out on landing.
  const tx = 2 * (1 - s) * (f.control.x - f.from.x) + 2 * s * (f.to.x - f.control.x);
  const ty = 2 * (1 - s) * (f.control.y - f.from.y) + 2 * s * (f.to.y - f.control.y);
  const heading = tx === 0 && ty === 0 ? 0 : Math.atan2(ty, tx) + Math.PI * 0.75;
  const lean = Math.sin(Math.PI * t) * normalise(heading) * 0.35;
  const ghosts = trail
    ? Array.from({ length: GHOSTS }, (_, i) =>
        bezier(f, ease(Math.max(0, t - (i + 1) * GHOST_STEP))),
      )
    : [];
  return { at, angle: lean, ghosts: t >= 1 ? [] : ghosts, done: t >= 1 };
}

function normalise(angle: number): number {
  let a = angle;
  while (a > Math.PI) a -= 2 * Math.PI;
  while (a < -Math.PI) a += 2 * Math.PI;
  return a;
}
