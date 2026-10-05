/**
 * Counters for measuring the idle budget from outside, through the DevTools
 * protocol (`window.__littleWizard`): frames painted, and messages received
 * by type. A few increments per event: nothing to switch off.
 */

export interface DebugStats {
  painted: number;
  settled: boolean;
  state: string;
  messages: Record<string, number>;
  /** Times the mouse came over the avatar: a hover wakes him. */
  hovers: number;
}

export const stats: DebugStats = {
  painted: 0,
  settled: false,
  state: "",
  messages: {},
  hovers: 0,
};

(globalThis as { __littleWizard?: DebugStats }).__littleWizard = stats;
