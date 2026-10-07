/**
 * Claude Code hooks (ui_hooks.py): the exact change to settings.json, shown
 * before it is made. "Écrire" sends back the diff shown: the core plans
 * again and writes only if it is still that one (services.py, hooks.apply).
 */

import { useState } from "react";

import type { ViewProps } from "../AppWindow";
import { useCall, useRequest } from "../useRequest";

interface Plan {
  installing: boolean;
  changed: boolean;
  path: string;
  diff: string;
  installed: boolean;
  stale: boolean;
}

function lineClass(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++")) return "add";
  if (line.startsWith("-") && !line.startsWith("---")) return "del";
  return "";
}

export function HooksView({ client, env, param, go }: ViewProps) {
  const installing = param !== "uninstall";
  const chosen = param === "install" || param === "uninstall";
  const plan = useRequest<Plan>(client, "hooks.plan", { install: installing });
  const { call, error, busy } = useCall(client);
  const [done, setDone] = useState<string | null>(null);

  if (plan.error && !plan.data) return <p className="lw-error">{plan.error}</p>;
  if (!plan.data) return <p className="lw-meta">Chargement…</p>;
  const p = plan.data;

  if (!chosen) {
    return (
      <>
        <h1 className="lw-page-title">Hooks Claude Code</h1>
        <p style={{ margin: 0 }}>
          {p.installed
            ? "Installés : je vois vos sessions Claude Code et vous pouvez approuver leurs actions ici."
            : "Pas installés : vos sessions Claude Code ne me sont pas reliées."}
        </p>
        {p.stale && (
          <p className="lw-error" style={{ margin: 0 }}>
            Le script référencé dans settings.json n'existe plus : réinstallez-les.
          </p>
        )}
        <p className="lw-meta" style={{ margin: 0 }}>
          Rien n'est modifié sans que vous voyiez le changement exact avant.
        </p>
        <div className="lw-actions" style={{ justifyContent: "flex-start" }}>
          <button className="lw-button accent" onClick={() => go("hooks/install")}>
            {p.installed ? "Réinstaller…" : "Installer…"}
          </button>
          {p.installed && (
            <button className="lw-button" onClick={() => go("hooks/uninstall")}>
              Désinstaller…
            </button>
          )}
        </div>
      </>
    );
  }

  const action = installing ? "installer" : "désinstaller";

  return (
    <>
      <h1 className="lw-page-title">
        {installing ? "Installer" : "Désinstaller"} les hooks Claude Code
      </h1>
      {done ? (
        <p style={{ margin: 0 }}>{done}</p>
      ) : p.changed ? (
        <p style={{ margin: 0 }}>
          Little Wizard va modifier <code>{p.path}</code>. Une copie horodatée est faite
          avant écriture, et seules les entrées de Little Wizard sont touchées.
        </p>
      ) : (
        <p style={{ margin: 0 }}>
          Rien à {action} : <code>{p.path}</code> contient déjà ce qu'il faut.
        </p>
      )}
      {p.changed && !done && (
        <pre className="lw-mono lw-diff" aria-label="Changement">
          {p.diff.split("\n").map((line, i) => (
            <div key={i} className={lineClass(line)}>
              {line || " "}
            </div>
          ))}
        </pre>
      )}
      <div className="lw-actions">
        <span className="lw-meta lw-error">{error ?? ""}</span>
        {done ? (
          <button className="lw-button accent" onClick={env.close}>
            Fermer
          </button>
        ) : (
          <>
            <button className="lw-button secondary" onClick={env.close}>
              Annuler
            </button>
            <button
              className="lw-button accent"
              disabled={!p.changed || busy}
              onClick={async () => {
                const result = await call<{ installed: boolean }>("hooks.apply", {
                  install: installing,
                  seen: p.diff,
                });
                if (result) {
                  setDone(result.installed ? "Hooks installés." : "Hooks retirés.");
                } else {
                  plan.reload(); // the file changed: show what would be written now
                }
              }}
            >
              Écrire
            </button>
          </>
        )}
      </div>
    </>
  );
}
