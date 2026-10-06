/**
 * The panel's views, one per state of DESIGN.md section 5. They only show
 * and report: what to send and where to go next is decided in Panel.tsx.
 */

import {
  Bot,
  Crop,
  Monitor,
  Paperclip,
  Plus,
  Send,
  TextCursorInput,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ActionName, CorePayloads } from "../protocol";
import { rank } from "./fuzzy";
import type { Answer, Selection, Toast } from "./machine";
import { MarkdownView } from "./MarkdownView";

// -- bar ---------------------------------------------------------------------

/** What "/" offers: the core's actions, in French. */
export const SLASH_ACTIONS: { name: ActionName; label: string }[] = [
  { name: "capture.region", label: "Montrer une zone" },
  { name: "capture.screen", label: "Capturer l'écran" },
  { name: "capture.text", label: "Copier le texte d'une zone" },
  { name: "selection", label: "Agir sur la sélection" },
  { name: "conversation.reset", label: "Nouvelle discussion" },
  { name: "config.reload", label: "Recharger la configuration" },
  { name: "config.open_folder", label: "Ouvrir le dossier de configuration" },
  { name: "quit", label: "Quitter Little Wizard" },
];

export interface BarProps {
  attachment: { label: string } | null;
  focus: boolean;
  onAsk(text: string): void;
  onAction(name: ActionName): void;
  onAgent(task: string, folder: string): void;
  onRemoveAttachment(): void;
}

export function Bar({
  attachment,
  focus,
  onAsk,
  onAction,
  onAgent,
  onRemoveAttachment,
}: BarProps) {
  const [text, setText] = useState("");
  const [agent, setAgent] = useState(false);
  const [folder, setFolder] = useState("");
  const [picked, setPicked] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focus) input.current?.focus();
  }, [focus, agent]);

  const slash = !agent && text.startsWith("/");
  const actions = useMemo(
    () => (slash ? rank(text.slice(1), SLASH_ACTIONS, (a) => a.label) : []),
    [slash, text],
  );

  const submit = () => {
    if (slash) {
      const action = actions[picked];
      if (action) {
        onAction(action.name);
        setText("");
      }
      return;
    }
    if (!text.trim()) return;
    if (agent) {
      if (!folder.trim()) return;
      onAgent(text.trim(), folder.trim());
      setAgent(false);
    } else onAsk(text.trim());
    setText("");
  };

  return (
    <div className="lw-surface" style={{ width: 520 }}>
      <form
        className="lw-section lw-row"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <input
          ref={input}
          className="lw-field"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setPicked(0);
          }}
          onKeyDown={(event) => {
            if (!slash) return;
            if (event.key === "ArrowDown")
              setPicked((p) => Math.min(p + 1, actions.length - 1));
            if (event.key === "ArrowUp") setPicked((p) => Math.max(p - 1, 0));
          }}
          placeholder={agent ? "Tâche de l'agent…" : "Demande au sorcier…"}
          aria-label={agent ? "Tâche de l'agent" : "Question"}
        />
        {agent && (
          <input
            className="lw-field"
            style={{ flex: "0 0 160px" }}
            value={folder}
            onChange={(event) => setFolder(event.target.value)}
            placeholder="Dossier"
            aria-label="Dossier de l'agent"
          />
        )}
        <button className="lw-button accent" type="submit" aria-label="Envoyer">
          <Send size={16} />
        </button>
      </form>

      {slash ? (
        <ul className="lw-list lw-section" style={{ paddingTop: 0 }}>
          {actions.length === 0 && <li className="lw-meta">Aucune action</li>}
          {actions.map((action, i) => (
            <li key={action.name}>
              <button
                className="lw-chip"
                aria-selected={i === picked}
                onClick={() => {
                  onAction(action.name);
                  setText("");
                }}
              >
                {action.label}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="lw-section lw-row" style={{ paddingTop: 0, flexWrap: "wrap" }}>
          {attachment && (
            <span className="lw-chip" style={{ color: "var(--lw-color-text)" }}>
              <Paperclip size={14} />
              {attachment.label}
              <button
                className="lw-chip"
                style={{ height: 20, padding: 0, border: "none" }}
                onClick={onRemoveAttachment}
                aria-label="Retirer la pièce jointe"
              >
                <X size={14} />
              </button>
            </span>
          )}
          <button className="lw-chip" onClick={() => onAction("capture.screen")}>
            <Monitor size={14} /> Écran
          </button>
          <button className="lw-chip" onClick={() => onAction("capture.region")}>
            <Crop size={14} /> Zone
          </button>
          <button className="lw-chip" onClick={() => onAction("selection")}>
            <TextCursorInput size={14} /> Sélection
          </button>
          <button
            className="lw-chip"
            aria-pressed={agent}
            style={agent ? { color: "var(--lw-color-accent)" } : undefined}
            onClick={() => setAgent((a) => !a)}
          >
            <Bot size={14} /> Agent
          </button>
        </div>
      )}
    </div>
  );
}

// -- answer ------------------------------------------------------------------

export function AnswerView({
  answer,
  onAsk,
  onNew,
  onCopy,
}: {
  answer: Answer;
  onAsk(text: string): void;
  onNew(): void;
  onCopy(text: string): void;
}) {
  const [text, setText] = useState("");
  const scroller = useRef<HTMLDivElement>(null);

  // Follow the text as it streams in.
  useEffect(() => {
    const element = scroller.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [answer.text]);

  return (
    <div className="lw-surface" style={{ width: 560 }}>
      <div className="lw-section">
        {answer.question && <div className="lw-meta">{answer.question}</div>}
        {answer.status && (
          <div className="lw-meta" aria-live="polite">
            {answer.status}
          </div>
        )}
      </div>
      <div ref={scroller} className="lw-section lw-answer" style={{ paddingTop: 0 }}>
        {answer.context && <MarkdownView text={answer.context} onCopy={onCopy} />}
        {answer.streaming ? (
          // Plain while it streams: Markdown half-written jumps around.
          <p style={{ whiteSpace: "pre-wrap" }}>
            {answer.text}
            <span className="lw-caret" aria-hidden="true" />
          </p>
        ) : (
          <MarkdownView text={answer.text} onCopy={onCopy} />
        )}
        {answer.error && <p className="lw-error">{answer.error}</p>}
      </div>
      <form
        className="lw-section lw-row"
        style={{ borderTop: "1px solid var(--lw-color-border)" }}
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim()) onAsk(text.trim());
          setText("");
        }}
      >
        <input
          className="lw-field"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Relancer…"
          aria-label="Relancer"
        />
        <button className="lw-button" type="button" onClick={onNew}>
          <Plus size={16} /> Nouvelle discussion
        </button>
      </form>
    </div>
  );
}

