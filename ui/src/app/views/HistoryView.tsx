/**
 * History (ui_history.py and ui_sessions.py): the wizard's own conversations,
 * grouped by date or searched, and, read-only, your Claude Code sessions.
 * Everything is shown as Markdown, never as HTML.
 */

import { Pin, PinOff } from "lucide-react";
import { useState } from "react";

import { MarkdownView } from "../../panel/MarkdownView";
import type { ViewProps } from "../AppWindow";
import { relativeTime } from "../time";
import { useCall, useRequest } from "../useRequest";

interface Conversation {
  id: number;
  kind_label: string;
  title: string;
  updated_at: string;
  pinned: boolean;
  project: string;
  resumable: boolean;
  snippet?: string;
}

type Listing =
  | { mode: "groups"; groups: { title: string; items: Conversation[] }[] }
  | { mode: "search"; items: Conversation[] };

interface Transcript {
  session_id: string;
  title: string;
  project: string;
  modified: string;
}

export function HistoryView(props: ViewProps) {
  const [tab, setTab] = useState<"own" | "claude">("own");
  return (
    <>
      <h1 className="lw-page-title">Historique</h1>
      <div className="lw-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "own"} onClick={() => setTab("own")}>
          Discussions
        </button>
        <button
          role="tab"
          aria-selected={tab === "claude"}
          onClick={() => setTab("claude")}
        >
          Mes sessions Claude Code
        </button>
      </div>
      {tab === "own" ? <OwnHistory {...props} /> : <ClaudeSessions {...props} />}
    </>
  );
}

/** A button that asks once more before doing something you cannot undo. */
function Confirm({
  label,
  confirm,
  onConfirm,
}: {
  label: string;
  confirm: string;
  onConfirm(): void;
}) {
  const [armed, setArmed] = useState(false);
  return (
    <button
      className={`lw-button ${armed ? "accent" : ""}`}
      onBlur={() => setArmed(false)}
      onClick={() => {
        if (armed) onConfirm();
        setArmed(!armed);
      }}
    >
      {armed ? confirm : label}
    </button>
  );
}

