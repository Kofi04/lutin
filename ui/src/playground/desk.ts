/**
 * A pretend desktop for the playground: the scenario's screens side by side,
 * the page's mouse standing in for the pointer when it is over one of them,
 * the avatar in the corner of the first, and the bus between windows.
 */

import { type Monitor, type Point } from "../guide/coords";
import type { WindowEnv } from "../windows/env";
import type { ScreenSpec } from "./scenario";

export class Desk {
  readonly monitors: Monitor[];
  /** The element drawing each screen, to map the page's mouse onto it. */
  readonly boxes = new Map<string, HTMLElement>();
  private cursor: Point | null = null;
  private cursorListeners = new Set<(at: Point) => void>();
  private bus = new Map<string, Set<(payload: unknown) => void>>();

  constructor(
    screens: readonly ScreenSpec[],
    private readonly scale: number,
  ) {
    let x = 0;
    this.monitors = screens.map((s) => {
      const monitor = { id: s.id, x, y: 0, width: s.width, height: s.height, scale: 1 };
      x += s.width;
      return monitor;
    });
  }

  /** Feed a page mouse event; returns true if it was over a screen. */
  mouse(clientX: number, clientY: number): boolean {
    for (const monitor of this.monitors) {
      const box = this.boxes.get(monitor.id)?.getBoundingClientRect();
      if (
        !box ||
        clientX < box.left ||
        clientX >= box.right ||
        clientY < box.top ||
        clientY >= box.bottom
      ) {
        continue;
      }
      this.cursor = {
        x: monitor.x + (clientX - box.left) / this.scale,
        y: monitor.y + (clientY - box.top) / this.scale,
      };
      for (const listener of this.cursorListeners) listener(this.cursor);
      return true;
    }
    return false;
  }

  /** What a window gets from this desk. */
  env(): Pick<
    WindowEnv,
    "monitors" | "onCursor" | "cursorNow" | "avatarAnchor" | "broadcast" | "onBroadcast"
  > {
    return {
      monitors: async () => this.monitors,
      onCursor: (listener) => {
        this.cursorListeners.add(listener);
        return () => this.cursorListeners.delete(listener);
      },
      cursorNow: async () => this.cursor,
      avatarAnchor: async () => {
        const first = this.monitors[0];
        return first
          ? { x: first.x + first.width - 60, y: first.y + first.height - 80 }
          : null;
      },
      broadcast: (name, payload) => {
        for (const listener of this.bus.get(name) ?? []) listener(payload);
      },
      onBroadcast: (name, listener) => {
        let set = this.bus.get(name);
        if (!set) this.bus.set(name, (set = new Set()));
        set.add(listener);
        return () => set.delete(listener);
      },
    };
  }
}
