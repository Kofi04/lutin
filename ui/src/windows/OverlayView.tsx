/**
 * One overlay per screen, phase M2-M3: a marker where the core points,
 * to check placement and click-through. The guide cursor is phase M6.
 *
 * Coordinates arrive in logical pixels from this screen's corner, which is
 * exactly CSS pixels in a window covering the screen at its scale factor.
 */

import { useEffect, useState } from "react";

import type { CoreClient } from "../core/client";
import type { ScreenBox, ScreenPoint } from "../protocol";
import type { WindowEnv } from "./env";

type Mark = { kind: "point"; at: ScreenPoint } | { kind: "box"; at: ScreenBox };

export function OverlayView({
  client,
  env,
  screenId,
}: {
  client: CoreClient;
  env: WindowEnv;
  screenId: string;
}) {
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
  }, [client, screenId]);

  useEffect(() => {
    if (mark === null) {
      env.hide();
      return;
    }
    // Monitors may have changed since startup: realign first. Escape is not
    // this window's business: the core claims it from the guide events, as
    // only it sees every screen at once.
    void env.syncOverlays().then(() => env.show());
  }, [mark, env]);

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