// -- approval ----------------------------------------------------------------

export function ApprovalView({
  request,
  onDecide,
}: {
  request: CorePayloads["approval.request"];
  onDecide(decision: "allow" | "always" | "deny"): void;
}) {
  const [expanded, setExpanded] = useState(false);
  const deadline = useMemo(
    () => Date.now() + request.timeout_seconds * 1000,
    [request.request_id, request.timeout_seconds],
  );
  const [left, setLeft] = useState(request.timeout_seconds);
  useEffect(() => {
    // Once a second: a countdown in seconds needs no more frames than that.
    const timer = setInterval(
      () => setLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000))),
      1000,
    );
    return () => clearInterval(timer);
  }, [deadline]);

  const lines = request.detail.split("\n");
  const long = lines.length > 4;
  return (
    <div
      className="lw-surface"
      style={{ width: 520 }}
      role="alertdialog"
      aria-label="Autorisation"
    >
      <div className="lw-section">
        <div className="lw-title">
          Claude veut exécuter {request.tool}
          {request.project && <span className="lw-meta"> · {request.project}</span>}
        </div>
      </div>
      <div className="lw-section" style={{ paddingTop: 0 }}>
        <pre className="lw-mono">
          {long && !expanded ? lines.slice(0, 4).join("\n") + "\n…" : request.detail}
        </pre>
        {long && (
          <button className="lw-chip" onClick={() => setExpanded((e) => !e)}>
            {expanded ? "Réduire" : "Tout afficher"}
          </button>
        )}
      </div>
      <div className="lw-section lw-row" style={{ justifyContent: "flex-end" }}>
        <span className="lw-meta" style={{ marginRight: "auto" }}>
          Refus automatique dans {left} s
        </span>
        <button className="lw-button" onClick={() => onDecide("deny")}>
          Refuser
        </button>
        <button className="lw-button secondary" onClick={() => onDecide("always")}>
          Toujours
        </button>
        <button className="lw-button accent" onClick={() => onDecide("allow")}>
          Autoriser
        </button>
      </div>
    </div>
  );
}

