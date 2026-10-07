/**
 * Reminders (ui.py's ReminderDialog, and the tray's list of running ones):
 * a duration the core parses ("25", "1h30", "90s"), presets, and what is
 * counting down, each cancellable.
 */

import { X } from "lucide-react";
import { useEffect, useState } from "react";

import type { ViewProps } from "../AppWindow";
import { useCall, useRequest } from "../useRequest";

const PRESETS: [string, number][] = [
  ["5 min", 300],
  ["15 min", 900],
  ["Pomodoro 25 min", 1500],
  ["1 h", 3600],
];

interface Running {
  id: number;
  label: string;
  remaining_text: string;
}

export function RemindersView({ client }: ViewProps) {
  const [duration, setDuration] = useState("");
  const [label, setLabel] = useState("");
  const [status, setStatus] = useState("");
  const running = useRequest<{ items: Running[] }>(client, "timers.list");
  const { call, error } = useCall(client);

  // The countdown is read from the core once a second, only while shown.
  const { reload } = running;
  useEffect(() => {
    const timer = setInterval(reload, 1000);
    return () => clearInterval(timer);
  }, [reload]);

  const start = async (params: Record<string, unknown>) => {
    const added = await call<{ label: string }>("timers.add", { label, ...params });
    if (added) {
      setStatus(`Rappel lancé : ${added.label}`);
      setDuration("");
      setLabel("");
      reload();
    }
  };

  const items = running.data?.items ?? [];

  return (
    <>
      <h1 className="lw-page-title">Rappels</h1>
      <form
        className="lw-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (duration.trim()) void start({ duration });
        }}
      >
        <div className="lw-form-row">
          <label htmlFor="duration">Durée</label>
          <input
            id="duration"
            className="lw-field"
            autoFocus
            placeholder="25  ·  25m  ·  1h30  ·  90s"
            value={duration}
            onChange={(event) => setDuration(event.target.value)}
          />
        </div>
        <div className="lw-form-row">
          <label htmlFor="label">Intitulé</label>
          <input
            id="label"
            className="lw-field"
            placeholder="À quel sujet ? (facultatif)"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </div>
        <div className="lw-actions" style={{ justifyContent: "flex-start" }}>
          {PRESETS.map(([text, seconds]) => (
            <button
              key={seconds}
              type="button"
              className="lw-chip"
              onClick={() => void start({ seconds })}
            >
              {text}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <button className="lw-button accent" type="submit" disabled={!duration.trim()}>
            Démarrer
          </button>
        </div>
        <span className={`lw-meta ${error ? "lw-error" : ""}`}>{error ?? status}</span>
      </form>

      <div className="lw-scroll">
        <div className="lw-actions" style={{ justifyContent: "space-between" }}>
          <span className="lw-title">En cours</span>
          {items.length > 1 && (
            <button
              className="lw-chip"
              onClick={async () => {
                await call("timers.cancel_all");
                reload();
              }}
            >
              Tout annuler
            </button>
          )}
        </div>
        {items.length === 0 && <p className="lw-meta">Aucun rappel en cours.</p>}
        <ul className="lw-items">
          {items.map((item) => (
            <li key={item.id} className="lw-item" style={{ cursor: "default" }}>
              <span
                className="lw-mono"
                style={{ border: 0, padding: 0, background: "none" }}
              >
                {item.remaining_text}
              </span>
              <span className="lw-item-body">{item.label}</span>
              <button
                className="lw-chip"
                aria-label={`Annuler ${item.label}`}
                onClick={async () => {
                  await call("timers.cancel", { id: item.id });
                  reload();
                }}
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
