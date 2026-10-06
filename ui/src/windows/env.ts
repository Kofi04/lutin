/**
 * What a window may do to itself, apart from talking to the core.
 *
 * The views never call Tauri directly: in the app this is Tauri
 * (tauriEnv.ts), in the playground it is a frame on a page. That is what lets
 * the playground show the real views, not look-alikes.
 */

import type { Monitor, Point } from "../guide/coords";
import type { ActionName } from "../protocol";

export interface WindowEnv {
  show(): void;
  hide(): void;
  startDragging(): void;
  togglePanel(): void;
  /** Realign the overlays with the monitors, before drawing on them. */
  syncOverlays(): Promise<void>;
  /**
   * Where the pointer goes, relative to this window's centre, in any unit
   * (only the direction and distance matter). Told only when it moves.
   */
  onPointer(listener: (pointer: { dx: number; dy: number }) => void): () => void;
  /** The panel's window: its size in CSS px, placed above the avatar. */
  placePanel(width: number, height: number): Promise<void>;
  /** Show the panel; `focus` only when it was opened to type. */
  showPanel(focus: boolean): void;
  /** The avatar was clicked (or the tray icon): the panel decides. */
  onPanelToggle(listener: () => void): () => void;
  // -- the guide (DESIGN.md section 6) --
  /** Every monitor, in physical pixels of the desktop. */
  monitors(): Promise<Monitor[]>;
  /** The pointer's moves, physical pixels, for as long as subscribed. */
  onCursor(listener: (at: Point) => void): () => void;
  /** Where the pointer is now, physical pixels. */
  cursorNow(): Promise<Point | null>;
  /** The avatar's orb, physical pixels: where the guide cursor is born. */
  avatarAnchor(): Promise<Point | null>;
  /** A message to our other windows (the panel's step buttons). */
  broadcast(name: string, payload: unknown): void;
  onBroadcast(name: string, listener: (payload: unknown) => void): () => void;
  /** Tray entries that are core actions, for the avatar to send. */
  onTrayAction(listener: (name: ActionName) => void): () => void;
}
