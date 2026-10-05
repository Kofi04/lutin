/**
 * The numbers of one frame of the avatar, at one instant.
 *
 * Everything DESIGN.md section 4 says about life and states, as a pure
 * function of time: breathing, blinking, gaze, the orb, the jumps and the
 * head shake. Nothing here draws; draw.ts turns a Pose into pixels. Lengths
 * are in figure units, where the figure is 56 wide.
 */

import { springAt, springs } from "../design/motion";
import { colors, figure } from "../design/tokens";
import type { VisualState } from "./state";

export interface Pose {
  /** Vertical scale of the body, 1 to 1.02 when breathing. */
  breath: number;
  /** Tilt of the hat's tip, radians. */
  hatSway: number;
  /** 0 closed, 1 open. */
  eyeOpen: number;
  /** Eyes slightly larger on hover. */
  eyeScale: number;
  /** Pupil offset, as a fraction of the eye's radius; length at most 0.3. */
  pupilX: number;
  pupilY: number;
  orbColor: string;
  /** 0 off, 1 full brightness. */
  orbIntensity: number;
  /** Upward offset (jumps), figure units. */
  liftY: number;
  /** Sideways offset (head shake), figure units. */
  shakeX: number;
  /** The "z" of sleep: 0 hidden, up to 1. */
  zAlpha: number;
}

export interface PoseContext {
  state: VisualState;
  /** Milliseconds since the state began: for what happens once. */
  sinceStateMs: number;
  /** Milliseconds since the current blink began, or Infinity. */
  sinceBlinkMs: number;
  /** Where the pointer is, relative to the avatar's centre, any unit. */
  pointer: { dx: number; dy: number } | null;
  hover: boolean;
  reducedMotion: boolean;
  /**
   * Nothing has happened for a while: no breathing, no blinking, only the
   * gaze (DESIGN.md section 1, principle 3, and section 4).
   */
  settled?: boolean;
}

/** DESIGN.md section 4: pupils limited to 30 % of the eye's radius. */
export const MAX_PUPIL = 0.3;
export const BREATH_PERIOD_MS = 3500;
export const BUSY_BREATH_PERIOD_MS = 2200;
export const WORKING_PULSE_MS = 1200;
export const BLINK_MS = 140;
const WAITING_PULSE_MS = 800;
const SLOW_PULSE_MS = 2400;
const READING_PERIOD_MS = 1600;
const SHAKE_MS = 600;
const FLASH_MS = 900;

const TAU = Math.PI * 2;

/**
 * The states that settle after a quiet minute: all but the two that are
 * work you are following, Claude working and Claude waiting for you. "done"
 * especially: it lasts until the next session event, which can be hours
 * (measured: a wizard breathing and blinking all afternoon for a finished
 * session).
 */
export const SETTLING_STATES: ReadonlySet<VisualState> = new Set([
  "calm",
  "busy",
  "stressed",
  "tired",
  "done",
  "error",
  "connecting",
  "offline",
  "asleep",
]);
/** DESIGN.md section 4: he settles after this long without anything happening. */
export const SETTLE_AFTER_MS = 60_000;

/** 0 to 1 and back, `period` long, starting at 0. */
function wave(timeMs: number, period: number): number {
  return (1 - Math.cos((TAU * timeMs) / period)) / 2;
}

function pulse(timeMs: number, period: number, low: number): number {
  return low + (1 - low) * (1 - wave(timeMs, period));
}

function clampPupil(x: number, y: number): [number, number] {
  const length = Math.hypot(x, y);
  if (length <= MAX_PUPIL) return [x, y];
  return [(x / length) * MAX_PUPIL, (y / length) * MAX_PUPIL];
}

/** Gaze toward the pointer: full deflection once it is 200 px away. */
/** The gaze takes one of this many directions... */
export const GAZE_DIRECTIONS = 16;

/**
 * Gaze toward the pointer, in steps: 16 directions, and two distances (near
 * and far). A pupil travels 1.6 px at most at 56 px, so finer steps are not
 * seen, and every step is a frame: with a busy mouse, 3 or 4 a second, each
 * paid in full by the compositor of a transparent window (measured in M4).
 */
function towards(pointer: { dx: number; dy: number }): [number, number] {
  const distance = Math.hypot(pointer.dx, pointer.dy);
  if (distance < 24) return [0, 0]; // on him: look straight out
  const step = (Math.PI * 2) / GAZE_DIRECTIONS;
  const angle = Math.round(Math.atan2(pointer.dy, pointer.dx) / step) * step;
  const reach = (distance < 160 ? 0.55 : 1) * MAX_PUPIL;
  return [Math.cos(angle) * reach, Math.sin(angle) * reach];
}

