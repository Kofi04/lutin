/**
 * Motion of DESIGN.md section 3: four springs, and the Windows setting that
 * turns movement off.
 *
 * The springs are in the shape Motion takes (`{ type: "spring", stiffness,
 * damping }`) for the panel. The avatar is drawn on a canvas, frame by frame,
 * so it also needs a spring's position at a given time: `springAt`.
 */

export interface Spring {
  stiffness: number;
  damping: number;
  /** Motion's default. */
  mass?: number;
}

export const springs = {
  snappy: { stiffness: 520, damping: 38 },
  smooth: { stiffness: 320, damping: 32 },
  bouncy: { stiffness: 420, damping: 16 },
  /** The island opening and changing size: a small rebound (~5 %), not bouncy's. */
  island: { stiffness: 380, damping: 27 },
} as const satisfies Record<string, Spring>;

/** The guide cursor's flight: a duration, not a spring (DESIGN.md section 6). */
export const glide = { minMs: 500, maxMs: 900 } as const;

/** Simple fades, never linear. */
export const fade = { ms: 150, easing: "cubic-bezier(0.2, 0, 0, 1)" } as const;

/**
 * Where a spring released from 0 towards 1 is after `t` seconds.
 *
 * The exact solution of m·x'' + c·x' + k·(x - 1) = 0, x(0) = 0, x'(0) = 0,
 * rather than a simulation: a frame can ask for any instant, in any order,
 * which a step-by-step integrator cannot answer without replaying from 0.
 */
export function springAt(spring: Spring, t: number): number {
  if (t <= 0) return 0;
  const m = spring.mass ?? 1;
  const omega = Math.sqrt(spring.stiffness / m);
  const zeta = spring.damping / (2 * Math.sqrt(spring.stiffness * m));
  if (zeta < 1) {
    const wd = omega * Math.sqrt(1 - zeta * zeta);
    const decay = Math.exp(-zeta * omega * t);
    return 1 - decay * (Math.cos(wd * t) + ((zeta * omega) / wd) * Math.sin(wd * t));
  }
  // Critically damped or slower: no overshoot.
  return 1 - Math.exp(-omega * t) * (1 + omega * t);
}

/**
 * The "Show animations in Windows" setting, as WebView2 reports it. When off,
 * fades stay; movement, bounces and flights go (DESIGN.md section 3).
 */
export function prefersReducedMotion(): boolean {
  return (
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
