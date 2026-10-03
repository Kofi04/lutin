import { createRoot } from "react-dom/client";

import { createClient } from "./connect";
import { PanelView } from "./PanelView";
import { tauriEnv } from "./tauriEnv";

createRoot(document.getElementById("root")!).render(
  <PanelView client={createClient("panel")} env={tauriEnv} />,
);
