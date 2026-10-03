/**
 * The avatar, phase M2-M3: a placeholder disc whose colour is the mood.
 * The real figure is drawn in phase M4 (DESIGN.md section 4).
 *
 * Click opens the panel, dragging moves the window. Tray entries that are
 * core actions arrive here and leave through this window's connection.
 */

import { useEffect, useRef, useState } from "react";

import type { CoreClient } from "../core/client";
import type { Mood } from "../protocol";
import { useStatus } from "./connect";
import type { WindowEnv } from "./env";

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

export function AvatarView({ client, env }: { client: CoreClient; env: WindowEnv }) {
  const [mood, setMood] = useState<Mood>("calm");
  const [hidden, setHidden] = useState(false);
  const status = useStatus(client);
  const press = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const off = [
      client.on("mood", (p) => setMood(p.mood)),
      client.on("quiet", (p) => setHidden(p.on)),
      client.on("avatar.toggle", () => setHidden((h) => !h)),
      env.onTrayAction((name) => client.send("action", { name })),
    ];
    return () => off.forEach((stop) => stop());
  }, [client, env]);

  useEffect(() => {
    if (hidden) env.hide();
    else env.show();
  }, [hidden, env]);

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
          env.startDragging();
        }
      }}
      onMouseUp={() => {
        if (press.current !== null) env.togglePanel();
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
