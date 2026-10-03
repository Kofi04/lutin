/**
 * One overlay window per screen, phase M2: a marker where the core points,
 * to check placement and click-through. The guide cursor is phase M6.
 *
 * Coordinates arrive in logical pixels from this screen's corner, which is
 * exactly CSS pixels in a window covering the screen at its scale factor.
 */

import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import type { ScreenBox, ScreenPoint } from "../protocol";
import { createClient } from "./connect";

const client = createClient("overlay");
const screenId = new URLSearchParams(location.search).get("screen") ?? "";

type Mark = { kind: "point"; at: ScreenPoint } | { kind: "box"; at: ScreenBox };

function Overlay() {
  const [mark, setMark] = useState<Mark | null>(null);

  useEffect(() => {
    const off = [
      client.on("guide.point", (p) =>
        setMark(p.screen_id === screenId ? { kind: "point", at: p } : null),
      ),
      client.on("guide.highlight", (p) =>
        setMark(p.screen_id === screenId ? { kind: "box", at: p } : null),
      ),
      client.on("guide.clear", () => setMark(null)),
    ];
    return () => off.forEach((stop) => stop());
  }, []);

  useEffect(() => {
    const window = getCurrentWindow();
    if (mark === null) {
      void window.hide();
      return;
    }
    // Monitors may have changed since startup: realign first.
    void invoke("overlays_sync").then(() => window.show());
    client.send("guide.active", { active: true });
    return () => {
      client.send("guide.active", { active: false });
    };
  }, [mark]);

  if (mark === null) return null;
  const { at } = mark;
  const box =
    mark.kind === "box"
      ? { left: at.x, top: at.y, width: mark.at.width, height: mark.at.height }
      : { left: at.x - 9, top: at.y - 9, width: 18, height: 18 };
  return (
    <div
      style={{
        position: "absolute",
        ...box,
        border: "3px solid #7C7BFF",
        borderRadius: mark.kind === "box" && mark.at.shape === "rect" ? 8 : 999,
        boxSizing: "border-box",
      }}
    >
      {at.label && (
        <span
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            marginTop: 6,
            padding: "4px 8px",
            borderRadius: 8,
            whiteSpace: "nowrap",
            background: "rgba(16,16,20,0.94)",
          }}
        >
          {at.label}
        </span>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Overlay />);
