import { createRoot } from "react-dom/client";

import { installTokens } from "../design/tokens";
import { createClient } from "./connect";
import { PanelView } from "./PanelView";
import { tauriEnv } from "./tauriEnv";

installTokens();

createRoot(document.getElementById("root")!).render(
  <PanelView client={createClient("panel")} env={tauriEnv} />,
);
