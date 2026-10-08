/**
 * One overlay window: the guide cursor, on this window's screen (DESIGN.md
 * section 6).
 *
 * Every overlay runs the same reducer on the same events and draws only what
 * falls on its own screen. It is shown only while there is something to
 * draw, and listens to the pointer only while the cursor stays beside it:
 * at rest an overlay costs nothing.
 */

import { motion } from "motion/react";
import { useEffect, useReducer, useRef, useState } from "react";

import type { CoreClient } from "../core/client";
import { prefersReducedMotion, springs } from "../design/motion";
import type { CorePayloads, ScreenPoint } from "../protocol";
import type { WindowEnv } from "../windows/env";
import { type Monitor, monitorAt, type Point, screenToOverlay } from "./coords";
import { type FlightFrame, frameAt, plan } from "./flight";
import "./guide.css";
import {
  type GuideState,
  initialGuide,
  LINGER_MS,
  onScreen,
  POINTING_MS,
  reduceGuide,
  type Spot,
  type Step,
  type Target,
} from "./machine";

/** A flight between two screens is a fade, not a curve across the gap. */
const CROSS_FADE_MS = 350;

function pointTarget(p: ScreenPoint): Target {
  return { screen: p.screen_id, x: p.x, y: p.y, label: p.label };
}

function boxTarget(p: CorePayloads["guide.highlight"]): Target {
  // The cursor lands in the middle of the area it shows.
  return {
    screen: p.screen_id,
    x: p.x + p.width / 2,
    y: p.y + p.height / 2,
    label: p.label,
    box: { width: p.width, height: p.height, shape: p.shape },
  };
}

function stepsFrom(payload: CorePayloads["guide.steps"]): Step[] {
  return payload.steps.map((step) => ({
    text: step.text,
    target:
      step.target === null
        ? null
        : step.target.kind === "highlight"
          ? boxTarget(step.target)
          : pointTarget(step.target),
  }));
}

/** The arrow: its tip at (0, 0), 22 px tall. */
function Arrow({
  className = "",
  opacity = 1,
}: {
  className?: string;
  opacity?: number;
}) {
  return (
    <svg
      className={`lw-guide-cursor ${className}`}
      viewBox="0 0 22 22"
      style={{ opacity }}
    >
      <path d="M1.5 1.5 L1.5 18 L6 13.8 L9.2 20.5 L12.2 19.1 L9.1 12.6 L15.2 12.6 Z" />
    </svg>
  );
}

/** Frames of a flight, painted only while it lasts. */
function useFlight(
  from: Spot | null,
  to: Spot | null,
  active: boolean,
): FlightFrame | null {
  const [frame, setFrame] = useState<FlightFrame | null>(null);
  useEffect(() => {
    if (!active || !from || !to || from.screen !== to.screen) {
      setFrame(null);
      return;
    }
    const flight = plan(from, to);
    const trail = !prefersReducedMotion();
    const start = performance.now();
    let handle = 0;
    const step = () => {
      const next = frameAt(flight, performance.now() - start, trail);
      setFrame(next);
      if (!next.done) handle = requestAnimationFrame(step);
    };
    handle = requestAnimationFrame(step);
    return () => cancelAnimationFrame(handle);
  }, [active, from, to]);
  return frame;
}