export function pose(nowMs: number, ctx: PoseContext): Pose {
  const { state, sinceStateMs: since, reducedMotion: still } = ctx;

  // -- breathing: always, faster when the machine is busy ---------------
  const period = state === "busy" ? BUSY_BREATH_PERIOD_MS : BREATH_PERIOD_MS;
  const breathing = still || ctx.settled || state === "asleep" ? 0 : wave(nowMs, period);
  const breath = 1 + 0.02 * breathing;
  const hatSway = still ? 0 : 0.04 * (breathing - 0.5);

  // -- eyes -------------------------------------------------------------
  let eyeOpen = 1;
  if (state === "tired") eyeOpen = 0.5;
  if (state === "stressed") eyeOpen = 0.6;
  if (state === "asleep") eyeOpen = 0;
  if (ctx.sinceBlinkMs < BLINK_MS && state !== "asleep" && !ctx.settled) {
    // Closes and opens again: a blink is seen, not just a missing frame.
    eyeOpen *= Math.abs(1 - (2 * ctx.sinceBlinkMs) / BLINK_MS);
  }
  const eyeScale = ctx.hover ? 1.08 : 1;

  let [pupilX, pupilY] = ctx.pointer ? towards(ctx.pointer) : [0, 0];
  if (state === "working" && !still) {
    // Reading: left to right, along a line.
    pupilX = 0.25 * Math.sin((TAU * nowMs) / READING_PERIOD_MS);
    pupilY = 0.1;
  } else if (state === "waiting") {
    // The panel opens above him: that is where the question is.
    pupilX = 0;
    pupilY = -MAX_PUPIL;
  }
  [pupilX, pupilY] = clampPupil(pupilX, pupilY);

  // -- the orb ----------------------------------------------------------
  let orbColor: string = colors.staffRest;
  let orbIntensity = 1;
  switch (state) {
    case "busy":
      orbIntensity = pulse(nowMs, SLOW_PULSE_MS, 0.6);
      break;
    case "stressed":
      orbColor = figure.stressed;
      break;
    case "tired":
      orbColor = figure.orbPale;
      break;
    case "working":
      orbColor = colors.stateWorking;
      orbIntensity = pulse(nowMs, WORKING_PULSE_MS, 0.45);
      break;
    case "waiting":
      orbColor = colors.stateWaiting;
      orbIntensity = pulse(nowMs, WAITING_PULSE_MS, 0.35);
      break;
    case "done":
      // One flash, then steady.
      orbColor = colors.stateSuccess;
      orbIntensity = since < FLASH_MS ? 1 : 0.85;
      break;
    case "error":
      orbColor = colors.stateDanger;
      break;
    case "connecting":
      orbColor = figure.orbPale;
      orbIntensity = pulse(nowMs, SLOW_PULSE_MS, 0.4);
      break;
    case "offline":
      orbColor = colors.stateOffline;
      orbIntensity = 0;
      break;
    case "asleep":
      orbColor = figure.orbOff;
      orbIntensity = 0;
      break;
  }
  if (ctx.hover && orbIntensity > 0) orbIntensity = Math.min(1, orbIntensity + 0.15);

  // -- what happens once -----------------------------------------------
  let liftY = 0;
  let shakeX = 0;
  if (!still) {
    const seconds = since / 1000;
    // Starts raised and lands with the bouncy spring: the jump.
    if (state === "done") liftY = 7 * (1 - springAt(springs.bouncy, seconds));
    if (state === "waiting") liftY = 3 * (1 - springAt(springs.bouncy, seconds));
    if (state === "error" && since < SHAKE_MS) {
      shakeX = 3 * Math.sin((TAU * since) / 150) * (1 - since / SHAKE_MS);
    }
  }

  // Steady: a pulsing "z" would be a frame every few hundred ms, all night.
  const zAlpha = state === "asleep" ? 0.7 : 0;

  return {
    breath,
    hatSway,
    eyeOpen,
    eyeScale,
    pupilX,
    pupilY,
    orbColor,
    orbIntensity,
    liftY,
    shakeX,
    zAlpha,
  };
}

/**
 * The pose, rounded to what can be seen at 56 px. Two frames with the same
 * key would look the same on screen: the second is not drawn. That is most
 * of the idle CPU budget (it was, in the Qt avatar).
 */
export function poseKey(p: Pose): string {
  const q = (value: number, step: number) => Math.round(value / step);
  return [
    // Breathing moves the hat's tip about 1 px in all: steps of half a pixel
    // look the same as finer ones, and halve the frames painted.
    q(p.breath, 0.01),
    q(p.hatSway, 0.01),
    q(p.eyeOpen, 0.1),
    q(p.eyeScale, 0.02),
    // A tenth of the eye's radius is half a pixel: the pupil's real step.
    q(p.pupilX, 0.1),
    q(p.pupilY, 0.1),
    p.orbColor,
    q(p.orbIntensity, 0.04),
    q(p.liftY, 0.5),
    q(p.shakeX, 0.5),
    q(p.zAlpha, 0.1),
  ].join(" ");
}

/**
 * How often the avatar needs a new frame, in this state. Breathing alone
 * moves less than half a pixel in a tenth of a second.
 */
export function frameIntervalMs(
  ctx: Pick<PoseContext, "state" | "sinceStateMs" | "reducedMotion" | "settled">,
): number {
  const { state, sinceStateMs, reducedMotion } = ctx;
  // Nothing moves on its own: a change of state or of gaze wakes the
  // renderer anyway, this is only a safety net.
  if (state === "asleep" || (ctx.settled && SETTLING_STATES.has(state))) return 2000;
  if (state === "offline") return reducedMotion ? 1000 : 250;
  const transient =
    sinceStateMs < 1500 && (state === "done" || state === "waiting" || state === "error");
  if (transient && !reducedMotion) return 1000 / 30;
  if (
    state === "working" ||
    state === "waiting" ||
    state === "busy" ||
    state === "connecting"
  ) {
    return 1000 / 20;
  }
  // At rest: breathing in half-pixel steps needs no more than this. Blinks
  // and the gaze ask for faster ticks themselves (renderer.ts).
  return reducedMotion ? 500 : 250;
}
