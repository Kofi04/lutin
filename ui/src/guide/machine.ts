/**
 * The guide cursor's states (DESIGN.md section 6), as a pure reducer.
 *
 * Every overlay window runs it on the same events and draws only what falls
 * on its own screen, so they agree without talking to each other. Timers
 * (a flight landing, the cursor fading after 1.2 s of quiet) live in the
 * component, which reports them as events: the reducer stays pure.
 */

import type { Point } from "./coords";

export type Mode =
  | "hidden"
  | "follow"
  | "thinking"
  | "talking"
  | "flying"
  | "pointing"
  | "steps"
  | "returning";

/** A place on a screen, in that screen's logical pixels. */
export interface Spot extends Point {
  screen: string;
}

export interface Target extends Spot {
  label: string;
  /** A highlighted rectangle (guide.highlight), its top-left at x, y. */
  box?: { width: number; height: number; shape: "rect" | "ellipse" };
}

export interface Step {
  text: string;
  target: Target | null;
}

export interface GuideState {
  mode: Mode;
  /** Where the cursor is (or lands, while flying). */
  at: Spot | null;
  /** Where it took off, while flying. */
  from: Spot | null;
  target: Target | null;
  steps: Step[];
  step: number;
  /** The last lines of the answer, while talking. */
  bubble: string;
  /** The real pointer, as last seen. */
  pointer: Spot | null;
  /** The answer shows in the panel: no bubble, no dots (one surface). */
  panelOpen: boolean;
}

export const initialGuide: GuideState = {
  mode: "hidden",
  at: null,
  from: null,
  target: null,
  steps: [],
  step: 0,
  bubble: "",
  pointer: null,
  panelOpen: false,
};

/** DESIGN.md section 6: beside the real pointer, offset (+18, +20). */
export const FOLLOW_OFFSET = { x: 18, y: 20 };
/** The fade after the last activity. */
export const LINGER_MS = 1200;
/** How long it stays on a target nobody clears. */
export const POINTING_MS = 12_000;
const BUBBLE_LINES = 3;

export type GuideEvent =
  | { type: "pointer"; at: Spot }
  | { type: "panel"; open: boolean }
  | { type: "stream.start" }
  | { type: "stream.chunk"; text: string }
  | { type: "stream.end" }
  | { type: "point"; target: Target; origin: Spot | null }
  | { type: "steps"; steps: Step[]; origin: Spot | null }
  | { type: "step"; index: number }
  | { type: "landed" }
  | { type: "clear" }
  | { type: "returned" }
  | { type: "linger.end" }
  | { type: "pointing.end" };

function besidePointer(pointer: Spot): Spot {
  return {
    screen: pointer.screen,
    x: pointer.x + FOLLOW_OFFSET.x,
    y: pointer.y + FOLLOW_OFFSET.y,
  };
}

/** Last lines of a text, for a bubble that keeps up with a stream. */
export function tail(text: string, lines = BUBBLE_LINES): string {
  return text.trimEnd().split("\n").filter(Boolean).slice(-lines).join("\n");
}

/** Start a flight to `target`, from wherever the cursor is, or `origin`. */
function flyTo(state: GuideState, target: Target, origin: Spot | null): GuideState {
  // From where it is; else from the avatar (it is born from the orb); else
  // from the pointer; else it simply appears on the target.
  const from =
    state.mode !== "hidden" && state.at ? state.at : (origin ?? state.pointer ?? target);
  return { ...state, mode: "flying", from, at: target, target, bubble: "" };
}

export function reduceGuide(state: GuideState, event: GuideEvent): GuideState {
  switch (event.type) {
    case "pointer": {
      const next = { ...state, pointer: event.at };
      // Only follow, thinking and talking stick to the pointer; on a target
      // it stays put however much the mouse moves (DESIGN.md section 6).
      if (
        state.mode === "follow" ||
        state.mode === "thinking" ||
        state.mode === "talking"
      ) {
        next.at = besidePointer(event.at);
      }
      return next;
    }
    case "panel":
      return { ...state, panelOpen: event.open };

    case "stream.start":
      if (
        state.panelOpen ||
        !state.pointer ||
        !["hidden", "follow"].includes(state.mode)
      ) {
        return state;
      }
      return { ...state, mode: "thinking", at: besidePointer(state.pointer), bubble: "" };
    case "stream.chunk":
      if (state.mode !== "thinking" && state.mode !== "talking") return state;
      return { ...state, mode: "talking", bubble: tail(state.bubble + event.text) };
    case "stream.end":
      if (state.mode !== "thinking" && state.mode !== "talking") return state;
      return { ...state, mode: "follow" };

    case "point":
      return { ...flyTo(state, event.target, event.origin), steps: [], step: 0 };
    case "steps": {
      const first = event.steps.findIndex((s) => s.target !== null);
      const base = { ...state, steps: event.steps, step: Math.max(0, first) };
      if (first < 0) return { ...base, mode: "steps", target: null };
      return flyTo(base, event.steps[first]!.target!, event.origin);
    }
    case "step": {
      if (!state.steps.length) return state;
      const index = Math.min(Math.max(0, event.index), state.steps.length - 1);
      const target = state.steps[index]!.target;
      const base = { ...state, step: index };
      return target
        ? flyTo(base, target, null)
        : { ...base, mode: "steps", target: null };
    }
    case "landed":
      if (state.mode !== "flying") return state;
      return { ...state, mode: state.steps.length ? "steps" : "pointing", from: null };

    case "clear":
      if (state.mode === "hidden") return state;
      if (state.pointer && state.at) {
        // Fly back to the pointer, then fade (DESIGN.md: "returning").
        return {
          ...state,
          mode: "returning",
          from: state.at,
          at: besidePointer(state.pointer),
          target: null,
          steps: [],
          step: 0,
        };
      }
      return { ...initialGuide, pointer: state.pointer, panelOpen: state.panelOpen };
    case "returned":
      if (state.mode !== "returning") return state;
      return { ...state, mode: "follow", from: null };
    case "pointing.end":
      return state.mode === "pointing" ? reduceGuide(state, { type: "clear" }) : state;
    case "linger.end":
      if (state.mode !== "follow") return state;
      return { ...initialGuide, pointer: state.pointer, panelOpen: state.panelOpen };
  }
}

/** Whether this screen's overlay has anything to show. */
export function onScreen(state: GuideState, screen: string): boolean {
  if (state.mode === "hidden") return false;
  if (state.at?.screen === screen) return true;
  // A flight leaving this screen fades out here.
  return state.mode === "flying" || state.mode === "returning"
    ? state.from?.screen === screen
    : false;
}