export function GuideCursor({
  client,
  env,
  screenId,
  held = false,
}: {
  client: CoreClient;
  env: WindowEnv;
  screenId: string;
  /** Something else on this overlay needs the window shown (the zone veil). */
  held?: boolean;
}) {
  const [state, dispatch] = useReducer(reduceGuide, initialGuide);
  const stateRef = useRef<GuideState>(state);
  stateRef.current = state;
  const monitors = useRef<Monitor[]>([]);

  useEffect(() => {
    void env.monitors().then((list) => (monitors.current = list));
  }, [env]);

  /** A physical desktop point, as a place on its screen. */
  const spot = (point: Point | null): Spot | null => {
    if (!point) return null;
    const monitor = monitorAt(point, monitors.current);
    return monitor ? { screen: monitor.id, ...screenToOverlay(point, monitor) } : null;
  };
  const avatarSpot = async () => spot(await env.avatarAnchor());

  // -- events: the core, the panel, the pointer --------------------------
  useEffect(() => {
    const off = [
      client.on("stream.start", async () => {
        if (!stateRef.current.pointer) {
          const at = spot(await env.cursorNow());
          if (at) dispatch({ type: "pointer", at });
        }
        dispatch({ type: "stream.start" });
      }),
      client.on("stream.chunk", (p) => dispatch({ type: "stream.chunk", text: p.text })),
      client.on("stream.end", () => dispatch({ type: "stream.end" })),
      client.on("stream.error", () => dispatch({ type: "stream.end" })),
      client.on("guide.point", async (p) =>
        dispatch({ type: "point", target: pointTarget(p), origin: await avatarSpot() }),
      ),
      client.on("guide.highlight", async (p) =>
        dispatch({ type: "point", target: boxTarget(p), origin: await avatarSpot() }),
      ),
      client.on("guide.steps", async (p) =>
        dispatch({ type: "steps", steps: stepsFrom(p), origin: await avatarSpot() }),
      ),
      client.on("guide.clear", () => dispatch({ type: "clear" })),
      env.onBroadcast("panel", (open) =>
        dispatch({ type: "panel", open: Boolean(open) }),
      ),
      env.onBroadcast("guide.step", (index) =>
        dispatch({ type: "step", index: Number(index) }),
      ),
    ];
    return () => off.forEach((stop) => stop());
  }, [client, env]);

  const following = ["follow", "thinking", "talking", "returning"].includes(state.mode);
  useEffect(() => {
    if (!following) return;
    return env.onCursor((point) => {
      const at = spot(point);
      if (at) dispatch({ type: "pointer", at });
    });
  }, [following, env]);

  // -- timers, reported as events --------------------------------------
  useEffect(() => {
    const { mode, from, at } = state;
    const still = prefersReducedMotion();
    let delay: number | null = null;
    let event: Parameters<typeof dispatch>[0] | null = null;
    if (mode === "flying" || mode === "returning") {
      event = { type: mode === "flying" ? "landed" : "returned" };
      delay =
        still || !from || !at
          ? 0
          : from.screen !== at.screen
            ? CROSS_FADE_MS
            : plan(from, at).durationMs;
    } else if (mode === "follow") {
      event = { type: "linger.end" };
      delay = LINGER_MS; // restarted by every move: `at` changes
    } else if (mode === "pointing") {
      event = { type: "pointing.end" };
      delay = POINTING_MS;
    }
    if (event === null || delay === null) return;
    // A target nobody cleared: tell the core, once (the overlay of the
    // target's screen), so it lets Escape go and every window clears,
    // the avatar's orb included.
    const tellCore = mode === "pointing" && at?.screen === screenId;
    const timer = setTimeout(() => {
      dispatch(event);
      if (tellCore) client.send("guide.done", {});
    }, delay);
    return () => clearTimeout(timer);
  }, [state.mode, state.from, state.at, client, screenId]);

  // -- the window --------------------------------------------------------
  const visible = onScreen(state, screenId);
  useEffect(() => {
    if (visible) void env.syncOverlays().then(() => env.show());
    else if (!held) env.hide();
  }, [visible, held, env]);

  const flying = state.mode === "flying" || state.mode === "returning";
  const frame = useFlight(state.from, state.at, flying);
  if (!visible || !state.at) return null;

  const here = state.at.screen === screenId;
  const leaving = flying && state.from?.screen === screenId && !here;
  const target = state.target;
  const step = state.steps[state.step];

  return (
    <div className="lw-guide-layer">
      {target?.box &&
        target.screen === screenId &&
        (state.mode === "pointing" || state.mode === "steps") && (
          <div
            className={`lw-guide-highlight ${target.box.shape === "ellipse" ? "ellipse" : ""}`}
            style={{
              left: target.x - target.box.width / 2,
              top: target.y - target.box.height / 2,
              width: target.box.width,
              height: target.box.height,
            }}
          />
        )}

      {leaving && state.from && (
        // Off to another screen: fade out where it was.
        <motion.div
          style={{ position: "absolute", left: state.from.x, top: state.from.y }}
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: CROSS_FADE_MS / 1000 }}
        >
          <Arrow />
        </motion.div>
      )}

      {here && frame && (
        <>
          {frame.ghosts.map((ghost, i) => (
            <div key={i} style={{ position: "absolute", left: ghost.x, top: ghost.y }}>
              <Arrow className="lw-guide-ghost" opacity={0.4 - i * 0.09} />
            </div>
          ))}
          <div
            style={{
              position: "absolute",
              left: frame.at.x,
              top: frame.at.y,
              transform: `rotate(${frame.angle}rad)`,
              transformOrigin: "0 0",
            }}
          >
            <Arrow />
          </div>
        </>
      )}

      {here && !frame && (
        <motion.div
          style={{ position: "absolute", left: 0, top: 0 }}
          initial={{ x: state.at.x, y: state.at.y, opacity: 0 }}
          animate={{ x: state.at.x, y: state.at.y, opacity: 1 }}
          // Beside the pointer, a little behind it (DESIGN.md: snappy).
          transition={{ type: "spring", ...springs.snappy, opacity: { duration: 0.15 } }}
        >
          <Arrow />
          {state.mode === "thinking" && (
            <div className="lw-guide-dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          )}
          {state.mode === "talking" && state.bubble && (
            <div className="lw-guide-bubble">{state.bubble}</div>
          )}
          {(state.mode === "pointing" || state.mode === "steps") && (
            <>
              <div className="lw-guide-ring" />
              {(state.mode === "steps" && step) || target?.label ? (
                <div className="lw-guide-label">
                  {state.mode === "steps" && step
                    ? `${state.step + 1}/${state.steps.length} · ${step.text}`
                    : target!.label}
                </div>
              ) : null}
            </>
          )}
        </motion.div>
      )}
    </div>
  );
}
