/**
 * The messages exchanged with the Python core, typed and checked.
 *
 * The list of messages lives in src/wizard/protocol_messages.json, read by
 * protocol.py too. The payload types below are written by hand, and a
 * compile-time check refuses any difference between them and that file: a
 * message added on one side and forgotten on the other does not build.
 */

import spec from "../../src/wizard/protocol_messages.json";

export const PROTOCOL_VERSION = 1;

export type Mood =
  "calm" | "busy" | "stressed" | "tired" | "working" | "waiting" | "done" | "error";
export type Decision = "allow" | "always" | "deny";
export type Role = "avatar" | "panel" | "overlay" | "settings" | "history" | "dev";
export type ToastKind = "info" | "success" | "warning" | "error";
export type CaptureKind = "region" | "window" | "file" | "screen";
export type ActionName =
  | "ask"
  | "capture.region"
  | "capture.screen"
  | "capture.text"
  | "selection"
  | "conversation.reset"
  | "config.reload"
  | "config.open_folder"
  | "quit";
export type WindowName =
  | "quick_note"
  | "clipboard"
  | "notes"
  | "reminder"
  | "palette"
  | "settings"
  | "history"
  | "agent"
  | "hooks.install"
  | "hooks.uninstall"
  | "onboarding";

/** A point on one screen, in logical pixels from its top-left corner. */
export interface ScreenPoint {
  screen_id: string;
  x: number;
  y: number;
  label: string;
}

export interface ScreenBox extends ScreenPoint {
  width: number;
  height: number;
  shape: "rect" | "ellipse";
}

export interface GuideStep {
  text: string;
  target: (ScreenPoint & { kind: "point" }) | (ScreenBox & { kind: "highlight" }) | null;
}

export interface SessionInfo {
  id: string;
  label: string;
  colour: string;
  state: string;
  last_action: string;
  agent_id?: number;
  running?: boolean;
  report?: string;
}

export interface SelectionChoice {
  key: string;
  label: string;
  replaces: boolean;
}

/** What the UI sends. */
export interface UiPayloads {
  hello: { token: string; protocol: number; role: Role; pid?: number };
  ping: Record<string, never>;
  ask: { text: string; capture_id?: string };
  "ask.cancel": Record<string, never>;
  "approval.answer": { request_id: string; decision: Decision };
  "capture.start": { mode: "region" | "screen" | "text" };
  "capture.region": {
    mode: "ask" | "text";
    screen_id: string;
    x: number;
    y: number;
    width: number;
    height: number;
  };
  "capture.file": { path: string };
  "capture.confirm": { capture_id: string };
  "capture.cancel": { capture_id?: string };
  "selection.pick": { selection_id: string; action: string };
  "selection.replace": { selection_id: string; text: string };
  "selection.copy": { text: string };
  "agent.start": { task: string; folder: string };
  "agent.stop": { agent_id: number };
  "session.dismiss": { session_id: string };
  "guide.active": { active: boolean };
  "guide.done": Record<string, never>;
  "cloak.ack": { cloak_id: string };
  action: { name: ActionName };
}

/** What the core sends. */
export interface CorePayloads {
  "hello.ok": { protocol: number; version: string; pid: number };
  reply: { ok: boolean; data?: Record<string, unknown> };
  error: { error: string; message: string };
  mood: { mood: Mood };
  connection: { state: string; detail: string };
  system: { cpu: number; memory: number; battery?: number; charging?: boolean };
  quiet: { on: boolean };
  "avatar.toggle": Record<string, never>;
  "panel.open": {
    state: "bar" | "answer";
    capture?: { capture_id: string; label: string; width: number; height: number };
    context?: string;
    status?: string;
  };
  "stream.start": Record<string, never>;
  "stream.chunk": { text: string };
  "stream.status": { text: string };
  "stream.reset": Record<string, never>;
  "stream.end": { status: string };
  "stream.error": { message: string };
  "approval.request": {
    request_id: string;
    tool: string;
    detail: string;
    project: string;
    timeout_seconds: number;
  };
  "approval.cancel": { request_id: string };
  "capture.select": { mode: "ask" | "text" };
  "capture.preview": {
    capture_id: string;
    kind: CaptureKind;
    label: string;
    width: number;
    height: number;
    tokens: number;
    png_base64: string;
  };
  "selection.menu": { selection_id: string; preview: string; actions: SelectionChoice[] };
  "selection.result": {
    selection_id: string;
    action: string;
    status: "working" | "done" | "error";
    text: string;
    replaces: boolean;
  };
  "sessions.update": { sessions: SessionInfo[] };
  toast: { title: string; body: string; kind: ToastKind };
  "guide.point": ScreenPoint;
  "guide.highlight": ScreenBox;
  "guide.steps": { steps: GuideStep[] };
  "guide.clear": Record<string, never>;
  "cloak.hide": { cloak_id: string };
  "cloak.show": { cloak_id: string };
  "window.open": { name: WindowName };
}

export type UiType = keyof UiPayloads;
export type CoreType = keyof CorePayloads;
export type MessageType = UiType | CoreType;

export type CoreMessage = {
  [K in CoreType]: { type: K; id?: string; payload: CorePayloads[K] };
}[CoreType];
export type UiMessage = {
  [K in UiType]: { type: K; id?: string; payload: UiPayloads[K] };
}[UiType];

