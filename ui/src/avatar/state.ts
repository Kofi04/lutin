/**
 * Which of the eleven states of DESIGN.md section 4 the avatar shows.
 *
 * Three sources: the core's mood (machine and Claude), the links (this
 * window to the core, the core to Claude), and how long nothing has
 * happened. Pure, so the whole table is tested.
 */

import type { Mood, Status } from "./types";

export type VisualState =
  | "calm"
  | "busy"
  | "stressed"
  | "tired"
  | "working"
  | "waiting"
  | "done"
  | "error"
  | "connecting"
  | "offline"
  | "asleep";

export const VISUAL_STATES: readonly VisualState[] = [
  "calm",
  "busy",
  "stressed",
  "tired",
  "working",
  "waiting",
  "done",
  "error",
  "connecting",
  "offline",
  "asleep",
];

/** After this long with nothing happening, a calm wizard falls asleep. */
export const ASLEEP_AFTER_MS = 3 * 60 * 1000;

export interface Inputs {
  mood: Mood;
  /** This window's link to the core. */
  link: Status;
  /** The core's link to Claude: "offline" | "connecting" | "ready". */
  claude: string;
  /** Milliseconds since anything happened (an event, a hover). */
  idleMs: number;
}

export function visualState({ mood, link, claude, idleMs }: Inputs): VisualState {
  // Without the core, nothing else is known: whatever the last mood was,
  // it is stale.
  if (link === "offline") return "offline";
  if (link === "connecting") return "connecting";

  // Claude's own moods come first: they are about you, and one of them
  // (waiting) is a question that will time out.
  if (mood === "waiting" || mood === "working" || mood === "done" || mood === "error") {
    return mood;
  }
  if (claude === "offline") return "offline";
  if (claude === "connecting") return "connecting";

  if (mood === "calm") return idleMs >= ASLEEP_AFTER_MS ? "asleep" : "calm";
  return mood; // busy, stressed, tired
}
