/**
 * Paints one Pose: three flat shapes and a point of light (DESIGN.md
 * section 4). No gradients, no textures. Coordinates are figure units, the
 * figure 56 wide, drawn at `size` CSS pixels and the device's pixel ratio.
 */

import { figure as palette } from "../design/tokens";
import type { Pose } from "./pose";

export const FIGURE = 56;
/** The band of three motifs on the hat shows only from this size up. */
export const BAND_MIN_SIZE = 48;

const GROUND = 54; // where the face sits; breathing scales from here
const EYE_Y = 40;
const EYE_DX = 7;
const EYE_CX = 22;
const EYE_R = 5.2;
const PUPIL_R = 2.5;
const STAFF_X = 49;
const ORB_Y = 15;
const ORB_R = 4;

function hat(ctx: CanvasRenderingContext2D, sway: number, band: boolean): void {
  // A wide brim, then a cone whose tip bends: it leans with the breath.
  const tipX = 22 + 7 + sway * 60;
  ctx.fillStyle = palette.hat;
  ctx.beginPath();
  ctx.moveTo(4, 31);
  ctx.quadraticCurveTo(22, 26, 40, 31);
  ctx.lineTo(31, 26);
  ctx.quadraticCurveTo(27, 12, tipX, 3);
  ctx.quadraticCurveTo(19, 9, 13, 26);
  ctx.closePath();
  ctx.fill();

  if (!band) return;
  // Three small diamonds across the cone: the one cultural touch.
  ctx.fillStyle = palette.hatBand;
  for (const x of [17, 22, 27]) {
    ctx.beginPath();
    ctx.moveTo(x, 21.5);
    ctx.lineTo(x + 1.6, 23.2);
    ctx.lineTo(x, 24.9);
    ctx.lineTo(x - 1.6, 23.2);
    ctx.closePath();
    ctx.fill();
  }
}

function face(ctx: CanvasRenderingContext2D): void {
  ctx.fillStyle = palette.skin;
  ctx.beginPath();
  // A squircle is a rounded square with generous corners, at this size.
  ctx.roundRect(8, 28, 28, GROUND - 28, 11);
  ctx.fill();
}

function eye(ctx: CanvasRenderingContext2D, cx: number, p: Pose): void {
  const r = EYE_R * p.eyeScale;
  if (p.eyeOpen < 0.08) {
    // Closed: a lid line, curving down.
    ctx.strokeStyle = palette.pupil;
    ctx.lineWidth = 1.4;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(cx, EYE_Y - r * 0.4, r * 0.85, 0.2 * Math.PI, 0.8 * Math.PI);
    ctx.stroke();
    return;
  }
  ctx.save();
  ctx.beginPath();
  ctx.ellipse(cx, EYE_Y, r, r * p.eyeOpen, 0, 0, Math.PI * 2);
  ctx.fillStyle = palette.eyeWhite;
  ctx.fill();
  ctx.clip(); // the pupil never leaves the eye, even half-closed
  ctx.fillStyle = palette.pupil;
  ctx.beginPath();
  ctx.arc(cx + p.pupilX * r, EYE_Y + p.pupilY * r, PUPIL_R * p.eyeScale, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function staff(ctx: CanvasRenderingContext2D, p: Pose): void {
  ctx.strokeStyle = palette.staff;
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(STAFF_X - 1, GROUND);
  ctx.lineTo(STAFF_X, ORB_Y + ORB_R);
  ctx.stroke();

  ctx.save();
  if (p.orbIntensity > 0) {
    // A halo, not a gradient: the light the orb casts.
    ctx.shadowColor = p.orbColor;
    ctx.shadowBlur = 10 * p.orbIntensity;
    ctx.globalAlpha = 0.45 + 0.55 * p.orbIntensity;
    ctx.fillStyle = p.orbColor;
  } else {
    ctx.fillStyle = palette.orbOff;
  }
  ctx.beginPath();
  ctx.arc(STAFF_X, ORB_Y, ORB_R, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function sleep(ctx: CanvasRenderingContext2D, alpha: number): void {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = palette.eyeWhite;
  ctx.font = "600 9px system-ui, sans-serif";
  ctx.fillText("z", 38, 25);
  ctx.restore();
}

/** Clear the canvas and paint the figure, `size` CSS px wide, at `offset`. */
export function draw(
  ctx: CanvasRenderingContext2D,
  p: Pose,
  size: number,
  offset: { x: number; y: number } = { x: 0, y: 0 },
): void {
  const ratio = ctx.canvas.width / (ctx.canvas.clientWidth || ctx.canvas.width);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);

  const scale = (size / FIGURE) * ratio;
  ctx.setTransform(scale, 0, 0, scale, offset.x * ratio, offset.y * ratio);
  ctx.translate(p.shakeX, -p.liftY);

  staff(ctx, p);
  // Breathing scales the body from the ground up; the staff stays planted.
  ctx.save();
  ctx.translate(0, GROUND);
  ctx.scale(1, p.breath);
  ctx.translate(0, -GROUND);
  face(ctx);
  eye(ctx, EYE_CX - EYE_DX, p);
  eye(ctx, EYE_CX + EYE_DX, p);
  hat(ctx, p.hatSway, size >= BAND_MIN_SIZE);
  ctx.restore();
  if (p.zAlpha > 0) sleep(ctx, p.zAlpha);
}
