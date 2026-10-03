/**
 * The panel window, phase M2: the raw events, a question field, and the
 * buttons needed to answer what the core asks (approval, capture, selection).
 * The real panel and its states are phase M5 (DESIGN.md section 5).
 */

import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import type { CoreMessage, CorePayloads } from "../protocol";
import { createClient, useStatus } from "./connect";

const client = createClient("panel");
const MAX_EVENTS = 60;

function summary(message: CoreMessage): string {
  const payload = { ...message.payload } as Record<string, unknown>;
  if (typeof payload.png_base64 === "string") payload.png_base64 = "…";
  const text = JSON.stringify(payload);
  return text.length > 160 ? `${text.slice(0, 159)}…` : text;
}

function Panel() {
  const status = useStatus(client);
  const [events, setEvents] = useState<CoreMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [approval, setApproval] = useState<CorePayloads["approval.request"] | null>(null);
  const [preview, setPreview] = useState<CorePayloads["capture.preview"] | null>(null);
  const [attached, setAttached] = useState<string | undefined>(undefined);
  const [menu, setMenu] = useState<CorePayloads["selection.menu"] | null>(null);

  useEffect(() => {
    const off = [
      client.onAny((message) =>
        setEvents((list) => [message, ...list].slice(0, MAX_EVENTS)),
      ),
      client.on("approval.request", (p) => setApproval(p)),
      client.on("approval.cancel", () => setApproval(null)),
      client.on("capture.preview", (p) => setPreview(p)),
      client.on("selection.menu", (p) => setMenu(p)),
      client.on("panel.open", (p) => {
        setAttached(p.capture?.capture_id);
        void getCurrentWindow().show();
      }),
    ];
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") void getCurrentWindow().hide();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      off.forEach((stop) => stop());
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const answer = (decision: "allow" | "always" | "deny") => {
    if (approval === null) return;
    client.send("approval.answer", { request_id: approval.request_id, decision });
    setApproval(null);
  };

  return (
    <div
      style={{
        height: "100%",
        boxSizing: "border-box",
        padding: 12,
        borderRadius: 18,
        background: "rgba(16,16,20,0.94)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        userSelect: "text",
      }}
    >
      <div style={{ opacity: 0.7 }}>Cœur : {status}</div>

      {approval && (
        <div style={{ border: "1px solid #FFB547", borderRadius: 8, padding: 8 }}>
          <div>
            {approval.tool} {approval.project && `dans ${approval.project}`}
          </div>
          <code style={{ fontFamily: "Cascadia Code, monospace" }}>
            {approval.detail}
          </code>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <button onClick={() => answer("deny")}>Refuser</button>
            <button onClick={() => answer("always")}>Toujours</button>
            <button onClick={() => answer("allow")}>Autoriser</button>
          </div>
        </div>
      )}

      {preview && (
        <div>
          <img
            alt={preview.label}
            src={`data:image/png;base64,${preview.png_base64}`}
            style={{ maxWidth: 480, maxHeight: 120 }}
          />
          <div>
            {preview.label} · {preview.width}×{preview.height} · ~{preview.tokens} tokens
          </div>
          <button
            onClick={() => {
              client.send("capture.confirm", { capture_id: preview.capture_id });
              setPreview(null);
            }}
          >
            Envoyer
          </button>
          <button
            onClick={() => {
              client.send("capture.cancel", { capture_id: preview.capture_id });
              setPreview(null);
            }}
          >
            Annuler
          </button>
        </div>
      )}

      {menu && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {menu.actions.map((action) => (
            <button
              key={action.key}
              onClick={() => {
                client.send("selection.pick", {
                  selection_id: menu.selection_id,
                  action: action.key,
                });
                setMenu(null);
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!question.trim()) return;
          const payload = attached
            ? { text: question, capture_id: attached }
            : { text: question };
          if (client.send("ask", payload)) {
            setQuestion("");
            setAttached(undefined);
          }
        }}
      >
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={attached ? "Question sur la capture…" : "Demander à Claude…"}
          style={{ width: "100%", boxSizing: "border-box" }}
        />
      </form>

      <ol
        style={{
          flex: 1,
          overflowY: "auto",
          margin: 0,
          paddingLeft: 18,
          fontFamily: "Cascadia Code, monospace",
          fontSize: 11,
        }}
      >
        {events.map((message, index) => (
          <li key={events.length - index}>
            <b>{message.type}</b> {summary(message)}
          </li>
        ))}
      </ol>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Panel />);
