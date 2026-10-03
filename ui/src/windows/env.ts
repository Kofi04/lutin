/**
 * What a window may do to itself, apart from talking to the core.
 *
 * The views never call Tauri directly: in the app this is Tauri
 * (tauriEnv.ts), in the playground it is a frame on a page. That is what lets
 * the playground show the real views, not look-alikes.
 */

import type { ActionName } from "../protocol";

export interface WindowEnv {
  show(): void;
  hide(): void;
  startDragging(): void;
  togglePanel(): void;
  /** Realign the overlays with the monitors, before drawing on them. */
  syncOverlays(): Promise<void>;
  /** Tray entries that are core actions, for the avatar to send. */
  onTrayAction(listener: (name: ActionName) => void): () => void;
}
