/**
 * The avatar window (DESIGN.md section 4): the figure, its state, and what
 * the mouse does to it.
 *
 * Click opens the panel, a right click shows the tray's menu at the pointer,
 * dragging moves the window, Ctrl + drag points at a
 * window to show Claude, a file dropped on him is shown too. Tray entries that
 * are core actions arrive here and leave through this window's connection.
 */

import { useEffect, useRef, useState } from "react";

import { viewFor } from "../app/routes";
import { isActivity } from "../avatar/activity";
import { AvatarCanvas } from "../avatar/AvatarCanvas";
import { CountdownRing } from "../avatar/CountdownRing";
import { SETTLE_AFTER_MS } from "../avatar/pose";
import { visualState } from "../avatar/state";
import type { CoreClient } from "../core/client";
import { stats } from "../debug";
import type { CorePayloads, Mood } from "../protocol";
import { useStatus } from "./connect";
import type { WindowEnv } from "./env";

/** Beyond this, a press is a drag, not a click (the Qt avatar used 4 too). */
const DRAG_DISTANCE = 4;

export function AvatarView({ client, env }: { client: CoreClient; env: WindowEnv }) {
  const [mood, setMood] = useState<Mood>("calm");
  const [claude, setClaude] = useState("idle");
  const [hidden, setHidden] = useState(false);
  const [hover, setHover] = useState(false);
  const [guiding, setGuiding] = useState(false);
  const [pending, setPending] = useState<{
    id: string;
    deadline: number;
    total: number;
  } | null>(null);
  const [lastActivity, setLastActivity] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const link = useStatus(client);
  const press = useRef<{ x: number; y: number; ctrl: boolean } | null>(null);
  /** Ctrl + drag under way: the pointer is held until released, anywhere. */
  const [targeting, setTargeting] = useState(false);
  const [look, setLook] = useState<CorePayloads["appearance"] | null>(null);

  useEffect(() => {
    const off = [
      client.on("mood", (p) => setMood(p.mood)),
      // "offline" without a reason is a session not opened yet (no prewarm):
      // nothing is wrong, and the wizard should not look switched off.
      client.on("connection", (p) =>
        setClaude(p.state === "offline" && !p.detail ? "idle" : p.state),
      ),
      client.on("quiet", (p) => setHidden(p.on)),
      client.on("appearance", setLook),
      // One capture at a time, as the core does: the first file only.
      env.onFileDrop((paths) => {
        if (paths[0]) client.send("capture.file", { path: paths[0] });
      }),
      client.on("avatar.toggle", () => setHidden((h) => !h)),
      client.on("guide.point", () => setGuiding(true)),
      client.on("guide.highlight", () => setGuiding(true)),
      client.on("guide.steps", () => setGuiding(true)),
      client.on("guide.clear", () => setGuiding(false)),
      client.on("approval.request", (p) =>
        setPending({
          id: p.request_id,
          deadline: Date.now() + p.timeout_seconds * 1000,
          total: p.timeout_seconds * 1000,
        }),
      ),
      client.on("approval.cancel", (p) =>
        setPending((current) => (current?.id === p.request_id ? null : current)),
      ),
      client.onAny((message) => {
        stats.messages[message.type] = (stats.messages[message.type] ?? 0) + 1;
        if (isActivity(message)) setLastActivity(Date.now());
      }),
      // The avatar is the one window always there: it opens the others.
      client.on("window.open", (p) => {
        const view = viewFor(p.name);
        if (view !== null) env.openApp(view);
      }),
      env.onTrayAction((name) => client.send("action", { name })),
    ];
    return () => off.forEach((stop) => stop());
  }, [client, env]);

  // Sleep needs the clock, but only coarsely: once every 30 s is enough.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (look === null) return;
    env.applyAppearance(look.scale, look.click_through);
    env.setCaptureExclusion(look.exclude_from_capture);
  }, [look, env]);

  useEffect(() => {
    if (hidden) env.hide();
    else env.show();
  }, [hidden, env]);

  // Settles a quiet minute after the last thing that happened, to the
  // millisecond: the 30 s clock above is too coarse for that.
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    setSettled(false);
    const timer = setTimeout(() => setSettled(true), SETTLE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [lastActivity]);

  const scale = look?.scale ?? 1;
  const state = visualState({ mood, link, claude, idleMs: now - lastActivity });
  stats.state = state;
  stats.settled = settled;

  return (
    <div
      title={`Little Wizard — ${state}`}
      onMouseEnter={() => {
        stats.hovers += 1;
        setHover(true);
        setLastActivity(Date.now());
        setNow(Date.now());
      }}
      onMouseLeave={() => setHover(false)}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        press.current = { x: e.screenX, y: e.screenY, ctrl: e.ctrlKey };
        // Held by this window until released, even far outside its 72 px.
        if (e.ctrlKey) e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        const start = press.current;
        if (start === null || (e.buttons & 1) === 0) return;
        if (Math.hypot(e.screenX - start.x, e.screenY - start.y) <= DRAG_DISTANCE) return;
        if (start.ctrl) {
          setTargeting(true);
          return;
        }
        press.current = null;
        env.startDragging();
      }}
      onPointerUp={() => {
        const start = press.current;
        press.current = null;
        if (targeting) {
          setTargeting(false);
          // Where the pointer really is, in desktop pixels: exact on any
          // monitor, whatever its scale (screenX would not be).
          void env.cursorNow().then((at) => {
            if (at) client.send("capture.window", { x: at.x, y: at.y });
          });
          return;
        }
        // A Ctrl + click without moving is a slip, not a pick (as in Qt).
        if (start !== null && !start.ctrl) env.togglePanel();
      }}
      onContextMenu={(e) => {
        e.preventDefault(); // not WebView2's own menu
        env.showMenu();
      }}
      onPointerCancel={() => {
        press.current = null;
        setTargeting(false);
      }}
      style={{
        cursor: targeting ? "crosshair" : "pointer",
        width: "fit-content",
        opacity: look?.opacity ?? 1,
      }}
    >
      <div style={{ position: "relative" }}>
        <AvatarCanvas
          state={state}
          size={56 * scale}
          padding={8 * scale}
          hover={hover}
          settled={settled}
          guiding={guiding}
          active={!hidden}
          onPointer={env.onPointer}
        />
        {pending && (
          <CountdownRing
            deadline={pending.deadline}
            total={pending.total}
            size={72 * scale}
          />
        )}
      </div>
    </div>
  );
}