// -- the compile-time check against protocol_messages.json -------------------

type SpecType = keyof typeof spec.messages;
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
const sameTypes: Same<SpecType, MessageType> = true;
void sameTypes;

/** Every type each side sends, listed exhaustively (the compiler checks). */
const UI_TYPES = Object.keys({
  hello: 1,
  ping: 1,
  ask: 1,
  "ask.cancel": 1,
  "approval.answer": 1,
  "capture.start": 1,
  "capture.region": 1,
  "capture.file": 1,
  "capture.confirm": 1,
  "capture.cancel": 1,
  "selection.pick": 1,
  "selection.replace": 1,
  "selection.copy": 1,
  "agent.start": 1,
  "agent.stop": 1,
  "session.dismiss": 1,
  "guide.active": 1,
  "guide.done": 1,
  "cloak.ack": 1,
  action: 1,
} satisfies Record<UiType, 1>) as UiType[];

export const uiTypes: readonly UiType[] = UI_TYPES;

// -- runtime validation, the same rules as protocol.py ------------------------

export type Sender = "core" | "ui";

export class ProtocolError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ProtocolError";
  }
}

type FieldKind = string | string[];
interface SpecEntry {
  from: string;
  payload: Record<string, FieldKind>;
}
const MESSAGES = spec.messages as unknown as Record<string, SpecEntry>;

if (spec.version !== PROTOCOL_VERSION) {
  throw new Error("protocol_messages.json and PROTOCOL_VERSION disagree");
}

const CHECKS: Record<string, (v: unknown) => boolean> = {
  string: (v) => typeof v === "string",
  integer: (v) => typeof v === "number" && Number.isInteger(v),
  number: (v) => typeof v === "number" && Number.isFinite(v),
  boolean: (v) => typeof v === "boolean",
  object: (v) => typeof v === "object" && v !== null && !Array.isArray(v),
  array: (v) => Array.isArray(v),
};

function isObject(v: unknown): v is Record<string, unknown> {
  return CHECKS.object!(v);
}

/** Throws ProtocolError unless `payload` is a valid `type` from `sender`. */
export function validate(type: string, payload: unknown, sender: Sender): void {
  const entry = Object.hasOwn(MESSAGES, type) ? MESSAGES[type] : undefined;
  if (entry === undefined) {
    throw new ProtocolError("unknown_type", `unknown message type: ${type}`);
  }
  if (entry.from !== sender) {
    throw new ProtocolError("wrong_direction", `${type} is not sent by the ${sender}`);
  }
  if (!isObject(payload)) {
    throw new ProtocolError("bad_payload", `${type}: payload must be an object`);
  }
  const extra = Object.keys(payload).filter((k) => !Object.hasOwn(entry.payload, k));
  if (extra.length > 0) {
    throw new ProtocolError("bad_payload", `${type}: unknown field(s) ${extra.sort()}`);
  }
  for (const [name, kind] of Object.entries(entry.payload)) {
    const optional = typeof kind === "string" && kind.endsWith("?");
    const value = payload[name];
    if (value === undefined || value === null) {
      if (optional) continue;
      throw new ProtocolError("bad_payload", `${type}: missing field ${name}`);
    }
    if (Array.isArray(kind)) {
      if (typeof value !== "string" || !kind.includes(value)) {
        throw new ProtocolError("bad_payload", `${type}.${name}: not one of ${kind}`);
      }
    } else if (!CHECKS[kind.replace(/\?$/, "")]!(value)) {
      throw new ProtocolError("bad_payload", `${type}.${name}: expected ${kind}`);
    }
  }
}

/** Parse and validate one message received from `sender` (normally the core). */
export function decode(text: string, sender: "core"): CoreMessage;
export function decode(text: string, sender: "ui"): UiMessage;
export function decode(text: string, sender: Sender): CoreMessage | UiMessage {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (error) {
    throw new ProtocolError("bad_json", `not valid JSON: ${String(error)}`);
  }
  if (!isObject(data)) {
    throw new ProtocolError("bad_envelope", "a message must be a JSON object");
  }
  const extra = Object.keys(data).filter((k) => !["type", "id", "payload"].includes(k));
  if (extra.length > 0) {
    throw new ProtocolError("bad_envelope", `unknown envelope field(s) ${extra}`);
  }
  if (typeof data.type !== "string") {
    throw new ProtocolError("bad_envelope", "missing or invalid 'type'");
  }
  if (data.id !== undefined && data.id !== null && typeof data.id !== "string") {
    throw new ProtocolError("bad_envelope", "'id' must be a string");
  }
  const payload = data.payload ?? {};
  validate(data.type, payload, sender);
  const message: { type: string; id?: string; payload: unknown } = {
    type: data.type,
    payload,
  };
  if (typeof data.id === "string") message.id = data.id;
  return message as CoreMessage | UiMessage;
}

/** A UI message, validated before it leaves: a malformed one is our bug. */
export function encode<K extends UiType>(
  type: K,
  payload: UiPayloads[K],
  id?: string,
): string {
  validate(type, payload, "ui");
  return JSON.stringify(id === undefined ? { type, payload } : { type, id, payload });
}
