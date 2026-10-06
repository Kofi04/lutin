/**
 * The avatar on a canvas: a renderer, the device's pixel ratio, and the
 * pointer it looks at. Used by the avatar window and the playground gallery.
 */

import { useEffect, useRef } from "react";

import { stats } from "../debug";
import { prefersReducedMotion } from "../design/motion";
import { draw } from "./draw";
import { AvatarRenderer } from "./renderer";
import type { VisualState } from "./state";

export interface AvatarCanvasProps {
  state: VisualState;
  /** Width of the figure, CSS px (DESIGN.md section 4: 56). */
  size?: number;
  /** Room around the figure for the halo and the jumps. */
  padding?: number;
  hover?: boolean;
  /** The guide cursor is out: the orb is dark. */
  guiding?: boolean;
  /** A quiet minute has passed: breathing and blinking stop. */
  settled?: boolean;
  /** False stops every timer, as when the window is hidden. */
  active?: boolean;
  /** Subscribe to the pointer's moves; returns the unsubscribe. */
  onPointer?: (listener: (pointer: { dx: number; dy: number }) => void) => () => void;
}

export function AvatarCanvas({
  state,
  size = 56,
  padding = 8,
  hover = false,
  settled = false,
  guiding = false,
  active = true,
  onPointer,
}: AvatarCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<AvatarRenderer | null>(null);
  const box = size + 2 * padding;
  // Read by a renderer created later (a new size): it must start from the
  // current state, not from its default.
  const latest = useRef({ state, hover, settled });
  latest.current = { state, hover, settled };

  // One renderer per canvas size, running only while visible: a hidden
  // window costs nothing.
  useEffect(() => {
    const canvas = canvasRef.current!;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(box * ratio);
    canvas.height = Math.round(box * ratio);
    const ctx = canvas.getContext("2d")!;
    const renderer = new AvatarRenderer((p) => {
      draw(ctx, p, size, { x: padding, y: padding });
      stats.painted += 1;
    }, prefersReducedMotion);
    renderer.setState(latest.current.state);
    renderer.setHover(latest.current.hover);
    renderer.setSettled(latest.current.settled);
    rendererRef.current = renderer;

    const sync = () => {
      if (active && document.visibilityState === "visible") renderer.start();
      else renderer.stop();
    };
    sync();
    document.addEventListener("visibilitychange", sync);
    return () => {
      document.removeEventListener("visibilitychange", sync);
      renderer.stop();
    };
  }, [box, size, padding, active]);

  useEffect(() => rendererRef.current?.setState(state), [state]);
  useEffect(() => rendererRef.current?.setHover(hover), [hover]);
  useEffect(() => rendererRef.current?.setSettled(settled), [settled]);
  useEffect(() => rendererRef.current?.setGuiding(guiding), [guiding]);

  // The eyes listen to the pointer only when they can use it.
  const watching =
    active && onPointer !== undefined && state !== "asleep" && state !== "offline";
  useEffect(() => {
    if (!watching || onPointer === undefined) {
      rendererRef.current?.setPointer(null);
      return;
    }
    return onPointer((at) => rendererRef.current?.setPointer(at));
  }, [watching, onPointer]);

  return <canvas ref={canvasRef} style={{ width: box, height: box, display: "block" }} />;
}
