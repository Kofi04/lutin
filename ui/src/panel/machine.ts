/**
 * The panel's state machine (DESIGN.md section 5), as a pure reducer.
 *
 *   hidden ──open──▶ bar ──submit──▶ answer ──Esc──▶ hidden
 *     ├─approval.request─▶ approval ──answered──▶ previous view
 *     ├─capture.preview──▶ capture  ──confirmed─▶ bar, with the attachment
 *     └─selection.menu───▶ selection
 *
 * What it guarantees, and the tests pin down:
 * - an approval or a capture cannot be dismissed by clicking the avatar:
 *   silence would time it out unseen; Escape answers it (refuse, cancel);
 * - an answer keeps arriving while the panel is closed, and reopening shows it;
 * - the window stays up while toasts show, panel closed or not;
 * - only opening the panel to type takes the keyboard focus.
 */

import type { CorePayloads } from "../protocol";

export type View = "hidden" | "bar" | "answer" | "approval" | "capture" | "selection";

/** Views that come and go on their own and return to the previous one. */
const INTERRUPTIONS: ReadonlySet<View> = new Set(["approval", "capture", "selection"]);

export const TOAST_MS = 4000;
export const MAX_TOASTS = 3;

export interface Toast {
  id: number;
  title: string;
  body: string;
  kind: CorePayloads["toast"]["kind"];
}

export interface Answer {
  /** The question that produced it, for the panel's header. */
  question: string;
  text: string;
  status: string;
  streaming: boolean;
  error: string | null;
  /** A resumed conversation, shown above the new answer. */
  context: string | null;
}

export interface Selection {
  id: string;
  preview: string;
  actions: CorePayloads["selection.menu"]["actions"];
  phase: "menu" | "working" | "done" | "error";
  action: string;
  text: string;
  replaces: boolean;
}

export interface PanelState {
  view: View;
  /** Where an interruption returns to. */
  back: View;
  /** Take the keyboard focus when shown: only to type. */
  focus: boolean;
  attachment: NonNullable<CorePayloads["panel.open"]["capture"]> | null;
  answer: Answer | null;
  approval: CorePayloads["approval.request"] | null;
  preview: CorePayloads["capture.preview"] | null;
  selection: Selection | null;
  toasts: Toast[];
  nextToast: number;
  /** A tutorial on screen: its steps, for Previous / Next (DESIGN.md section 6). */
  guide: { texts: string[]; index: number } | null;
  /** Bumped by the palette hotkey: the bar opens anew (a new key)... */
  palette: number;
  /** ...with this already typed: "/" after the palette, "" otherwise. */
  prefill: string;
}

export const initial: PanelState = {
  view: "hidden",
  back: "hidden",
  focus: false,
  attachment: null,
  answer: null,
  approval: null,
  preview: null,
  selection: null,
  toasts: [],
  nextToast: 1,
  guide: null,
  palette: 0,
  prefill: "",
};

export type PanelEvent =
  // From the core.
  | { type: "panel.open"; payload: CorePayloads["panel.open"] }
  | { type: "stream.start" }
  | { type: "stream.chunk"; text: string }
  | { type: "stream.status"; text: string }
  | { type: "stream.reset" }
  | { type: "stream.end"; status: string }
  | { type: "stream.error"; message: string }
  | { type: "approval.request"; payload: CorePayloads["approval.request"] }
  | { type: "approval.cancel"; requestId: string }
  | { type: "capture.preview"; payload: CorePayloads["capture.preview"] }
  | { type: "selection.menu"; payload: CorePayloads["selection.menu"] }
  | { type: "selection.result"; payload: CorePayloads["selection.result"] }
  | { type: "toast"; payload: CorePayloads["toast"] }
  | { type: "guide.steps"; texts: string[] }
  | { type: "guide.clear" }
  | { type: "guide.step"; index: number }
  // From the user.
  | { type: "toggle" }
  | { type: "palette" }
  | { type: "escape" }
  | { type: "submit"; question: string }
  | { type: "approval.answered" }
  | { type: "capture.decided" }
  | { type: "attachment.remove" }
  | { type: "conversation.new" }
  | { type: "selection.picked"; action: string }
  | { type: "toast.dismiss"; id: number };

/** Show an interruption, remembering where to come back to. */
function interrupt(state: PanelState, view: View): PanelState {
  const back = INTERRUPTIONS.has(state.view) ? state.back : state.view;
  return { ...state, view, back, focus: false };
}

/** Leave an interruption. */
function resume(state: PanelState): PanelState {
  // Another interruption may still be pending: an approval that arrived
  // while a capture was shown, say.
  if (state.approval) return { ...state, view: "approval" };
  if (state.preview) return { ...state, view: "capture" };
  return { ...state, view: state.back, back: "hidden", focus: false };
}

function blankAnswer(question: string): Answer {
  return { question, text: "", status: "", streaming: true, error: null, context: null };
}

