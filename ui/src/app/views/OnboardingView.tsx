/**
 * The welcome (ui_onboarding.py): how the wizard works, the shortcuts worth
 * learning, and what is not ready on this machine, checked by the core.
 */

import { Check, CircleAlert } from "lucide-react";

import { MarkdownView } from "../../panel/MarkdownView";
import type { ViewProps } from "../AppWindow";
import { useCall, useRequest } from "../useRequest";

interface Info {
  checks: { label: string; ok: boolean; detail: string; action: string }[];
  shortcuts: { label: string; keys: string }[];
}

export function OnboardingView({ client, env, go }: ViewProps) {
  const info = useRequest<Info>(client, "onboarding.info");
  const { call } = useCall(client);

  const finish = async (then: () => void) => {
    await call("onboarding.done");
    then();
  };

  return (
    <>
      <h1 className="lw-page-title">Bonjour, je suis Little Wizard.</h1>
      <div
        className="lw-scroll"
        style={{ display: "flex", flexDirection: "column", gap: "var(--lw-space-4)" }}
      >
        <p style={{ margin: 0, maxWidth: 560, lineHeight: 1.5 }}>
          Je vis au-dessus de votre barre des tâches. Montrez-moi quelque chose à l'écran,
          posez-moi une question, et je vous réponds ici — sans terminal. Mon bâton
          s'allume selon ce que je fais : doré au repos, bleu quand Claude travaille,
          ambre quand quelque chose vous attend.
        </p>

        {info.error && <p className="lw-error">{info.error}</p>}

        <section>
          <div className="lw-title">Les raccourcis à retenir</div>
          <ul className="lw-items" style={{ maxWidth: 560 }}>
            {info.data?.shortcuts.map((s) => (
              <li key={s.label} className="lw-item" style={{ cursor: "default" }}>
                <span className="lw-item-body">{s.label}</span>
                <span className="lw-meta">{s.keys}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <div className="lw-title">Sur cette machine</div>
          <ul className="lw-items" style={{ maxWidth: 560 }}>
            {info.data?.checks.map((c) => (
              <li
                key={c.label}
                className="lw-item lw-status"
                style={{ cursor: "default" }}
              >
                <span
                  style={{
                    color: c.ok
                      ? "var(--lw-color-state-success)"
                      : "var(--lw-color-state-waiting)",
                  }}
                >
                  {c.ok ? <Check size={16} /> : <CircleAlert size={16} />}
                </span>
                <span style={{ flex: 1 }}>
                  <strong>{c.label}</strong>
                  <MarkdownView
                    text={c.detail}
                    onCopy={(text) => client.send("selection.copy", { text })}
                  />
                </span>
                {c.action && (
                  <button className="lw-button" onClick={() => go("hooks/install")}>
                    {c.action}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>
      <div className="lw-actions">
        <button className="lw-button" onClick={() => void finish(() => go("settings"))}>
          Paramètres…
        </button>
        <button className="lw-button accent" onClick={() => void finish(env.close)}>
          C'est parti
        </button>
      </div>
    </>
  );
}
