/**
 * What the app window may do apart from talking to the core: Tauri in the
 * app (windows/appEnv.ts), a frame in the playground.
 */

export interface AppEnv {
  /** The core or the tray asked for another view while the window was open. */
  onView(listener: (view: string) => void): () => void;
  /** A native folder picker; null when cancelled. */
  pickFolder(start?: string): Promise<string | null>;
  /** A native "save as" for a file name; null when cancelled. */
  saveFile(name: string): Promise<string | null>;
  /** Out of sight: the window stays, ready to reopen at once. */
  close(): void;
}