export function reduce(state: PanelState, event: PanelEvent): PanelState {
  switch (event.type) {
    case "panel.open": {
      const { state: view, capture, context, status } = event.payload;
      const next: PanelState = {
        ...state,
        attachment: capture ?? state.attachment,
        focus: true,
        prefill: "",
      };
      if (view === "answer") {
        next.answer = {
          ...blankAnswer(""),
          streaming: false,
          context: context ?? null,
          status: status ?? "",
        };
      }
      if (INTERRUPTIONS.has(state.view) && state.view !== "capture") {
        // Never cover a pending question: open behind it.
        return { ...next, back: view };
      }
      return { ...next, view, back: "hidden" };
    }

    case "stream.start":
      return {
        ...state,
        // An answer starting under the bar shows; a closed panel stays closed.
        view: state.view === "bar" ? "answer" : state.view,
        answer: {
          ...(state.answer ?? blankAnswer("")),
          text: "",
          streaming: true,
          error: null,
        },
      };
    case "stream.chunk":
      if (!state.answer) return state;
      return {
        ...state,
        answer: { ...state.answer, text: state.answer.text + event.text },
      };
    case "stream.status":
      if (!state.answer) return state;
      return { ...state, answer: { ...state.answer, status: event.text } };
    case "stream.reset":
      if (!state.answer) return state;
      return { ...state, answer: { ...state.answer, text: "" } };
    case "stream.end":
      if (!state.answer) return state;
      return {
        ...state,
        answer: { ...state.answer, streaming: false, status: event.status },
      };
    case "stream.error":
      if (!state.answer) return state;
      return {
        ...state,
        answer: { ...state.answer, streaming: false, error: event.message },
      };

    case "approval.request":
      return interrupt({ ...state, approval: event.payload }, "approval");
    case "approval.cancel":
      if (state.approval?.request_id !== event.requestId) return state;
      return state.view === "approval"
        ? resume({ ...state, approval: null })
        : { ...state, approval: null };
    case "approval.answered":
      return resume({ ...state, approval: null });

    case "capture.preview":
      if (state.view === "approval") return { ...state, preview: event.payload };
      return interrupt({ ...state, preview: event.payload }, "capture");
    case "capture.decided":
      return resume({ ...state, preview: null });

    case "selection.menu":
      return interrupt(
        {
          ...state,
          selection: {
            id: event.payload.selection_id,
            preview: event.payload.preview,
            actions: event.payload.actions,
            phase: "menu",
            action: "",
            text: "",
            replaces: false,
          },
        },
        "selection",
      );
    case "selection.picked":
      if (!state.selection) return state;
      return {
        ...state,
        selection: { ...state.selection, phase: "working", action: event.action },
      };
    case "selection.result": {
      const { selection } = state;
      if (!selection || selection.id !== event.payload.selection_id) return state;
      return {
        ...state,
        selection: {
          ...selection,
          phase: event.payload.status,
          text: event.payload.text,
          action: event.payload.action || selection.action,
          replaces: event.payload.replaces,
        },
      };
    }

    case "toast": {
      const toast = { id: state.nextToast, ...event.payload };
      // The newest on top, three at most: the oldest goes.
      const toasts = [toast, ...state.toasts].slice(0, MAX_TOASTS);
      return { ...state, toasts, nextToast: state.nextToast + 1 };
    }
    case "guide.steps":
      return {
        ...state,
        guide: event.texts.length ? { texts: event.texts, index: 0 } : null,
      };
    case "guide.step":
      if (!state.guide) return state;
      return {
        ...state,
        guide: {
          ...state.guide,
          index: Math.min(Math.max(0, event.index), state.guide.texts.length - 1),
        },
      };
    case "guide.clear":
      return { ...state, guide: null };

    case "toast.dismiss":
      return { ...state, toasts: state.toasts.filter((t) => t.id !== event.id) };

    case "palette": {
      const palette = state.palette + 1;
      // Never cover a pending question: open behind it, as panel.open does.
      const opened = { ...state, palette, prefill: "/" };
      if (INTERRUPTIONS.has(state.view)) return { ...opened, back: "bar" };
      return { ...opened, view: "bar", back: "hidden", focus: true };
    }

    case "toggle":
      if (state.view === "approval" || state.view === "capture") return state;
      if (state.view !== "hidden") return { ...state, view: "hidden", focus: false };
      return {
        ...state,
        view: state.answer ? "answer" : "bar",
        focus: true,
        prefill: "",
      };

    case "escape":
      switch (state.view) {
        // Escape on these is an answer (refuse, cancel): the view sends it,
        // then reports approval.answered / capture.decided.
        case "approval":
        case "capture":
          return state;
        case "selection":
          return resume({ ...state, selection: null });
        default:
          return { ...state, view: "hidden", focus: false };
      }

    case "submit":
      return {
        ...state,
        view: "answer",
        attachment: null,
        answer: blankAnswer(event.question),
      };
    case "attachment.remove":
      return { ...state, attachment: null };
    case "conversation.new":
      return { ...state, view: "bar", answer: null, attachment: null, focus: true };
  }
}

/** The window is on screen for a view, or for toasts alone. */
export function windowVisible(state: PanelState): boolean {
  return state.view !== "hidden" || state.toasts.length > 0 || state.guide !== null;
}