function OwnHistory({ client, env }: ViewProps) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const kinds = useRequest<{ kinds: { value: string; label: string }[] }>(
    client,
    "history.kinds",
  );
  const listing = useRequest<Listing>(client, "history.list", { search, kind });
  const detail = useRequest<{ conversation: Conversation; markdown: string }>(
    client,
    picked === null ? null : "history.get",
    { id: picked },
  );
  const { call, error } = useCall(client);
  const [status, setStatus] = useState("");

  const groups =
    listing.data?.mode === "groups"
      ? listing.data.groups
      : listing.data
        ? [{ title: "", items: listing.data.items }]
        : [];
  const count = groups.reduce((n, g) => n + g.items.length, 0);
  const current = picked === null ? null : (detail.data?.conversation ?? null);

  const refresh = () => {
    listing.reload();
    detail.reload();
  };
  const act = async (method: string, params: Record<string, unknown> = {}) => {
    if (!current) return null;
    const done = await call(method, { id: current.id, ...params });
    return done;
  };

  return (
    <div className="lw-split">
      <div className="lw-list-pane">
        <input
          className="lw-field"
          style={{ flex: "none" }}
          placeholder="Rechercher dans toutes les discussions…"
          aria-label="Rechercher"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="lw-row" style={{ flexWrap: "wrap" }}>
          {[{ value: "", label: "Toutes" }, ...(kinds.data?.kinds ?? [])].map((k) => (
            <button
              key={k.value}
              className="lw-chip"
              aria-pressed={kind === k.value}
              style={kind === k.value ? { color: "var(--lw-color-text)" } : undefined}
              onClick={() => setKind(k.value)}
            >
              {k.label}
            </button>
          ))}
        </div>
        <div className="lw-scroll">
          {listing.error && <p className="lw-error">{listing.error}</p>}
          {!listing.loading && count === 0 && (
            <p className="lw-meta">
              {search
                ? "Aucune discussion ne correspond."
                : "Aucune discussion pour l'instant."}
            </p>
          )}
          {groups.map((group) => (
            <section key={group.title}>
              {group.title && <div className="lw-meta lw-group">{group.title}</div>}
              <ul className="lw-items">
                {group.items.map((c) => (
                  <li key={c.id}>
                    <button
                      className="lw-item"
                      aria-selected={picked === c.id}
                      onClick={() => {
                        setPicked(c.id);
                        setRenaming(null);
                        setStatus("");
                      }}
                      style={{ flexDirection: "column", gap: 2 }}
                    >
                      <span className="lw-item-body" style={{ width: "100%" }}>
                        {c.pinned && <Pin size={12} />} {c.title}
                      </span>
                      <span className="lw-meta">
                        {c.snippet ?? `${c.kind_label} · ${relativeTime(c.updated_at)}`}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <div className="lw-actions" style={{ justifyContent: "space-between" }}>
          <span className="lw-meta">
            {count} discussion{count > 1 ? "s" : ""}
          </span>
          <Confirm
            label="Tout effacer…"
            confirm="Effacer tout l'historique ?"
            onConfirm={async () => {
              const done = await call<{ deleted: number }>("history.clear");
              if (done) {
                setPicked(null);
                setStatus(`${done.deleted} discussion(s) effacée(s).`);
                listing.reload();
              }
            }}
          />
        </div>
      </div>

      <div className="lw-detail">
        {current === null ? (
          <p className="lw-meta">Choisissez une discussion à gauche.</p>
        ) : (
          <>
            {renaming === null ? (
              <div className="lw-title">{current.title}</div>
            ) : (
              <form
                className="lw-row"
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (await act("history.rename", { title: renaming })) {
                    setRenaming(null);
                    refresh();
                  }
                }}
              >
                <input
                  className="lw-field"
                  autoFocus
                  aria-label="Nouveau titre"
                  value={renaming}
                  onChange={(event) => setRenaming(event.target.value)}
                />
                <button className="lw-button accent" type="submit">
                  OK
                </button>
              </form>
            )}
            <div className="lw-reader lw-answer" style={{ maxHeight: "none" }}>
              <MarkdownView
                text={detail.data?.markdown ?? ""}
                onCopy={(text) => client.send("selection.copy", { text })}
              />
            </div>
            <div className="lw-actions">
              <span className={`lw-meta ${error ? "lw-error" : ""}`}>
                {error ?? status}
              </span>
              <button className="lw-button" onClick={() => setRenaming(current.title)}>
                Renommer
              </button>
              <button
                className="lw-button"
                onClick={async () => {
                  if (await act("history.pin", { pinned: !current.pinned })) refresh();
                }}
              >
                {current.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                {current.pinned ? "Désépingler" : "Épingler"}
              </button>
              <button
                className="lw-button"
                onClick={async () => {
                  const path = await env.saveFile(`${current.title}.md`);
                  if (path && (await act("history.export", { path }))) {
                    setStatus(`Exporté : ${path}`);
                  }
                }}
              >
                Exporter…
              </button>
              <Confirm
                label="Supprimer"
                confirm="Supprimer ?"
                onConfirm={async () => {
                  if (await act("history.delete")) {
                    setPicked(null);
                    listing.reload();
                  }
                }}
              />
              <button
                className="lw-button accent"
                disabled={!current.resumable}
                title={
                  current.resumable
                    ? "Continuer cette discussion dans le panneau"
                    : "Claude n'a jamais répondu : rien à reprendre."
                }
                onClick={async () => {
                  if (await act("history.resume")) env.close();
                }}
              >
                Reprendre
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ClaudeSessions({ client }: ViewProps) {
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const list = useRequest<{ items: Transcript[] }>(client, "transcripts.list", {
    search,
  });
  const detail = useRequest<{ markdown: string }>(
    client,
    picked === null ? null : "transcripts.get",
    { session_id: picked },
  );
  const items = list.data?.items ?? [];

  return (
    <div className="lw-split">
      <div className="lw-list-pane">
        <input
          className="lw-field"
          style={{ flex: "none" }}
          placeholder="Filtrer par titre ou projet…"
          aria-label="Filtrer"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="lw-scroll">
          {list.error && <p className="lw-error">{list.error}</p>}
          {!list.loading && items.length === 0 && (
            <p className="lw-meta">Aucune session Claude Code trouvée.</p>
          )}
          <ul className="lw-items">
            {items.map((s) => (
              <li key={s.session_id}>
                <button
                  className="lw-item"
                  aria-selected={picked === s.session_id}
                  onClick={() => setPicked(s.session_id)}
                  style={{ flexDirection: "column", gap: 2 }}
                >
                  <span className="lw-item-body" style={{ width: "100%" }}>
                    {s.title}
                  </span>
                  <span className="lw-meta">
                    {s.project} · {relativeTime(s.modified)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="lw-detail">
        {picked === null ? (
          <p className="lw-meta">
            Vos sessions Claude Code, en lecture seule. Choisissez-en une à gauche.
          </p>
        ) : (
          <div className="lw-reader lw-answer" style={{ maxHeight: "none" }}>
            {detail.error ? (
              <p className="lw-error">{detail.error}</p>
            ) : (
              <MarkdownView
                text={detail.data?.markdown ?? ""}
                onCopy={(text) => client.send("selection.copy", { text })}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
