/**
 * The panel window (DESIGN.md section 5): one surface, several states,
 * driven by the reducer in machine.ts.
 *
 * The window follows its content: when it grows, it takes its final size
 * first and the content animates inside it; when it shrinks, the content
 * animates first and the window follows. Never a window resized frame by
 * frame (DESIGN.md section 5).
 */

import { AnimatePresence, MotionConfig, motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import type { CoreClient } from "../core/client";
import { springs } from "../design/motion";
import type { ActionName } from "../protocol";
import type { WindowEnv } from "../windows/env";
import { initial, reduce, TOAST_MS, windowVisible } from "./machine";
import "./panel.css";
import {
  AnswerView,
  ApprovalView,
  Bar,
  CaptureView,
  SelectionView,
  ToastView,
  StepsCard,
  type SlashItem,
} from "./views";

/** "/" entries that open a view of the app window (ui_palette.py had them). */
const VIEW_ITEMS: [string, string][] = [
  ["notes/new", "Note rapide"],
  ["clipboard", "Presse-papiers"],
  ["notes", "Notes"],
  ["reminders", "Me rappeler…"],
  ["history", "Historique des discussions"],
  ["agent", "Lancer un agent…"],
  ["settings", "Paramètres…"],
];

/** Space around the surface for its shadow, as in panel.css. */
const MARGIN = 16;
/** How long the content takes to leave before the window shrinks. */
const EXIT_MS = 180;

const enter = { opacity: 1, scale: 1, y: 0 };
const hidden = { opacity: 0, scale: 0.96, y: 6 };

export function Panel({ client, env }: { client: CoreClient; env: WindowEnv }) {
  const [state, dispatch] = useReducer(reduce, initial);
  const content = useRef<HTMLDivElement>(null);
  const size = useRef({ width: 0, height: 0 });
  const shrinkTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // -- the core's events ---------------------------------------------------
  useEffect(() => {
    const off = [
      client.on("panel.open", (payload) => dispatch({ type: "panel.open", payload })),
      client.on("stream.start", () => dispatch({ type: "stream.start" })),
      client.on("stream.chunk", (p) => dispatch({ type: "stream.chunk", text: p.text })),
      client.on("stream.status", (p) =>
        dispatch({ type: "stream.status", text: p.text }),
      ),
      client.on("stream.reset", () => dispatch({ type: "stream.reset" })),
      client.on("stream.end", (p) => dispatch({ type: "stream.end", status: p.status })),
      client.on("stream.error", (p) =>
        dispatch({ type: "stream.error", message: p.message }),
      ),
      client.on("approval.request", (payload) =>
        dispatch({ type: "approval.request", payload }),
      ),
      client.on("approval.cancel", (p) =>
        dispatch({ type: "approval.cancel", requestId: p.request_id }),
      ),
      client.on("capture.preview", (payload) =>
        dispatch({ type: "capture.preview", payload }),
      ),
      client.on("selection.menu", (payload) =>
        dispatch({ type: "selection.menu", payload }),
      ),
      client.on("selection.result", (payload) =>
        dispatch({ type: "selection.result", payload }),
      ),
      client.on("toast", (payload) => dispatch({ type: "toast", payload })),
      client.on("guide.steps", (p) =>
        dispatch({ type: "guide.steps", texts: p.steps.map((step) => step.text) }),
      ),
      client.on("guide.clear", () => dispatch({ type: "guide.clear" })),
      env.onPanelToggle(() => dispatch({ type: "toggle" })),
      client.on("window.open", (p) => {
        if (p.name === "palette") dispatch({ type: "palette" });
      }),
    ];
    return () => off.forEach((stop) => stop());
  }, [client, env]);

  // The launcher entries of config.toml, asked for each time the bar opens:
  // a config reload may have changed them.
  const [launchers, setLaunchers] = useState<{ index: number; label: string }[]>([]);
  const barOpen = state.view === "bar";
  useEffect(() => {
    if (!barOpen) return;
    client
      .request<{ items: { index: number; label: string }[] }>("launcher.list")
      .then((r) => setLaunchers(r.items))
      .catch(() => setLaunchers([]));
  }, [client, barOpen]);
  const slashExtra = useMemo<SlashItem[]>(
    () => [
      ...VIEW_ITEMS.map(([view, label]) => ({
        key: `view:${view}`,
        label,
        run: () => {
          env.openApp(view);
          dispatch({ type: "escape" });
        },
      })),
      ...launchers.map((entry) => ({
        key: `launch:${entry.index}`,
        label: `Lancer ${entry.label}`,
        run: () => {
          void client.request("launcher.run", { index: entry.index }).catch(() => {});
          dispatch({ type: "escape" });
        },
      })),
    ],
    [client, env, launchers],
  );

  // -- answers to send ------------------------------------------------------
  const send = client.send.bind(client);
  const ask = (text: string) => {
    const payload = state.attachment
      ? { text, capture_id: state.attachment.capture_id }
      : { text };
    if (send("ask", payload)) dispatch({ type: "submit", question: text });
    else
      dispatch({
        type: "toast",
        payload: {
          title: "Cœur déconnecté",
          body: "La question n'est pas partie.",
          kind: "warning",
        },
      });
  };
  const action = (name: ActionName) => {
    send("action", { name });
    if (name === "conversation.reset") dispatch({ type: "conversation.new" });
  };
  const copy = (text: string) => send("selection.copy", { text });
  const decideApproval = useCallback(
    (decision: "allow" | "always" | "deny") => {
      if (!state.approval) return;
      client.send("approval.answer", { request_id: state.approval.request_id, decision });
      dispatch({ type: "approval.answered" });
    },
    [client, state.approval],
  );
  const decideCapture = useCallback(
    (confirm: boolean) => {
      if (!state.preview) return;
      const capture_id = state.preview.capture_id;
      if (confirm) client.send("capture.confirm", { capture_id });
      else client.send("capture.cancel", { capture_id });
      dispatch({ type: "capture.decided" });
    },
    [client, state.preview],
  );

  // -- the keyboard ---------------------------------------------------------
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        // Escape always closes; on a question it is the safe answer.
        if (state.view === "approval") decideApproval("deny");
        else if (state.view === "capture") decideCapture(false);
        else dispatch({ type: "escape" });
      } else if (event.key === "Enter" && state.view === "approval") {
        event.preventDefault();
        decideApproval("allow");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.view, decideApproval, decideCapture]);

  // -- the window -----------------------------------------------------------
  // The overlays show the answer beside the pointer only while the panel is
  // closed: one surface at a time (DESIGN.md principle 1).
  const open = state.view !== "hidden";
  useEffect(() => env.broadcast("panel", open), [open, env]);

  const goToStep = (index: number) => {
    dispatch({ type: "guide.step", index });
    env.broadcast("guide.step", index);
  };

  const visible = windowVisible(state);
  useEffect(() => {
    if (visible)
      env.showPanel(state.focus && (state.view === "bar" || state.view === "answer"));
    else env.hide();
  }, [visible, state.view, state.focus, env]);

  useLayoutEffect(() => {
    const element = content.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      const width = Math.ceil(element.offsetWidth) + 2 * MARGIN;
      const height = Math.ceil(element.offsetHeight) + 2 * MARGIN;
      const previous = size.current;
      if (width === previous.width && height === previous.height) return;
      if (shrinkTimer.current) clearTimeout(shrinkTimer.current);
      const apply = () => {
        size.current = { width, height };
        void env.placePanel(width, height);
      };
      // Grow at once, so the content animates into room it already has;
      // shrink after the content has left.
      if (width >= previous.width && height >= previous.height) apply();
      else shrinkTimer.current = setTimeout(apply, EXIT_MS);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [env]);

  const view = state.view;
  return (
    <MotionConfig reducedMotion="user" transition={{ type: "spring", ...springs.smooth }}>
      <div className="lw-panel-window">
        <div
          ref={content}
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: "var(--lw-space-2)",
          }}
        >
          <AnimatePresence initial={false}>
            {state.toasts.map((toast) => (
              <motion.div
                key={`toast-${toast.id}`}
                layout
                initial={hidden}
                animate={enter}
                exit={hidden}
                style={{ transformOrigin: "bottom right" }}
              >
                <ToastView
                  toast={toast}
                  lifetimeMs={TOAST_MS}
                  onDismiss={() => dispatch({ type: "toast.dismiss", id: toast.id })}
                />
              </motion.div>
            ))}
          </AnimatePresence>
          {state.guide && (
            <StepsCard
              texts={state.guide.texts}
              index={state.guide.index}
              onGo={goToStep}
              onDone={() => send("guide.done", {})}
            />
          )}
          <AnimatePresence mode="wait" initial={false}>
            {view !== "hidden" && (
              <motion.div
                key={view}
                initial={hidden}
                animate={enter}
                exit={{ ...hidden, transition: { duration: EXIT_MS / 1000 } }}
                // Born from the avatar, below and to the right.
                style={{ transformOrigin: "bottom right" }}
              >
                {view === "bar" && (
                  <Bar
                    key={state.palette}
                    initialText={state.prefill}
                    extra={slashExtra}
                    attachment={state.attachment}
                    focus={state.focus}
                    onAsk={ask}
                    onAction={action}
                    onAgent={(task, folder) => send("agent.start", { task, folder })}
                    onRemoveAttachment={() => dispatch({ type: "attachment.remove" })}
                  />
                )}
                {view === "answer" && state.answer && (
                  <AnswerView
                    answer={state.answer}
                    onAsk={ask}
                    onNew={() => action("conversation.reset")}
                    onCopy={copy}
                  />
                )}
                {view === "approval" && state.approval && (
                  <ApprovalView request={state.approval} onDecide={decideApproval} />
                )}
                {view === "capture" && state.preview && (
                  <CaptureView preview={state.preview} onDecide={decideCapture} />
                )}
                {view === "selection" && state.selection && (
                  <SelectionView
                    selection={state.selection}
                    onPick={(key) => {
                      send("selection.pick", {
                        selection_id: state.selection!.id,
                        action: key,
                      });
                      dispatch({ type: "selection.picked", action: key });
                    }}
                    onCopy={copy}
                    onReplace={(text) => {
                      send("selection.replace", {
                        selection_id: state.selection!.id,
                        text,
                      });
                      dispatch({ type: "escape" });
                    }}
                  />
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </MotionConfig>
  );
}
