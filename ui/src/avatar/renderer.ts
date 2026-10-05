/**
 * Keeps one avatar alive on a canvas, at the lowest cost that looks right.
 *
 * No requestAnimationFrame: that is 60 frames a second whatever happens. A
 * timer ticks at the rate the state needs (frameIntervalMs), and a tick only
 * paints when the frame would look different (poseKey). It stops entirely
 * while the window is hidden.
 */

import {
  BLINK_MS,
  frameIntervalMs,
  pose,
  type Pose,
  type PoseContext,
  poseKey,
  SETTLING_STATES,
} from "./pose";
import type { VisualState } from "./state";

export interface Clock {
  now(): number;
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
  random(): number;
}

export const realClock: Clock = {
  now: () => performance.now(),
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  random: () => Math.random(),
};

/** DESIGN.md section 4: a random blink every 3 to 6 seconds. */
const BLINK_MIN_MS = 3000;
const BLINK_SPREAD_MS = 3000;
/** Ticks while a blink runs. */
const BLINK_TICK_MS = 35;
/**
 * Settled, the eyes follow the pointer at most this often. Each new gaze is
 * a frame, and with a busy mouse that was most of the idle cost (measured:
 * 2 to 4 % of a core); once a second still reads as "he watches you".
 */
export const SETTLED_GAZE_MS = 1000;

export class AvatarRenderer {
  /** Frames actually painted; the tests and the budget read it. */
  painted = 0;

  private state: VisualState = "connecting";
  private stateSince: number;
  private hover = false;
  private settled = false;
  private target: { dx: number; dy: number } | null = null;
  /** The pointer the eyes show: the target, or a second behind when settled. */
  private gaze: { dx: number; dy: number } | null = null;
  private gazeAt = -Infinity;
  private gazeTimer: unknown = null;
  private blinkAt: number;
  private lastKey = "";
  private timer: unknown = null;
  private running = false;

  constructor(
    private readonly paint: (p: Pose) => void,
    private readonly reducedMotion: () => boolean,
    private readonly clock: Clock = realClock,
  ) {
    this.stateSince = clock.now();
    this.blinkAt = this.nextBlink(clock.now());
  }

  setState(state: VisualState): void {
    if (state === this.state) return;
    this.state = state;
    this.stateSince = this.clock.now();
    this.wake();
  }

  setHover(hover: boolean): void {
    this.hover = hover;
    this.wake();
  }

  /** A quiet minute has passed (true) or something happened (false). */
  setSettled(settled: boolean): void {
    if (settled === this.settled) return;
    this.settled = settled;
    if (!settled) this.applyGaze(); // awake: the eyes catch up at once
    this.wake();
  }

  /** Pointer relative to the avatar's centre, or null if unknown. */
  setPointer(pointer: { dx: number; dy: number } | null): void {
    this.target = pointer;
    const wait = this.settled ? this.gazeAt + SETTLED_GAZE_MS - this.clock.now() : 0;
    if (wait <= 0) {
      this.applyGaze();
      this.wake(); // the eyes move now, not at the next slow tick
    } else if (this.gazeTimer === null) {
      // One catch-up a second later, with wherever the pointer is by then.
      this.gazeTimer = this.clock.setTimeout(() => {
        this.gazeTimer = null;
        this.applyGaze();
        this.wake();
      }, wait);
    }
  }

  private applyGaze(): void {
    this.gaze = this.target;
    this.gazeAt = this.clock.now();
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.lastKey = ""; // the canvas may have been cleared while hidden
    this.tick();
  }

  stop(): void {
    this.running = false;
    if (this.timer !== null) this.clock.clearTimeout(this.timer);
    if (this.gazeTimer !== null) this.clock.clearTimeout(this.gazeTimer);
    this.timer = this.gazeTimer = null;
  }

  /** Something changed: paint now rather than at the next tick. */
  private wake(): void {
    if (!this.running) return;
    if (this.timer !== null) this.clock.clearTimeout(this.timer);
    this.tick();
  }

  private nextBlink(from: number): number {
    return from + BLINK_MIN_MS + this.clock.random() * BLINK_SPREAD_MS;
  }

  private tick(): void {
    this.timer = null;
    if (!this.running) return;
    const now = this.clock.now();
    const still = this.reducedMotion();

    if (now >= this.blinkAt + 1000) this.blinkAt = this.nextBlink(now);

    const ctx: PoseContext = {
      state: this.state,
      sinceStateMs: now - this.stateSince,
      sinceBlinkMs: now >= this.blinkAt ? now - this.blinkAt : Infinity,
      // No gliding: at 56 px a pupil travels 1.6 px at most, and easing that
      // cost a stream of frames (measured) for nothing visible.
      pointer: this.gaze,
      hover: this.hover,
      reducedMotion: still,
      settled: this.settled && SETTLING_STATES.has(this.state),
    };
    const frame = pose(now, ctx);
    const key = poseKey(frame);
    if (key !== this.lastKey) {
      this.lastKey = key;
      this.paint(frame);
      this.painted += 1;
    }
    this.timer = this.clock.setTimeout(() => this.tick(), this.nextDelay(now, ctx));
  }

  /**
   * The state's own rate, shortened only for a blink: one about to start
   * (it lasts 140 ms, a 250 ms tick would miss it), or one in progress.
   */
  private nextDelay(now: number, ctx: PoseContext): number {
    let delay = frameIntervalMs(ctx);
    if (ctx.settled) return delay; // no blinks to catch
    if (ctx.sinceBlinkMs < BLINK_MS) delay = Math.min(delay, BLINK_TICK_MS);
    else if (this.blinkAt > now) delay = Math.min(delay, this.blinkAt - now);
    return Math.max(1, delay);
  }
}
