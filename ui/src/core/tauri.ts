/** The Host a window has inside Tauri: endpoint from Rust, its own window. */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

import type { Endpoint, Host } from "./client";

export const tauriHost: Host = {
  endpoint: () => invoke<Endpoint | null>("core_endpoint"),
  onEndpoint(listener) {
    void listen<Endpoint>("core://ready", (event) => listener(event.payload));
    void listen("core://down", () => listener(null));
  },
  async hideWindow() {
    const window = getCurrentWindow();
    const visible = await window.isVisible();
    if (visible) await window.hide();
    return visible;
  },
  async showWindow() {
    await getCurrentWindow().show();
  },
};
