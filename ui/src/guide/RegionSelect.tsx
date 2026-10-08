/**
 * Draw a rectangle to show Claude a zone of the screen (the Qt veil's
 * successor). Shown on every overlay while the core waits for
 * capture.select; the rectangle drawn on one screen answers capture.region
 * for that screen. Escape is the core's (a global hotkey: the overlays never
 * take the keyboard); a right click cancels too.
 */

import { type PointerEvent, useRef, useState } from "react";

import type { CoreClient } from "../core/client";
import type { WindowEnv } from "../windows/env";
import type { Point } from "./coords";
import { isSelection, type Rect, rectBetween } from "./region";

/**
 * Where the pointer is on the veil, in the overlay's CSS pixels. The same as
 * clientX/Y in the real overlay, which covers its screen; also right in the
 * playground, where the screen is drawn scaled down inside a page.
 */
function local(event: PointerEvent<HTMLElement>): Point {
  const box = event.currentTarget.getBoundingClientRect();
  const scale = box.width / (event.currentTarget.offsetWidth || box.width || 1);
  return { x: (event.clientX - box.left) / scale, y: (event.clientY - box.top) / scale };
}

export function RegionSelect({
  client,
  env,
  screenId,
  mode,
}: {
  client: CoreClient;
  env: WindowEnv;
  screenId: string;
  mode: "ask" | "text";
}) {
  const start = useRef<Point | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);

  return (
    <div
      className="lw-select"
      onContextMenu={(event) => {
        event.preventDefault();
        client.send("capture.cancel", {});
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        try {
          event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
          // A pointer already gone: the drag still works inside the window.
        }
        start.current = local(event);
        setRect(rectBetween(start.current, start.current));
      }}
      onPointerMove={(event) => {
        if (start.current === null) return;
        setRect(rectBetween(start.current, local(event)));
      }}
      onPointerUp={(event) => {
        if (start.current === null) return;
        const drawn = rectBetween(start.current, local(event));
        start.current = null;
        if (!isSelection(drawn)) {
          setRect(null);
          return;
        }
        // Gone before the core's cloak looks: the veil must not be in the
        // picture, nor come back after it.
        setRect(null);
        env.hide();
        client.send("capture.region", { mode, screen_id: screenId, ...drawn });
      }}
    >
      {rect && isSelection(rect) ? (
        <div
          className="lw-select-rect"
          style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height }}
        >
          <span className="lw-select-size">
            {rect.width} × {rect.height}
          </span>
        </div>
      ) : (
        <div className="lw-select-veil" />
      )}
      <div className="lw-select-hint">
        {mode === "text"
          ? "Tracez la zone dont lire le texte · Échap pour annuler"
          : "Tracez la zone à montrer à Claude · Échap pour annuler"}
      </div>
    </div>
  );
}
