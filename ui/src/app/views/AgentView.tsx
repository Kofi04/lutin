/**
 * Launch a background agent (ui_agent.py): what to do, and the folder it may
 * work in. The core checks both again, and remembers the folder.
 */

import { FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";

import type { ViewProps } from "../AppWindow";
import { useCall } from "../useRequest";

export function AgentView({ client, env }: ViewProps) {
  const [task, setTask] = useState("");
  const [folder, setFolder] = useState("");
  const { call, error, busy } = useCall(client);

  useEffect(() => {
    client
      .request<{ folder: string }>("agents.last_folder")
      .then((r) => setFolder((current) => current || r.folder))
      .catch(() => undefined);
  }, [client]);

  const launch = async () => {
    if (await call("agents.launch", { task, folder })) env.close();
  };

  return (
    <>
      <h1 className="lw-page-title">Lancer un agent</h1>
      <p className="lw-meta" style={{ margin: 0, maxWidth: 560 }}>
        L'agent travaille en arrière-plan dans le dossier choisi. Chaque action qui
        modifie quelque chose vous sera demandée, comme d'habitude.
      </p>
      <div className="lw-form" style={{ maxWidth: 640 }}>
        <textarea
          className="lw-area"
          style={{ minHeight: 120, flex: "none" }}
          autoFocus
          aria-label="Tâche"
          placeholder="Que doit-il faire ? Par exemple : « fais passer les tests qui échouent »"
          value={task}
          onChange={(event) => setTask(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && event.ctrlKey) {
              event.preventDefault();
              void launch();
            }
          }}
        />
        <div className="lw-row">
          <input
            className="lw-field"
            aria-label="Dossier de travail"
            placeholder="Dossier de travail"
            value={folder}
            onChange={(event) => setFolder(event.target.value)}
          />
          <button
            className="lw-button"
            onClick={async () => {
              const picked = await env.pickFolder(folder || undefined);
              if (picked) setFolder(picked);
            }}
          >
            <FolderOpen size={14} /> Parcourir…
          </button>
        </div>
      </div>
      <div className="lw-actions" style={{ maxWidth: 640 }}>
        <span className="lw-meta lw-error">{error ?? ""}</span>
        <button className="lw-button secondary" onClick={env.close}>
          Annuler
        </button>
        <button
          className="lw-button accent"
          disabled={busy || !task.trim()}
          onClick={() => void launch()}
        >
          Lancer
        </button>
      </div>
    </>
  );
}
