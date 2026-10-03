import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

import type { ActionName } from "../protocol";
import type { WindowEnv } from "./env";

export const tauriEnv: WindowEnv = {
  show: () => void getCurrentWindow().show(),
  hide: () => void getCurrentWindow().hide(),
  startDragging: () => void getCurrentWindow().startDragging(),
  togglePanel: () => void invoke("toggle_panel"),
  syncOverlays: () => invoke("overlays_sync"),
  onTrayAction(listener) {
    const unlisten = listen<{ name: ActionName }>("tray://action", (event) =>
      listener(event.payload.name),
    );
    return () => void unlisten.then((stop) => stop());
  },
};
