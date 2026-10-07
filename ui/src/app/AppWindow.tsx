/**
 * The app window (DESIGN.md section 9): one ordinary window, a list of views
 * on the left. It holds what the Qt dialogs held; every read and every change
 * goes through the core's services (request/reply), nothing is kept here.
 */

import {
  Bell,
  Bot,
  Clipboard,
  History,
  NotebookPen,
  Plug,
  Settings,
  Sparkles,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { CoreClient } from "../core/client";
import { useStatus } from "../windows/connect";
import type { AppEnv } from "./env";
import { formatRoute, parseRoute, type Route, type ViewName } from "./routes";
import { AgentView } from "./views/AgentView";
import { ClipsView } from "./views/ClipsView";
import { HistoryView } from "./views/HistoryView";
import { HooksView } from "./views/HooksView";
import { OnboardingView } from "./views/OnboardingView";
import { RemindersView } from "./views/RemindersView";
import { SettingsView } from "./views/SettingsView";

const NAV: { view: ViewName; label: string; icon: ReactNode }[] = [
  { view: "history", label: "Historique", icon: <History size={16} /> },
  { view: "clipboard", label: "Presse-papiers", icon: <Clipboard size={16} /> },
  { view: "notes", label: "Notes", icon: <NotebookPen size={16} /> },
  { view: "reminders", label: "Rappels", icon: <Bell size={16} /> },
  { view: "agent", label: "Lancer un agent", icon: <Bot size={16} /> },
  { view: "hooks", label: "Hooks Claude Code", icon: <Plug size={16} /> },
  { view: "settings", label: "Paramètres", icon: <Settings size={16} /> },
  { view: "onboarding", label: "Bienvenue", icon: <Sparkles size={16} /> },
];

export interface ViewProps {
  client: CoreClient;
  env: AppEnv;
  param: string;
  go(route: string): void;
}

export function AppWindow({
  client,
  env,
  initial,
}: {
  client: CoreClient;
  env: AppEnv;
  initial: string;
}) {
  const [route, setRoute] = useState<Route>(() => parseRoute(initial));
  // Asking for the same view again ("Note rapide" twice) must still reset
  // it, so each request gets its own key.
  const [visit, setVisit] = useState(0);
  const link = useStatus(client);

  const go = (text: string) => {
    setRoute(parseRoute(text));
    setVisit((v) => v + 1);
  };

  useEffect(() => env.onView(go), [env]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Escape is the hotkey fields' way out: they stop it themselves.
      if (event.key === "Escape" && !event.defaultPrevented) env.close();
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [env]);

  const props: ViewProps = { client, env, param: route.param, go };
  const key = `${formatRoute(route)}#${visit}`;

  return (
    <div className="lw-app">
      <nav className="lw-nav" aria-label="Sections">
        <div className="lw-nav-title">Little Wizard</div>
        {NAV.map((item) => (
          <button
            key={item.view}
            aria-current={route.view === item.view ? "page" : undefined}
            onClick={() => go(item.view)}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        {link !== "online" && (
          <div className="lw-meta lw-error" style={{ padding: "0 var(--lw-space-3)" }}>
            Le cœur ne répond pas : reconnexion…
          </div>
        )}
      </nav>
      <main className="lw-page" key={key}>
        {route.view === "settings" && <SettingsView {...props} />}
        {route.view === "history" && <HistoryView {...props} />}
        {route.view === "clipboard" && <ClipsView {...props} kind="clips" />}
        {route.view === "notes" && <ClipsView {...props} kind="notes" />}
        {route.view === "reminders" && <RemindersView {...props} />}
        {route.view === "hooks" && <HooksView {...props} />}
        {route.view === "onboarding" && <OnboardingView {...props} />}
        {route.view === "agent" && <AgentView {...props} />}
      </main>
    </div>
  );
}
