import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { availableMonitors, getCurrentWindow } from "@tauri-apps/api/window";

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
  // Through window_visible, never the window API's show/hide: see
  // set_visible in windows.rs for why.
  show: () => void invoke("window_visible", { visible: true, focus: false }),
  hide: () => void invoke("window_visible", { visible: false, focus: false }),
  startDragging: () => void getCurrentWindow().startDragging(),
  togglePanel: () => void invoke("toggle_panel"),
  openApp: (view) => void invoke("app_window", { view }),
  setInteractive: (interactive) => void invoke("overlay_interactive", { interactive }),
  releaseFocus: () => invoke("panel_release_focus"),
  applyAppearance: (scale, clickThrough) =>
    void invoke("avatar_appearance", { scale, clickThrough }),
  setCaptureExclusion: (exclude) => void invoke("capture_exclusion", { exclude }),
  onFileDrop(listener) {
    const unlisten = getCurrentWebview().onDragDropEvent((event) => {
      if (event.payload.type === "drop") listener(event.payload.paths);
    });
    return () => void unlisten.then((stop) => stop());
  },
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
  placePanel: (width, height) => invoke("panel_place", { width, height }),
  showPanel: (focus) => void invoke("panel_show", { focus }),
  onPanelToggle(listener) {
    const unlisten = listen("panel://toggle", () => listener());
    return () => void unlisten.then((stop) => stop());
  },
  async monitors() {
    return (await availableMonitors()).map((m, index) => ({
      id: m.name ?? `screen-${index}`,
      x: m.position.x,
      y: m.position.y,
      width: m.size.width,
      height: m.size.height,
      scale: m.scaleFactor,
    }));
  },
  onCursor(listener) {
    // Rust sends the moves only while some overlay listens (cursor.rs).
    void invoke("cursor_listen", { listen: true });
    const unlisten = listen<{ x: number; y: number }>("cursor://moved", (event) =>
      listener(event.payload),
    );
    return () => {
      void invoke("cursor_listen", { listen: false });
      void unlisten.then((stop) => stop());
    };
  },
  cursorNow: () => invoke<{ x: number; y: number } | null>("cursor_now"),
  avatarAnchor: () => invoke<{ x: number; y: number } | null>("avatar_anchor"),
  broadcast: (name, payload) => void emit(`lw://${name}`, payload),
  onBroadcast(name, listener) {
    const unlisten = listen(`lw://${name}`, (event) => listener(event.payload));
    return () => void unlisten.then((stop) => stop());
  },
  onTrayAction(listener) {
    const unlisten = listen<{ name: ActionName }>("tray://action", (event) =>
      listener(event.payload.name),
    );
    return () => void unlisten.then((stop) => stop());
  },
};
