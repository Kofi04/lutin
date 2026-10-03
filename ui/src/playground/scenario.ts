/**
 * Scenarios: what the core says, and when, written as JSON.
 *
 * A step is a protocol event (`type` + `payload`), or one of two pseudo-events
 * for the core itself: `@core.down` (it crashed) and `@core.up` (restarted).
 * `at` is in milliseconds from the start and never goes backwards.
 */

import { validate } from "../protocol";
import type { Hub } from "./hub";

export interface ScreenSpec {
  id: string;
  width: number;
  height: number;
}

export interface Step {
  at: number;
  type: string;
  payload?: Record<string, unknown>;
}

export interface Scenario {
  name: string;
  description: string;
  screens: ScreenSpec[];
  steps: Step[];
}

export const PSEUDO_EVENTS = ["@core.down", "@core.up"] as const;

/** Every problem with a scenario, or an empty list. */
export function check(scenario: Scenario): string[] {
  const problems: string[] = [];
  const screens = new Set(scenario.screens.map((s) => s.id));
  if (screens.size === 0) problems.push("no screen");
  let last = 0;
  scenario.steps.forEach((step, index) => {
    const where = `step ${index} (${step.type})`;
    if (!(step.at >= last)) problems.push(`${where}: 'at' goes backwards`);
    last = step.at;
    if ((PSEUDO_EVENTS as readonly string[]).includes(step.type)) return;
    try {
      validate(step.type, step.payload ?? {}, "core");
    } catch (error) {
      problems.push(`${where}: ${(error as Error).message}`);
      return;
    }
    const screenId = step.payload?.screen_id;
    if (typeof screenId === "string" && !screens.has(screenId)) {
      problems.push(`${where}: unknown screen ${screenId}`);
    }
  });
  return problems;
}

/** Plays a scenario on a hub; returns a function that stops it. */
export function play(
  scenario: Scenario,
  hub: Hub,
  onStep: (index: number) => void = () => {},
  speed = 1,
): () => void {
  const timers = scenario.steps.map((step, index) =>
    setTimeout(() => {
      if (step.type === "@core.down") hub.down();
      else if (step.type === "@core.up") hub.restart();
      else hub.broadcast(step.type, step.payload ?? {});
      onStep(index);
    }, step.at / speed),
  );
  return () => timers.forEach(clearTimeout);
}
