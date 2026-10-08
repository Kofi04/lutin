/**
 * Where things are drawn in an overlay window (DESIGN.md section 6).
 *
 * Each overlay window covers one monitor exactly, at that monitor's scale
 * factor, so one CSS pixel of the window is one logical pixel of the screen.
 * Two kinds of points arrive:
 *
 * - from the core (guide.point...): logical pixels from the screen's corner,
 *   already what the window draws in;
 * - from Rust (the cursor): physical pixels of the whole desktop, which must
 *   find their monitor and be divided by its own scale factor.
 *
 * The one conversion lives here, tested at 100 to 200 % and on monitors to
 * the left of or above the primary one (negative coordinates).
 */

export interface Monitor {
  id: string;
  /** Top-left corner, physical pixels of the desktop. */
  x: number;
  y: number;
  /** Size, physical pixels. */
  width: number;
  height: number;
  scale: number;
}

export interface Point {
  x: number;
  y: number;
}

/** The monitor holding a physical desktop point, or null between monitors. */
export function monitorAt(point: Point, monitors: readonly Monitor[]): Monitor | null {
  return (
    monitors.find(
      (m) =>
        point.x >= m.x &&
        point.x < m.x + m.width &&
        point.y >= m.y &&
        point.y < m.y + m.height,
    ) ?? null
  );
}

/** A physical desktop point, in the CSS pixels of `monitor`'s overlay window. */
export function screenToOverlay(point: Point, monitor: Monitor): Point {
  return {
    x: (point.x - monitor.x) / monitor.scale,
    y: (point.y - monitor.y) / monitor.scale,
  };
}

/** The overlay window's own size, in CSS pixels. */
export function overlaySize(monitor: Monitor): { width: number; height: number } {
  return { width: monitor.width / monitor.scale, height: monitor.height / monitor.scale };
}
