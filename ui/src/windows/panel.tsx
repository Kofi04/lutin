import { createRoot } from "react-dom/client";

import { installTokens } from "../design/tokens";
import { Panel } from "../panel/Panel";
import { createClient } from "./connect";
import { tauriEnv } from "./tauriEnv";

installTokens();

createRoot(document.getElementById("root")!).render(
  <Panel client={createClient("panel")} env={tauriEnv} />,
);
