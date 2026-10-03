/**
 * The avatar window, phase M2: a placeholder disc whose colour is the mood.
 * The real figure is drawn in phase M4 (DESIGN.md section 4).
 *
 * Click opens the panel, dragging moves the window. Tray entries that are
 * core actions arrive here and leave through this window's connection.
 */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import type { ActionName, Mood } from "../protocol";
import { createClient, useStatus } from "./connect";

const client = createClient("avatar");

// DESIGN.md section 3, state colours.
const MOOD_COLOURS: Record<Mood, string> = {
  calm: "#E8B04A",
  busy: "#E8B04A",
  stressed: "#FFB547",
  tired: "#8A8A93",
  working: "#5AA9FF",
  waiting: "#FFB547",
  done: "#3DDC97",
  error: "#FF5C5C",
};

/** Beyond this, a press is a drag, not a click (the Qt avatar used 4 too). */
const DRAG_DISTANCE = 4;

function Avatar() {
  const [mood, setMood] = useState<Mood>("calm");
  const [hidden, setHidden] = useState(false);
  const status = useStatus(client);
  const press = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const off = [
      client.on("mood", (p) => setMood(p.mood)),
      client.on("quiet", (p) => setHidden(p.on)),
      client.on("avatar.toggle", () => setHidden((h) => !h)),
    ];
    const unlisten = listen<{ name: ActionName }>("tray://action", (event) => {
      client.send("action", { name: event.payload.name });
    });
    return () => {
      off.forEach((stop) => stop());
      void unlisten.then((stop) => stop());
    };
  }, []);

  useEffect(() => {
    const window = getCurrentWindow();
    void (hidden ? window.hide() : window.show());
  }, [hidden]);

  const colour = status === "online" ? MOOD_COLOURS[mood] : "#8A8A93";
  return (
    <div
      title={
        status === "online"
          ? `Little Wizard — ${mood}`
          : "Little Wizard — cœur déconnecté"
      }
      onMouseDown={(e) => {
        if (e.button === 0) press.current = { x: e.screenX, y: e.screenY };
      }}
      onMouseMove={(e) => {
        const start = press.current;
        if (start === null || (e.buttons & 1) === 0) return;
        if (Math.hypot(e.screenX - start.x, e.screenY - start.y) > DRAG_DISTANCE) {
          press.current = null;
          void getCurrentWindow().startDragging();
        }
      }}
      onMouseUp={() => {
        if (press.current !== null) void invoke("toggle_panel");
        press.current = null;
      }}
      style={{
        width: 56,
        height: 56,
        margin: 8,
        borderRadius: 999,
        background: colour,
        boxShadow: "0 0 0 3px rgba(16,16,20,0.94)",
        opacity: status === "online" ? 1 : 0.6,
        cursor: "pointer",
      }}
    />
  );
}

createRoot(document.getElementById("root")!).render(<Avatar />);
