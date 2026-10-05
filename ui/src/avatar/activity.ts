/**
 * What counts as "something happened" for the avatar: it wakes him from a
 * settled pose, and delays sleep.
 *
 * The machine's load does not count. It changes the orb's colour, but a
 * machine hovering around a threshold flips between calm and stressed every
 * few seconds, and the wizard never settled (measured in M4: five flips a
 * minute, caused by the measurement itself).
 */

import type { CoreMessage, Mood } from "../protocol";

const MACHINE_MOODS: ReadonlySet<Mood> = new Set(["calm", "busy", "stressed", "tired"]);

/** Messages that are plumbing, or the machine's load. */
const NOT_ACTIVITY: ReadonlySet<string> = new Set([
  "system",
  "hello.ok",
  "reply",
  "error",
]);

export function isActivity(message: CoreMessage): boolean {
  if (NOT_ACTIVITY.has(message.type)) return false;
  if (message.type === "mood") return !MACHINE_MOODS.has(message.payload.mood);
  return true;
}