// -- capture -----------------------------------------------------------------

export function CaptureView({
  preview,
  onDecide,
}: {
  preview: CorePayloads["capture.preview"];
  onDecide(send: boolean): void;
}) {
  return (
    <div
      className="lw-surface"
      style={{ width: 520 }}
      role="dialog"
      aria-label="Capture à envoyer"
    >
      <div className="lw-section">
        <div className="lw-title">Envoyer cette image à Claude ?</div>
        <div className="lw-meta">
          {preview.label} · {preview.width}×{preview.height} · ~{preview.tokens} tokens
        </div>
      </div>
      <div className="lw-section" style={{ paddingTop: 0 }}>
        {/* The exact image that will be sent: it is the one the core holds. */}
        <img
          src={`data:image/png;base64,${preview.png_base64}`}
          alt={preview.label}
          style={{
            display: "block",
            maxWidth: 480,
            maxHeight: 280,
            borderRadius: "var(--lw-radius-field)",
          }}
        />
      </div>
      <div className="lw-section lw-row" style={{ justifyContent: "flex-end" }}>
        <button className="lw-button" onClick={() => onDecide(false)}>
          Annuler
        </button>
        <button className="lw-button accent" onClick={() => onDecide(true)}>
          Envoyer
        </button>
      </div>
    </div>
  );
}

// -- selection ---------------------------------------------------------------

export function SelectionView({
  selection,
  onPick,
  onCopy,
  onReplace,
}: {
  selection: Selection;
  onPick(action: string): void;
  onCopy(text: string): void;
  onReplace(text: string): void;
}) {
  const [text, setText] = useState(selection.text);
  useEffect(() => setText(selection.text), [selection.text]);
  const label = selection.actions.find((a) => a.key === selection.action)?.label ?? "";

  return (
    <div className="lw-surface" style={{ width: 520 }}>
      <div className="lw-section">
        <div className="lw-title">
          {selection.phase === "menu" ? "Que faire de la sélection ?" : label}
        </div>
        <div className="lw-meta">« {selection.preview} »</div>
      </div>
      <div className="lw-section" style={{ paddingTop: 0 }}>
        {selection.phase === "menu" && (
          <ul className="lw-list">
            {selection.actions.map((action) => (
              <li key={action.key}>
                <button className="lw-chip" onClick={() => onPick(action.key)}>
                  {action.label}
                </button>
              </li>
            ))}
          </ul>
        )}
        {selection.phase === "working" && <div className="lw-meta">Claude écrit…</div>}
        {selection.phase === "error" && <div className="lw-error">{selection.text}</div>}
        {selection.phase === "done" && (
          <>
            <textarea
              className="lw-field"
              style={{
                width: "100%",
                height: 120,
                padding: "var(--lw-space-2) var(--lw-space-3)",
                resize: "vertical",
              }}
              value={text}
              onChange={(event) => setText(event.target.value)}
              aria-label="Résultat, modifiable"
            />
            <div
              className="lw-row"
              style={{ justifyContent: "flex-end", marginTop: "var(--lw-space-2)" }}
            >
              <button className="lw-button" onClick={() => onCopy(text)}>
                Copier
              </button>
              {selection.replaces && (
                <button className="lw-button accent" onClick={() => onReplace(text)}>
                  Remplacer la sélection
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// -- toasts ------------------------------------------------------------------

const TOAST_DOT: Record<Toast["kind"], string> = {
  info: "var(--lw-color-accent)",
  success: "var(--lw-color-state-success)",
  warning: "var(--lw-color-state-waiting)",
  error: "var(--lw-color-state-danger)",
};

export function ToastView({
  toast,
  lifetimeMs,
  onDismiss,
}: {
  toast: Toast;
  lifetimeMs: number;
  onDismiss(): void;
}) {
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused) return;
    // Restarts on leaving: a toast you hovered gets its full time again.
    const timer = setTimeout(onDismiss, lifetimeMs);
    return () => clearTimeout(timer);
  }, [paused, lifetimeMs, onDismiss]);

  return (
    <div
      className="lw-surface lw-toast"
      role="status"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onClick={onDismiss}
    >
      <span className="lw-dot" style={{ background: TOAST_DOT[toast.kind] }} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: "var(--lw-weight-medium)" }}>{toast.title}</div>
        {toast.body && <div className="lw-meta">{toast.body}</div>}
      </div>
    </div>
  );
}
