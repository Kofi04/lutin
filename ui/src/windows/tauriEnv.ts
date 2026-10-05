import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

import type { ActionName } from "../protocol";
import type { WindowEnv } from "./env";

/**
 * This window's centre in physical pixels, kept current: it only changes
 * when the window moves or is resized. The cursor arrives in the same
 * physical pixels, pushed by Rust when it moves (cursor.rs).
 */
let centre: { x: number; y: number } | null = null;

async function measure(): Promise<void> {
  const window = getCurrentWindow();
  const [position, size] = await Promise.all([
    window.outerPosition(),
    window.outerSize(),
  ]);
  centre = { x: position.x + size.width / 2, y: position.y + size.height / 2 };
}

let watching = false;
function watchCentre(): void {
  if (watching) return;
  watching = true;
  const window = getCurrentWindow();
  void measure();
  void window.onMoved(() => void measure());
  void window.onResized(() => void measure());
}

export const tauriEnv: WindowEnv = {
  show: () => void getCurrentWindow().show(),
  hide: () => void getCurrentWindow().hide(),
  startDragging: () => void getCurrentWindow().startDragging(),
  togglePanel: () => void invoke("toggle_panel"),
  syncOverlays: () => invoke("overlays_sync"),
  onPointer(listener) {
    watchCentre();
    const unlisten = listen<{ x: number; y: number }>("cursor://moved", (event) => {
      if (centre !== null) {
        listener({ dx: event.payload.x - centre.x, dy: event.payload.y - centre.y });
      }
    });
    return () => void unlisten.then((stop) => stop());
  },
  onTrayAction(listener) {
    const unlisten = listen<{ name: ActionName }>("tray://action", (event) =>
      listener(event.payload.name),
    );
    return () => void unlisten.then((stop) => stop());
  },
};
