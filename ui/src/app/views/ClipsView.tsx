/**
 * Clipboard history and notes (ui.py's HistoryWindow and QuickNoteDialog):
 * search, copy back, delete; and for notes, write one ("notes/new" is the
 * quick-note hotkey: it opens with the editor focused, and closes on save).
 */

import { Copy, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { ViewProps } from "../AppWindow";
import { relativeTime } from "../time";
import { useCall, useRequest } from "../useRequest";

interface Item {
  id: number;
  body: string;
  created_at: string;
  kind: "text" | "image";
  thumbnail: string | null;
}

export function ClipsView({
  client,
  env,
  param,
  kind,
}: ViewProps & { kind: "clips" | "notes" }) {
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const list = useRequest<{ items: Item[] }>(client, `${kind}.list`, { search });
  const { call, error } = useCall(client);
  const composer = useRef<HTMLTextAreaElement>(null);
  const quick = kind === "notes" && param === "new";

  useEffect(() => {
    if (quick) composer.current?.focus();
  }, [quick]);

  const items = list.data?.items ?? [];
  const current = items.find((i) => i.id === picked) ?? items[0] ?? null;

  const copy = async (item: Item) => {
    const done = await call(`${kind}.copy`, { id: item.id });
    if (done) setStatus(item.kind === "image" ? "Image copiée." : "Copié.");
  };
  const remove = async (item: Item) => {
    if (await call(`${kind}.delete`, { id: item.id })) {
      setPicked(null);
      list.reload();
    }
  };
  const save = async () => {
    if (!draft.trim()) return;
    if (await call("notes.add", { body: draft })) {
      setDraft("");
      if (quick) env.close();
      else list.reload();
    }
  };

  return (
    <>
      <h1 className="lw-page-title">{kind === "clips" ? "Presse-papiers" : "Notes"}</h1>

      {kind === "notes" && (
        <div className="lw-form" style={{ maxWidth: "none", gap: "var(--lw-space-2)" }}>
          <textarea
            ref={composer}
            className="lw-area"
            style={{ minHeight: 90, flex: "none" }}
            placeholder="Qu'est-ce que vous voulez retenir ?"
            aria-label="Nouvelle note"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && event.ctrlKey) {
                event.preventDefault();
                void save();
              }
            }}
          />
          <div className="lw-actions">
            <span className="lw-meta">Ctrl+Entrée pour enregistrer</span>
            <button
              className="lw-button accent"
              disabled={!draft.trim()}
              onClick={() => void save()}
            >
              Enregistrer
            </button>
          </div>
        </div>
      )}

      <input
        className="lw-field"
        style={{ flex: "none" }}
        placeholder="Rechercher…"
        aria-label="Rechercher"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />

      <div className="lw-scroll">
        {list.error && <p className="lw-error">{list.error}</p>}
        {!list.loading && items.length === 0 && (
          <p className="lw-meta">
            {search
              ? "Rien ne correspond."
              : kind === "clips"
                ? "Rien de copié pour l'instant."
                : "Aucune note."}
          </p>
        )}
        <ul className="lw-items" role="listbox" aria-label={kind}>
          {items.map((item) => (
            <li key={item.id}>
              <button
                className="lw-item"
                role="option"
                aria-selected={current?.id === item.id}
                onClick={() => setPicked(item.id)}
                onDoubleClick={() => void copy(item)}
              >
                {item.thumbnail && (
                  <img src={`data:image/png;base64,${item.thumbnail}`} alt="" />
                )}
                <span className="lw-item-body">{item.body.replace(/\s+/g, " ")}</span>
                <span className="lw-meta">{relativeTime(item.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="lw-actions">
        <span className={`lw-meta ${error ? "lw-error" : ""}`}>
          {error ?? (status || "Double-clic pour copier.")}
        </span>
        <button
          className="lw-button"
          disabled={!current}
          onClick={() => current && void remove(current)}
        >
          <Trash2 size={14} /> Supprimer
        </button>
        <button
          className="lw-button accent"
          disabled={!current}
          onClick={() => current && void copy(current)}
        >
          <Copy size={14} /> Copier
        </button>
      </div>
    </>
  );
}
