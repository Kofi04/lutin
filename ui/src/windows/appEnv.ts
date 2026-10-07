/** The app window's AppEnv inside Tauri. */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";

import type { AppEnv } from "../app/env";

export const appEnv: AppEnv = {
  onView(listener) {
    const unlisten = listen<string>("app://view", (event) => listener(event.payload));
    return () => void unlisten.then((stop) => stop());
  },
  async pickFolder(start) {
    const picked = await open({ directory: true, defaultPath: start });
    return typeof picked === "string" ? picked : null;
  },
  saveFile: (name) =>
    save({ defaultPath: name, filters: [{ name: "Markdown", extensions: ["md"] }] }),
  close: () => void invoke("window_visible", { visible: false, focus: false }),
};
