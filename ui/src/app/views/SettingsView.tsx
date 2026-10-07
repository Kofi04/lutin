/**
 * Settings (ui_settings.py): config.toml without opening it, plus the memory.
 * The fields, their limits and their wording come from the core
 * (settings_schema.py), which checks every value again before writing.
 */

import { useEffect, useMemo, useState } from "react";

import type { ViewProps } from "../AppWindow";
import { prettySpec, specFromKey } from "../hotkey";
import { useCall, useRequest } from "../useRequest";

interface Field {
  tab: string;
  section: string;
  key: string;
  label: string;
  kind: "bool" | "int" | "float" | "hotkey";
  minimum?: number;
  maximum?: number;
  step?: number;
  suffix?: string;
  hint?: string;
  value: boolean | number | string;
}

interface Settings {
  fields: Field[];
  memory: { text: string; from_file: boolean; template: string; limit: number };
}

type Value = Field["value"];
const MEMORY_TAB = "Mémoire";
const nameOf = (f: Field) => `${f.section}.${f.key}`;

export function SettingsView({ client, env }: ViewProps) {
  const settings = useRequest<Settings>(client, "settings.read");
  const system = useRequest<{ autostart: boolean }>(client, "system.info");
  const { call, error, setError, busy } = useCall(client);
  const [tab, setTab] = useState("Apparence");
  const [edits, setEdits] = useState<Record<string, Value>>({});
  const [memory, setMemory] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [memoryNote, setMemoryNote] = useState("");

  const fields = settings.data?.fields ?? [];
  const tabs = useMemo(
    () => [...new Set(fields.map((f) => f.tab)), MEMORY_TAB],
    [fields],
  );
  const valueOf = (f: Field): Value => edits[nameOf(f)] ?? f.value;
  const memoryText = memory ?? settings.data?.memory.text ?? "";

  // Conflicts as you type a shortcut, from the core's own rules.
  const hotkeys = fields.filter((f) => f.kind === "hotkey");
  const bindings = JSON.stringify(
    Object.fromEntries(hotkeys.map((f) => [f.key, valueOf(f)])),
  );
  useEffect(() => {
    if (!hotkeys.length) return;
    let live = true;
    client
      .request<{ problems: string[] }>("settings.check_hotkeys", {
        bindings: JSON.parse(bindings),
      })
      .then((r) => live && setProblems(r.problems))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [client, bindings, hotkeys.length]);

  useEffect(() => {
    if (!settings.data) return;
    const timer = setTimeout(() => {
      client
        .request<{ sent: number; truncated: boolean }>("settings.memory_size", {
          text: memoryText,
        })
        .then((r) =>
          setMemoryNote(
            r.truncated
              ? `Trop long : seuls les ${settings.data!.memory.limit} premiers caractères seront envoyés.`
              : `${r.sent} caractères envoyés à Claude.`,
          ),
        )
        .catch(() => undefined);
    }, 250);
    return () => clearTimeout(timer);
  }, [client, memoryText, settings.data]);

  if (settings.error && !settings.data) {
    return <p className="lw-error">{settings.error}</p>;
  }
  if (!settings.data) return <p className="lw-meta">Chargement…</p>;

  const original = settings.data.memory;
  // The untouched template is not a memory worth creating a file for.
  const memoryChanged =
    memory !== null &&
    memory !== original.text &&
    !(!original.from_file && memory === original.template);
  const changed = Object.entries(edits).filter(
    ([name, value]) => fields.find((f) => nameOf(f) === name)?.value !== value,
  );
  const dirty = changed.length > 0 || memoryChanged;

  const save = async () => {
    const result = await call("settings.write", {
      values: Object.fromEntries(changed),
      ...(memoryChanged ? { memory } : {}),
    });
    if (result) env.close();
  };

  const set = (f: Field, value: Value) => {
    setEdits((e) => ({ ...e, [nameOf(f)]: value }));
    setError(null);
  };

  return (
    <>
      <h1 className="lw-page-title">Paramètres</h1>
      <div className="lw-tabs" role="tablist">
        {tabs.map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>

      <div className="lw-scroll">
        {tab === MEMORY_TAB ? (
          <div className="lw-form" style={{ maxWidth: "none", height: "100%" }}>
            <p className="lw-meta" style={{ margin: 0 }}>
              Ce que Claude doit savoir sur vous : vos préférences, votre contexte, votre
              façon de travailler. C'est envoyé avec chaque question — n'y mettez rien de
              secret.
            </p>
            <textarea
              className="lw-area"
              aria-label="Mémoire"
              value={memoryText}
              onChange={(event) => setMemory(event.target.value)}
              style={{ minHeight: 260 }}
            />
            <span className="lw-meta">{memoryNote}</span>
          </div>
        ) : (
          <div className="lw-form">
            {fields
              .filter((f) => f.tab === tab)
              .map((f) => (
                <FieldRow key={nameOf(f)} field={f} value={valueOf(f)} onChange={set} />
              ))}
            {tab === "Système" && system.data && (
              <div className="lw-form-row">
                <span />
                <label className="lw-check">
                  <input
                    type="checkbox"
                    checked={system.data.autostart}
                    onChange={async (event) => {
                      await call("system.autostart", { enabled: event.target.checked });
                      system.reload();
                    }}
                  />
                  Lancer au démarrage de Windows
                </label>
                <span className="lw-meta">Appliqué tout de suite.</span>
              </div>
            )}
            {tab === "Raccourcis" &&
              problems.map((p) => (
                <p key={p} className="lw-error" style={{ margin: 0 }}>
                  {p}
                </p>
              ))}
          </div>
        )}
      </div>

      <div className="lw-actions">
        <span className={`lw-meta ${error ? "lw-error" : ""}`}>
          {error ?? (dirty ? "Modifications non enregistrées." : "")}
        </span>
        <button
          className="lw-button"
          onClick={() => void call("system.open_config", { file: true })}
        >
          Ouvrir config.toml
        </button>
        <button className="lw-button secondary" onClick={env.close}>
          Annuler
        </button>
        <button
          className="lw-button accent"
          disabled={!dirty || busy || problems.length > 0}
          onClick={() => void save()}
        >
          Enregistrer
        </button>
      </div>
    </>
  );
}

function FieldRow({
  field: f,
  value,
  onChange,
}: {
  field: Field;
  value: Value;
  onChange(field: Field, value: Value): void;
}) {
  const id = `field-${f.section}-${f.key}`;
  let control;
  if (f.kind === "bool") {
    return (
      <div className="lw-form-row">
        <span />
        <label className="lw-check">
          <input
            id={id}
            type="checkbox"
            checked={value as boolean}
            onChange={(event) => onChange(f, event.target.checked)}
          />
          {f.label}
        </label>
        {f.hint && <span className="lw-meta">{f.hint}</span>}
      </div>
    );
  }
  if (f.kind === "hotkey") {
    control = (
      <HotkeyField id={id} value={value as string} onChange={(v) => onChange(f, v)} />
    );
  } else {
    control = (
      <span className="lw-row">
        <input
          id={id}
          className="lw-field narrow"
          type="number"
          min={f.minimum}
          max={f.maximum}
          step={f.step}
          value={value as number}
          onChange={(event) => {
            const number = event.target.valueAsNumber;
            if (!Number.isNaN(number)) onChange(f, number);
          }}
        />
        {f.suffix && <span className="lw-meta">{f.suffix.trim()}</span>}
      </span>
    );
  }
  return (
    <div className="lw-form-row">
      <label htmlFor={id}>{f.label}</label>
      {control}
      {f.hint && <span className="lw-meta">{f.hint}</span>}
    </div>
  );
}

/** Click, press a combination, done. Backspace or Delete clears it. */
function HotkeyField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange(value: string): void;
}) {
  const [listening, setListening] = useState(false);
  return (
    <input
      id={id}
      className="lw-field"
      readOnly
      value={listening ? "" : value ? prettySpec(value) : ""}
      placeholder={
        listening ? "Appuyez sur une combinaison…" : "Aucun — cliquez puis appuyez"
      }
      title="Cliquez, puis appuyez sur la combinaison voulue. Retour arrière pour effacer."
      onFocus={() => setListening(true)}
      onBlur={() => setListening(false)}
      onKeyDown={(event) => {
        const bare = !event.ctrlKey && !event.altKey && !event.shiftKey && !event.metaKey;
        if (event.key === "Tab" && bare) return;
        event.preventDefault();
        if ((event.key === "Backspace" || event.key === "Delete") && bare) {
          onChange("");
          event.currentTarget.blur();
          return;
        }
        if (event.key === "Escape" && bare) {
          // The way out of the field, not a binding, and not closing the window.
          event.currentTarget.blur();
          return;
        }
        const spec = specFromKey(event.nativeEvent);
        if (spec !== null) {
          onChange(spec);
          event.currentTarget.blur();
        }
      }}
    />
  );
}
